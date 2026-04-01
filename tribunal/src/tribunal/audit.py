"""Audit logger — records all tool executions for compliance.

Features:
- JSONL append-only audit trail
- Automatic log rotation at configurable size (default 10MB)
- Configurable retention (default 5 archived logs)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .protocol import HookEvent

# Rotation defaults
DEFAULT_MAX_BYTES = 10_000_000  # 10 MB
DEFAULT_KEEP_ROTATED = 5


def rotate_audit_log(
    audit_path: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP_ROTATED,
) -> bool:
    """Rotate audit log if it exceeds max_bytes. Returns True if rotated."""
    audit_path = Path(audit_path)
    if not audit_path.exists():
        return False
    try:
        if audit_path.stat().st_size < max_bytes:
            return False
    except OSError:
        return False

    # Shift existing rotated files: .5 → delete, .4 → .5, .3 → .4, etc.
    for i in range(keep, 0, -1):
        src = audit_path.with_suffix(f".{i}.jsonl")
        if i == keep:
            if src.exists():
                src.unlink()
        else:
            dst = audit_path.with_suffix(f".{i + 1}.jsonl")
            if src.exists():
                src.rename(dst)

    # Move current log to .1
    audit_path.rename(audit_path.with_suffix(".1.jsonl"))
    return True


def audit_stats(audit_path: str | Path) -> dict[str, int | str]:
    """Return basic stats about the audit log (size, entry count)."""
    path = Path(audit_path)
    if not path.is_file():
        return {"entries": 0, "bytes": 0, "rotated_files": 0}

    text = path.read_text()
    entry_count = sum(1 for line in text.strip().split("\n") if line.strip())
    size = path.stat().st_size

    # Count rotated files
    rotated = 0
    for i in range(1, DEFAULT_KEEP_ROTATED + 1):
        if path.with_suffix(f".{i}.jsonl").exists():
            rotated += 1

    return {"entries": entry_count, "bytes": size, "rotated_files": rotated}


def log_event(event: HookEvent, verdict_allow: bool, rule_name: str = "") -> None:
    """Append a structured log entry to .tribunal/audit.jsonl."""
    log_dir = Path(event.cwd) / ".tribunal"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audit.jsonl"

    # Rotate if needed (before writing)
    rotate_audit_log(log_file)

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
