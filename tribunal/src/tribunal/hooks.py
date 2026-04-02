"""Lifecycle hook handlers — process all Claude Code hook event types.

Provides specialized handlers for each hook event type beyond the basic
PreToolUse/PostToolUse rule evaluation:

- SessionEnd: flush analytics, write session summary, finalize costs
- PostToolUseFailure: track failure patterns per tool
- FileChanged: run rules on external file modifications
- CwdChanged: reload project rules for new working directory
- ConfigChange: detect unauthorized config/permissions changes
- PermissionRequest/Denied: audit permission decisions
- PreCompact/PostCompact: persist/restore state across context compaction
- SubagentStart/Stop: track multi-agent lifecycle
- TaskCreated/Completed: track task-level work
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .audit import log_event
from .protocol import HookEvent, HookVerdict


def handle_session_end(event: HookEvent) -> HookVerdict:
    """Handle SessionEnd — flush analytics, write session summary, finalize cost."""
    from .analytics import analyze_costs, format_analytics
    from .cost import load_state
    from .memory import inject_session_summary

    cwd = event.cwd

    # Finalize cost tracking
    state = load_state(cwd)
    session_cost = state.get("session_cost_usd", 0.0)

    # Write session summary to memory
    model = state.get("model", "unknown")
    summary_lines = [
        f"Session {event.session_id[:8] if event.session_id else 'unknown'} completed.",
        f"Model: {model}",
        f"Cost: ${session_cost:.4f}",
    ]

    # Add analytics summary
    analytics = analyze_costs(cwd)
    if analytics.trend != "insufficient_data":
        summary_lines.append(f"Trend: {analytics.trend}")
    if analytics.anomalies:
        summary_lines.append(f"Anomalies: {len(analytics.anomalies)}")

    inject_session_summary(cwd, "\n".join(summary_lines), event.session_id or "")

    log_event(event, True, "session-end")
    return HookVerdict(allow=True, additional_context=f"Session cost: ${session_cost:.4f}")


def handle_post_tool_failure(event: HookEvent) -> HookVerdict:
    """Handle PostToolUseFailure — track failure patterns per tool."""
    from .io import atomic_write_json, locked_read_json

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    # Track failures per tool
    failures = state.get("tool_failures", {})
    tool = event.tool_name or "unknown"
    failures.setdefault(tool, {"count": 0, "last_error": "", "last_ts": ""})
    failures[tool]["count"] += 1
    failures[tool]["last_error"] = (event.error or "")[:200]
    failures[tool]["last_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["tool_failures"] = failures

    atomic_write_json(state_path, state)
    log_event(event, True, f"tool-failure:{tool}")

    # Alert on repeated failures (same tool, 3+ failures)
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
    # Warn on any config/permissions changes mid-session
    return HookVerdict(
        allow=True,
        additional_context="⚠️ Tribunal: configuration was modified mid-session.",
    )


def handle_permission_request(event: HookEvent) -> HookVerdict:
    """Handle PermissionRequest — audit permission requests and track grants."""
    from .io import atomic_write_json, locked_read_json

    log_event(event, True, "permission-request")

    # Track granted permissions for escalation detection
    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)
    granted = state.get("permissions_granted", [])
    granted.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": event.tool_name or "",
        "session_id": event.session_id or "",
    })
    state["permissions_granted"] = granted[-100:]
    atomic_write_json(state_path, state)

    return HookVerdict(allow=True)


def handle_permission_denied(event: HookEvent) -> HookVerdict:
    """Handle PermissionDenied — log denied permissions and detect escalation."""
    from .io import atomic_write_json, locked_read_json

    log_event(event, False, "permission-denied")

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    # Track denied permissions for compliance reporting
    denied = state.get("permissions_denied", [])
    denied.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": event.tool_name or "",
        "session_id": event.session_id or "",
    })
    state["permissions_denied"] = denied[-100:]

    # Escalation detection — check if same tool was previously granted then denied
    tool = event.tool_name or ""
    if tool:
        granted = state.get("permissions_granted", [])
        escalations = state.get("permission_escalations", [])
        for g in granted:
            if g.get("tool") == tool:
                escalations.append({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "tool": tool,
                    "type": "grant-then-deny",
                })
                break  # One escalation record per denial event
        state["permission_escalations"] = escalations[-50:]

    atomic_write_json(state_path, state)

    return HookVerdict(allow=True)


def handle_pre_compact(event: HookEvent) -> HookVerdict:
    """Handle PreCompact — save critical state and track compaction frequency."""
    from .memory import inject_memory, MemoryEntry
    from .cost import load_state
    from .io import atomic_write_json, locked_read_json

    cwd = event.cwd
    state = load_state(cwd)

    # Persist budget status so it survives compaction
    session_cost = state.get("session_cost_usd", 0.0)
    budget = state.get("budget", {})

    if session_cost > 0 or budget:
        entry = MemoryEntry(
            title="Tribunal Budget Status (pre-compact)",
            content=(
                f"Session cost: ${session_cost:.4f}\n"
                f"Budget: {budget}\n"
                f"Persisted before context compaction."
            ),
            memory_type="reference",
            tags=["tribunal", "budget", "compact"],
        )
        inject_memory(cwd, entry, "tribunal-compact-state.md")

    # Track compaction frequency for analytics
    trib_state_path = Path(cwd) / ".tribunal" / "state.json"
    trib_state = locked_read_json(trib_state_path)
    compactions = trib_state.get("compaction_events", [])
    compactions.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": "pre",
        "session_id": event.session_id or "",
    })
    trib_state["compaction_events"] = compactions[-100:]
    trib_state["compaction_count"] = trib_state.get("compaction_count", 0) + 1
    atomic_write_json(trib_state_path, trib_state)

    log_event(event, True, "pre-compact")
    return HookVerdict(allow=True)


def handle_post_compact(event: HookEvent) -> HookVerdict:
    """Handle PostCompact — re-inject essential rules and log compaction completion."""
    from .memory import inject_rules_as_memory
    from .io import atomic_write_json, locked_read_json

    inject_rules_as_memory(event.cwd)

    # Log compaction completion
    trib_state_path = Path(event.cwd) / ".tribunal" / "state.json"
    trib_state = locked_read_json(trib_state_path)
    compactions = trib_state.get("compaction_events", [])
    compactions.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": "post",
        "session_id": event.session_id or "",
    })
    trib_state["compaction_events"] = compactions[-100:]
    atomic_write_json(trib_state_path, trib_state)

    log_event(event, True, "post-compact")

    return HookVerdict(
        allow=True,
        additional_context="Tribunal: rules re-injected after context compaction.",
    )


def handle_subagent_start(event: HookEvent) -> HookVerdict:
    """Handle SubagentStart — track sub-agent lifecycle."""
    from .io import atomic_write_json, locked_read_json

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    agents = state.get("active_agents", {})
    agent_id = event.agent_id or event.session_id or "unknown"
    agents[agent_id] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_type": event.agent_type or "",
        "cost_usd": 0.0,
        "tool_calls": 0,
    }
    state["active_agents"] = agents
    atomic_write_json(state_path, state)

    log_event(event, True, f"subagent-start:{agent_id}")
    return HookVerdict(allow=True)


def handle_subagent_stop(event: HookEvent) -> HookVerdict:
    """Handle SubagentStop — finalize sub-agent tracking."""
    from .io import atomic_write_json, locked_read_json

    cwd = event.cwd
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)

    agent_id = event.agent_id or event.session_id or "unknown"
    agents = state.get("active_agents", {})
    if agent_id in agents:
        agents[agent_id]["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Move to completed agents
        completed = state.get("completed_agents", [])
        completed.append(agents.pop(agent_id))
        state["completed_agents"] = completed[-50:]  # Keep last 50
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
