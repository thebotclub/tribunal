"""Team Dashboard API — lightweight HTTP server for multi-project governance.

Aggregates audit, cost, and agent data across projects for team-wide visibility.
Used by the VS Code extension's dashboard panel and CI/CD integrations.

Usage:
    tribunal-dashboard --port 8700 --data-dir /shared/tribunal-data

Endpoints:
    GET  /api/health              Server health check
    GET  /api/projects            List tracked projects
    GET  /api/projects/:id/audit  Audit log for a project
    GET  /api/projects/:id/cost   Cost data for a project
    GET  /api/projects/:id/agents Agent tree for a project
    POST /api/projects/:id/report Submit audit/cost data from a project
    GET  /api/summary             Aggregated cross-project summary
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs


class DashboardStore:
    """File-backed storage for team dashboard data."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        # Sanitize and use hash-based ID
        safe_id = "".join(c for c in project_id if c.isalnum() or c in "-_")[:64]
        d = self.projects_dir / safe_id
        d.mkdir(exist_ok=True)
        return d

    def list_projects(self) -> list[dict[str, Any]]:
        projects = []
        if not self.projects_dir.is_dir():
            return projects
        for d in sorted(self.projects_dir.iterdir()):
            if d.is_dir():
                meta_path = d / "meta.json"
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text())
                        meta["id"] = d.name
                        projects.append(meta)
                    except (json.JSONDecodeError, OSError):
                        projects.append({"id": d.name, "name": d.name})
                else:
                    projects.append({"id": d.name, "name": d.name})
        return projects

    def store_report(self, project_id: str, data: dict[str, Any]) -> None:
        pdir = self._project_dir(project_id)

        # Update metadata
        meta = {
            "name": data.get("project_name", project_id),
            "last_report": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (pdir / "meta.json").write_text(json.dumps(meta, indent=2))

        # Append cost snapshot
        if "cost" in data:
            with open(pdir / "cost.jsonl", "a") as f:
                entry = {"ts": meta["last_report"], **data["cost"]}
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")

        # Append audit entries
        if "audit_entries" in data:
            with open(pdir / "audit.jsonl", "a") as f:
                for entry in data["audit_entries"]:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")

        # Store agent snapshot
        if "agents" in data:
            (pdir / "agents.json").write_text(json.dumps(data["agents"], indent=2))

    def get_audit(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        path = self._project_dir(project_id) / "audit.jsonl"
        if not path.is_file():
            return []
        lines = path.read_text().strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def get_cost(self, project_id: str) -> list[dict[str, Any]]:
        path = self._project_dir(project_id) / "cost.jsonl"
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text().strip().split("\n"):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def get_agents(self, project_id: str) -> dict[str, Any]:
        path = self._project_dir(project_id) / "agents.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def get_summary(self) -> dict[str, Any]:
        projects = self.list_projects()
        total_cost = 0.0
        total_blocked = 0
        total_entries = 0

        for p in projects:
            pid = p["id"]
            cost_entries = self.get_cost(pid)
            if cost_entries:
                last = cost_entries[-1]
                total_cost += last.get("session_cost_usd", 0)

            audit = self.get_audit(pid, limit=1000)
            total_entries += len(audit)
            total_blocked += sum(1 for e in audit if not e.get("allowed", True))

        return {
            "project_count": len(projects),
            "total_cost_usd": round(total_cost, 4),
            "total_audit_entries": total_entries,
            "total_blocked": total_blocked,
            "projects": projects,
        }


def make_handler(store: DashboardStore) -> type:
    """Create a request handler class with access to the store."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def _send_json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # CORS for VS Code extension
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: int, message: str) -> None:
            self._send_json({"error": message}, status)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path == "/api/health":
                self._send_json({"status": "ok", "version": "0.1.0"})
            elif path == "/api/projects":
                self._send_json(store.list_projects())
            elif path == "/api/summary":
                self._send_json(store.get_summary())
            elif path.startswith("/api/projects/"):
                parts = path.split("/")
                if len(parts) >= 5:
                    project_id = parts[3]
                    resource = parts[4]
                    if resource == "audit":
                        self._send_json(store.get_audit(project_id))
                    elif resource == "cost":
                        self._send_json(store.get_cost(project_id))
                    elif resource == "agents":
                        self._send_json(store.get_agents(project_id))
                    else:
                        self._send_error(404, f"Unknown resource: {resource}")
                else:
                    self._send_error(400, "Missing resource path")
            else:
                self._send_error(404, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path.startswith("/api/projects/") and path.endswith("/report"):
                parts = path.split("/")
                if len(parts) >= 5:
                    project_id = parts[3]
                    content_length = int(self.headers.get("Content-Length", 0))
                    if content_length > 1_000_000:  # 1MB limit
                        self._send_error(413, "Payload too large")
                        return
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        self._send_error(400, "Invalid JSON")
                        return
                    store.store_report(project_id, data)
                    self._send_json({"status": "ok"})
                else:
                    self._send_error(400, "Missing project ID")
            else:
                self._send_error(404, "Not found")

        def log_message(self, format: str, *args: Any) -> None:
            # Quieter logging
            sys.stderr.write(f"[dashboard] {args[0]} {args[1]} {args[2]}\n")

    return DashboardHandler


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="tribunal-dashboard",
        description="Tribunal Team Dashboard API server",
    )
    parser.add_argument("--port", type=int, default=8700, help="Port to listen on")
    parser.add_argument(
        "--data-dir",
        default=os.path.expanduser("~/.tribunal/dashboard"),
        help="Directory for dashboard data storage",
    )
    args = parser.parse_args()

    store = DashboardStore(args.data_dir)
    handler_class = make_handler(store)
    server = HTTPServer(("127.0.0.1", args.port), handler_class)

    print(f"  ⚖  Tribunal Team Dashboard")
    print(f"  Listening on http://127.0.0.1:{args.port}")
    print(f"  Data dir: {args.data_dir}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
