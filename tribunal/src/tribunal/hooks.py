"""Lifecycle hook handlers — process Claude Code hook event types.

Provides handlers for each hook event type beyond the basic
PreToolUse/PostToolUse rule evaluation. All handlers are self-contained
and only depend on protocol, audit, and io modules.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .audit import log_event
from .io import atomic_write_json, locked_read_json
from .protocol import HookEvent, HookVerdict


def handle_session_end(event: HookEvent) -> HookVerdict:
    """Handle SessionEnd — log session completion."""
    log_event(event, True, "session-end")
    return HookVerdict(allow=True, additional_context="Session ended.")


def handle_post_tool_failure(event: HookEvent) -> HookVerdict:
    """Handle PostToolUseFailure — track failure patterns per tool."""
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    failures = state.get("tool_failures", {})
    tool = event.tool_name or "unknown"
    failures.setdefault(tool, {"count": 0, "last_error": "", "last_ts": ""})
    failures[tool]["count"] += 1
    failures[tool]["last_error"] = (event.error or "")[:200]
    failures[tool]["last_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["tool_failures"] = failures

    atomic_write_json(state_path, state)
    log_event(event, True, f"tool-failure:{tool}")

    count = failures[tool]["count"]
    if count >= 3:
        return HookVerdict(
            allow=True,
            additional_context=f"⚠️ {tool} has failed {count} times this session.",
        )

    return HookVerdict(allow=True)


def handle_file_changed(event: HookEvent) -> HookVerdict:
    """Handle FileChanged — log external file modifications."""
    log_event(event, True, "file-changed")
    return HookVerdict(allow=True)


def handle_cwd_changed(event: HookEvent) -> HookVerdict:
    """Handle CwdChanged — reload rules for new project context."""
    log_event(event, True, "cwd-changed")
    return HookVerdict(
        allow=True,
        additional_context=f"Tribunal: project context switched to {event.cwd}",
    )


def handle_config_change(event: HookEvent) -> HookVerdict:
    """Handle ConfigChange — detect unauthorized config/permissions changes."""
    log_event(event, True, "config-changed")
    return HookVerdict(
        allow=True,
        additional_context="⚠️ Tribunal: configuration was modified mid-session.",
    )


def handle_permission_request(event: HookEvent) -> HookVerdict:
    """Handle PermissionRequest — audit permission requests."""
    log_event(event, True, "permission-request")

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)
    granted = state.get("permissions_granted", [])
    granted.append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": event.tool_name or "",
            "session_id": event.session_id or "",
        }
    )
    state["permissions_granted"] = granted[-100:]
    atomic_write_json(state_path, state)

    return HookVerdict(allow=True)


def handle_permission_denied(event: HookEvent) -> HookVerdict:
    """Handle PermissionDenied — log denied permissions and detect escalation."""
    log_event(event, False, "permission-denied")

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    denied = state.get("permissions_denied", [])
    denied.append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": event.tool_name or "",
            "session_id": event.session_id or "",
        }
    )
    state["permissions_denied"] = denied[-100:]

    tool = event.tool_name or ""
    if tool:
        granted = state.get("permissions_granted", [])
        escalations = state.get("permission_escalations", [])
        for g in granted:
            if g.get("tool") == tool:
                escalations.append(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "tool": tool,
                        "type": "grant-then-deny",
                    }
                )
                break
        state["permission_escalations"] = escalations[-50:]

    atomic_write_json(state_path, state)
    return HookVerdict(allow=True)


def handle_pre_compact(event: HookEvent) -> HookVerdict:
    """Handle PreCompact — save critical state before context compaction."""
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    compactions = state.get("compaction_events", [])
    compactions.append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "pre",
            "session_id": event.session_id or "",
        }
    )
    state["compaction_events"] = compactions[-100:]
    state["compaction_count"] = state.get("compaction_count", 0) + 1
    atomic_write_json(state_path, state)

    log_event(event, True, "pre-compact")
    return HookVerdict(allow=True)


def handle_post_compact(event: HookEvent) -> HookVerdict:
    """Handle PostCompact — log compaction completion."""
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    compactions = state.get("compaction_events", [])
    compactions.append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "post",
            "session_id": event.session_id or "",
        }
    )
    state["compaction_events"] = compactions[-100:]
    atomic_write_json(state_path, state)

    log_event(event, True, "post-compact")
    return HookVerdict(
        allow=True,
        additional_context="Tribunal: rules re-injected after context compaction.",
    )


def handle_subagent_start(event: HookEvent) -> HookVerdict:
    """Handle SubagentStart — track sub-agent lifecycle."""
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    agents = state.get("active_agents", {})
    agent_id = event.agent_id or event.session_id or "unknown"
    agents[agent_id] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_type": event.agent_type or "",
        "tool_calls": 0,
    }
    state["active_agents"] = agents
    atomic_write_json(state_path, state)

    log_event(event, True, f"subagent-start:{agent_id}")
    return HookVerdict(allow=True)


def handle_subagent_stop(event: HookEvent) -> HookVerdict:
    """Handle SubagentStop — finalize sub-agent tracking."""
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    agent_id = event.agent_id or event.session_id or "unknown"
    agents = state.get("active_agents", {})
    if agent_id in agents:
        agents[agent_id]["stopped_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        completed = state.get("completed_agents", [])
        completed.append(agents.pop(agent_id))
        state["completed_agents"] = completed[-50:]
        state["active_agents"] = agents
        atomic_write_json(state_path, state)

    log_event(event, True, f"subagent-stop:{agent_id}")
    return HookVerdict(allow=True)


def handle_task_created(event: HookEvent) -> HookVerdict:
    """Handle TaskCreated — track task lifecycle."""
    log_event(event, True, "task-created")
    return HookVerdict(allow=True)


def handle_task_completed(event: HookEvent) -> HookVerdict:
    """Handle TaskCompleted — track task completion."""
    log_event(event, True, "task-completed")
    return HookVerdict(allow=True)


# ── Handler Registry ──────────────────────────────────────────────────────────

LIFECYCLE_HANDLERS: dict[str, Any] = {
    "SessionEnd": handle_session_end,
    "PostToolUseFailure": handle_post_tool_failure,
    "FileChanged": handle_file_changed,
    "CwdChanged": handle_cwd_changed,
    "ConfigChange": handle_config_change,
    "PermissionRequest": handle_permission_request,
    "PermissionDenied": handle_permission_denied,
    "PreCompact": handle_pre_compact,
    "PostCompact": handle_post_compact,
    "SubagentStart": handle_subagent_start,
    "SubagentStop": handle_subagent_stop,
    "TaskCreated": handle_task_created,
    "TaskCompleted": handle_task_completed,
}
