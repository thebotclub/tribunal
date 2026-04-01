"""Audit logger — records all tool executions for compliance."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .protocol import HookEvent


def log_event(event: HookEvent, verdict_allow: bool, rule_name: str = "") -> None:
    """Append a structured log entry to .tribunal/audit.jsonl."""
    log_dir = Path(event.cwd) / ".tribunal"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audit.jsonl"

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch": time.time(),
        "session_id": event.session_id,
        "hook": event.hook_event_name,
        "tool": event.tool_name,
        "allowed": verdict_allow,
    }

    if rule_name:
        entry["rule"] = rule_name

    # Log file path if present
    file_path = _extract_path_from_input(event.tool_input)
    if file_path:
        entry["path"] = file_path

    # For Bash, log the command (truncated)
    if event.tool_name == "Bash" and "command" in event.tool_input:
        cmd = event.tool_input["command"]
        entry["command"] = cmd[:200] + ("…" if len(cmd) > 200 else "")

    with open(log_file, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _extract_path_from_input(tool_input: dict) -> str | None:
    for key in ("path", "file_path", "filePath", "filename"):
        if key in tool_input:
            return tool_input[key]
    return None
