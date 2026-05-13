"""Adapter installers -- wire Tribunal into each agent's local config.

For Claude Code we edit ``~/.claude/settings.json`` and add (or refresh) a
``hooks`` entry that forwards every hook event to the Tribunal daemon via
the ``tribunal adapter claude-code`` shim command.

For Cursor we drop a config file under the user's Cursor data directory
(W4). Each installer:

  - Is idempotent -- safe to run repeatedly.
  - Backs up the existing file the first time it writes.
  - Honours dry-run mode for the CLI's ``--dry-run`` flag.
  - Reports what it would do via :class:`InstallReport`.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# -- Result type --------------------------------------------------------------


@dataclass
class InstallReport:
    """Structured result of an install attempt."""

    agent: str
    target_path: str
    installed: bool = False
    already_installed: bool = False
    dry_run: bool = False
    backup_path: str = ""
    changes: list[str] = field(default_factory=list)
    error: str = ""


# -- Claude Code installer ----------------------------------------------------

_CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "Stop",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "Notification",
)


def _claude_settings_path() -> Path:
    """Return the platform-correct path to Claude Code's settings.json."""
    return Path.home() / ".claude" / "settings.json"


def _hook_command() -> list[str]:
    """The command Claude Code runs for each hook event."""
    # Use the installed CLI; falls back to ``python -m tribunal.cli`` for
    # source checkouts where the entry point may not be on $PATH.
    return ["tribunal", "adapter", "claude-code"]


def install_claude_code(
    *, dry_run: bool = False, settings_path: Optional[Path] = None
) -> InstallReport:
    """Add (or refresh) Tribunal hooks in Claude Code's settings.json.

    The resulting block looks like::

        "hooks": {
          "PreToolUse":  [{"matcher": "*", "hooks": [{"type": "command",
                                                       "command": "tribunal adapter claude-code"}]}],
          "PostToolUse": [...],
          ...
        }
    """
    target = settings_path or _claude_settings_path()
    report = InstallReport(
        agent="claude-code", target_path=str(target), dry_run=dry_run
    )

    settings = _read_json_safe(target)
    changes: list[str] = []

    hooks = settings.setdefault("hooks", {})
    hook_cmd = _hook_command()
    desired = [{"type": "command", "command": " ".join(hook_cmd)}]

    for event in _CLAUDE_HOOK_EVENTS:
        existing = hooks.get(event) or []
        if _has_tribunal_hook(existing):
            continue
        changes.append(f"add Tribunal hook for {event}")
        # Claude's settings shape: list of {matcher, hooks}
        existing.append({"matcher": "*", "hooks": desired})
        hooks[event] = existing

    if not changes:
        report.already_installed = True
        return report

    report.changes = changes
    if dry_run:
        return report

    if target.exists():
        backup = target.with_suffix(f".json.bak.{int(time.time())}")
        shutil.copy2(target, backup)
        report.backup_path = str(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    report.installed = True
    return report


def uninstall_claude_code(*, settings_path: Optional[Path] = None) -> InstallReport:
    """Remove Tribunal hooks but keep the user's other hooks intact."""
    target = settings_path or _claude_settings_path()
    report = InstallReport(agent="claude-code", target_path=str(target))

    settings = _read_json_safe(target)
    hooks = settings.get("hooks") or {}
    changed = False
    for event, entries in list(hooks.items()):
        filtered = [e for e in entries if not _entry_is_tribunal(e)]
        if filtered != entries:
            changed = True
            report.changes.append(f"remove Tribunal hook from {event}")
            if filtered:
                hooks[event] = filtered
            else:
                del hooks[event]

    if not changed:
        return report

    backup = target.with_suffix(f".json.bak.{int(time.time())}")
    if target.exists():
        shutil.copy2(target, backup)
        report.backup_path = str(backup)
    target.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    report.installed = True
    return report


# -- Cursor installer (skeleton -- Week 4 will wire the matching adapter) ------


def _cursor_config_path() -> Path:
    """Return the platform-correct path to Cursor's user config."""
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "settings.json"
        )
    if system == "Windows":  # pragma: no cover
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "settings.json"
    # Linux
    return Path.home() / ".config" / "Cursor" / "User" / "settings.json"


def install_cursor(
    *, dry_run: bool = False, settings_path: Optional[Path] = None
) -> InstallReport:
    """Wire Tribunal into Cursor via its MCP/extension hooks.

    Cursor 0.40+ supports MCP servers and external command hooks. We add a
    ``tribunal.mcp.url`` and a ``tribunal.audit.command`` entry under the
    user settings; the matching adapter (W4) will use those to relay
    events. For older Cursor versions we fall back to a recommended
    extension that the user installs from the marketplace.
    """
    target = settings_path or _cursor_config_path()
    report = InstallReport(agent="cursor", target_path=str(target), dry_run=dry_run)
    settings = _read_json_safe(target)

    daemon_url = settings.get("tribunal.daemon.url")
    audit_cmd = settings.get("tribunal.audit.command")
    changes: list[str] = []

    if daemon_url != "http://127.0.0.1:8088":
        changes.append("set tribunal.daemon.url")
    if audit_cmd != "tribunal adapter cursor":
        changes.append("set tribunal.audit.command")

    if not changes:
        report.already_installed = True
        return report

    settings["tribunal.daemon.url"] = "http://127.0.0.1:8088"
    settings["tribunal.audit.command"] = "tribunal adapter cursor"

    report.changes = changes
    if dry_run:
        return report
    if target.exists():
        backup = target.with_suffix(f".json.bak.{int(time.time())}")
        shutil.copy2(target, backup)
        report.backup_path = str(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    report.installed = True
    return report


# -- Helpers ------------------------------------------------------------------


def _read_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        # Don't clobber a hand-edited file with a syntax error.
        raise RuntimeError(f"{path} is not valid JSON -- refusing to overwrite")


def _has_tribunal_hook(entries: list) -> bool:
    return any(_entry_is_tribunal(e) for e in entries)


def _entry_is_tribunal(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks") or []
    for h in inner:
        if isinstance(h, dict) and "tribunal" in str(h.get("command", "")):
            return True
    return False


def detect_installed_agents() -> list[str]:
    """Best-effort detection of which agent configs exist on disk."""
    found: list[str] = []
    if _claude_settings_path().exists() or _claude_settings_path().parent.exists():
        found.append("claude-code")
    if _cursor_config_path().exists() or _cursor_config_path().parent.exists():
        found.append("cursor")
    return found


__all__ = [
    "InstallReport",
    "install_claude_code",
    "uninstall_claude_code",
    "install_cursor",
    "detect_installed_agents",
]
