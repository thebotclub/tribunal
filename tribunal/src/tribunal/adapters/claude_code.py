"""Claude Code adapter — translate Anthropic's hook payloads to v1 events.

Claude Code calls registered hooks with a JSON payload on stdin and reads
a single JSON response from stdout. The Tribunal hook script (``tribunal
adapter claude-code``) reads that payload, calls one of the translators
below, POSTs the resulting event to the local daemon, and prints either
``{}`` (allow) or a structured deny response.

Hook events we translate
------------------------

Anthropic ships ~12 hook event types (UserPromptSubmit, PreToolUse,
PostToolUse, Notification, Stop, SubagentStop, …). We map each to one or
more unified events. The full mapping table lives in the v3 execution
plan §2.1; this module is the executable form of it.

Design rules
------------

  - **One translator per hook event.** Keep each ~10 LOC so it's obvious
    what is mapped where.
  - **Adapters never decide policy.** They only translate. The daemon
    runs the policy engine over the resulting events.
  - **Adapters never make network calls.** They write to a callable
    ``emit`` that the hook wrapper provides. Tests can pass a list-append
    to verify the translator output.
"""

from __future__ import annotations

import os
import socket
from typing import Any, Callable, Mapping

from tribunal.events.schema import new_event

AGENT_ID = "claude-code"

#: Translator signature: takes the raw Anthropic payload, returns a list
#: of zero or more unified events.
Emit = Callable[[dict[str, Any]], None]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _machine_id() -> str:
    """Best-effort stable machine identifier."""
    try:
        return socket.gethostname()
    except OSError:  # pragma: no cover
        return "unknown"


def _agent_version(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("claude_code_version") or payload.get("version") or "unknown"
    )


def _session_id(payload: Mapping[str, Any]) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or "unknown")


def _user_id(payload: Mapping[str, Any]) -> str:
    # Claude Code does not pass user id; we use the OS login or an env var.
    return (
        os.environ.get("TRIBUNAL_USER_ID")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )


def _common_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "agent": AGENT_ID,
        "agent_version": _agent_version(payload),
        "session_id": _session_id(payload),
        "user_id": _user_id(payload),
        "machine_id": _machine_id(),
        "repo_path": payload.get("cwd") or os.getcwd(),
    }


# ── Per-hook translators ─────────────────────────────────────────────────────


def on_session_start(payload: Mapping[str, Any], emit: Emit) -> None:
    """Claude Code SessionStart hook → ``session.start`` event."""
    ev = new_event(
        event_type="session.start",
        payload={
            "source": payload.get("source", "user"),
            "model": payload.get("model") or "",
        },
        **_common_fields(payload),
    )
    emit(ev)


def on_session_stop(payload: Mapping[str, Any], emit: Emit) -> None:
    """SessionEnd / Stop hook → ``session.end`` event."""
    ev = new_event(
        event_type="session.end",
        payload={
            "reason": payload.get("stop_reason") or payload.get("reason") or "unknown",
            "turns": payload.get("turn_count"),
        },
        **_common_fields(payload),
    )
    emit(ev)


def on_user_prompt(payload: Mapping[str, Any], emit: Emit) -> None:
    """UserPromptSubmit hook → ``prompt.submitted`` event."""
    prompt_text = payload.get("prompt") or payload.get("user_prompt") or ""
    ev = new_event(
        event_type="prompt.submitted",
        payload={
            "prompt": prompt_text,
            "prompt_length": len(prompt_text),
        },
        **_common_fields(payload),
    )
    emit(ev)


def on_pre_tool_use(payload: Mapping[str, Any], emit: Emit) -> None:
    """PreToolUse hook → ``tool.proposed`` event.

    Special-cases ``Bash``, ``Read``, ``Write``, ``Edit``, ``WebFetch``,
    ``mcp__*`` so the daemon's policy engine has structured details.
    """
    tool_name = payload.get("tool_name") or "unknown"
    tool_input = payload.get("tool_input") or {}
    extra: dict[str, Any] = {}
    if tool_name == "Bash":
        extra["command"] = tool_input.get("command", "")
    elif tool_name in ("Read", "Write", "Edit"):
        extra["path"] = tool_input.get("file_path", "")
    elif tool_name == "WebFetch":
        extra["url"] = tool_input.get("url", "")
    elif tool_name.startswith("mcp__"):
        extra["mcp_server"] = tool_name.split("__")[1] if "__" in tool_name else ""

    ev = new_event(
        event_type="tool.proposed",
        payload={
            "tool_name": tool_name,
            "tool_input": tool_input,
            **extra,
        },
        **_common_fields(payload),
    )
    emit(ev)


def on_post_tool_use(payload: Mapping[str, Any], emit: Emit) -> None:
    """PostToolUse hook → ``tool.executed`` or ``tool.failed`` event."""
    success = bool(payload.get("success", True))
    event_type = "tool.executed" if success else "tool.failed"

    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}

    # File-write events get a parallel file.write/file.read/file.delete
    # so the audit log has rich file-level history.
    tool_name = payload.get("tool_name") or "unknown"

    ev = new_event(
        event_type=event_type,
        payload={
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": tool_response,
            "error": payload.get("error") or "",
        },
        **_common_fields(payload),
    )
    emit(ev)

    if success and tool_name in ("Write", "Edit"):
        emit(
            new_event(
                event_type="file.write",
                payload={
                    "path": tool_input.get("file_path", ""),
                    "bytes": len(str(tool_input.get("content", ""))),
                },
                **_common_fields(payload),
            )
        )
    elif success and tool_name == "Read":
        emit(
            new_event(
                event_type="file.read",
                payload={"path": tool_input.get("file_path", "")},
                **_common_fields(payload),
            )
        )
    elif success and tool_name == "Bash":
        emit(
            new_event(
                event_type="bash.executed",
                payload={
                    "command": tool_input.get("command", ""),
                    "exit_code": tool_response.get("exit_code"),
                    "stdout_truncated": str(tool_response.get("stdout", ""))[:500],
                },
                **_common_fields(payload),
            )
        )


def on_subagent_start(payload: Mapping[str, Any], emit: Emit) -> None:
    """SubagentStart → ``subagent.start`` event."""
    emit(
        new_event(
            event_type="subagent.start",
            payload={
                "subagent_id": payload.get("subagent_id") or "",
                "subagent_type": payload.get("subagent_type") or "",
            },
            **_common_fields(payload),
        )
    )


def on_subagent_stop(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="subagent.stop",
            payload={
                "subagent_id": payload.get("subagent_id") or "",
                "reason": payload.get("reason") or "",
            },
            **_common_fields(payload),
        )
    )


def on_cost_recorded(payload: Mapping[str, Any], emit: Emit) -> None:
    """Anthropic emits cost data alongside tool turns. Captured separately
    so the cost module can aggregate without re-scanning every event.
    """
    cost = payload.get("cost") or {}
    emit(
        new_event(
            event_type="cost.recorded",
            payload={},
            cost={
                "usd": float(cost.get("usd") or 0),
                "model": cost.get("model") or payload.get("model") or "",
                "input_tokens": int(cost.get("input_tokens") or 0),
                "output_tokens": int(cost.get("output_tokens") or 0),
            },
            **_common_fields(payload),
        )
    )


def on_mcp_call(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="mcp.call.before",
            payload={
                "server": payload.get("mcp_server") or "",
                "method": payload.get("mcp_method") or "",
                "args": payload.get("mcp_args") or {},
            },
            **_common_fields(payload),
        )
    )


# ── Dispatcher ───────────────────────────────────────────────────────────────


HOOK_MAP: dict[str, Callable[[Mapping[str, Any], Emit], None]] = {
    "SessionStart": on_session_start,
    "SessionEnd": on_session_stop,
    "Stop": on_session_stop,
    "UserPromptSubmit": on_user_prompt,
    "PreToolUse": on_pre_tool_use,
    "PostToolUse": on_post_tool_use,
    "SubagentStart": on_subagent_start,
    "SubagentStop": on_subagent_stop,
    "CostRecorded": on_cost_recorded,
    "McpCall": on_mcp_call,
}


def translate(payload: Mapping[str, Any], emit: Emit) -> int:
    """Dispatch the hook payload to its translator. Returns event count.

    The hook event name is taken from ``payload["hook_event_name"]`` (the
    field Anthropic uses). Unknown hooks become a single ``cost.recorded``
    no-op so they're still surfaced in the audit log instead of silently
    dropped.
    """
    name = payload.get("hook_event_name") or payload.get("event") or ""
    handler = HOOK_MAP.get(name)
    if handler is None:
        # Unknown hook → emit a generic event so we never lose signal.
        emit(
            new_event(
                event_type="error.gate",
                payload={"unknown_hook": name, "raw": str(payload)[:1000]},
                **_common_fields(payload),
            )
        )
        return 1
    before = _Counter()
    handler(payload, before)
    before.flush(emit)
    return before.count


class _Counter:
    """Wrapper that counts and forwards events. Tiny utility for tests."""

    def __init__(self) -> None:
        self._events: list[dict] = []

    def __call__(self, ev: dict) -> None:
        self._events.append(ev)

    @property
    def count(self) -> int:
        return len(self._events)

    def flush(self, emit: Emit) -> None:
        for ev in self._events:
            emit(ev)


__all__ = [
    "AGENT_ID",
    "HOOK_MAP",
    "translate",
    "on_session_start",
    "on_session_stop",
    "on_user_prompt",
    "on_pre_tool_use",
    "on_post_tool_use",
    "on_subagent_start",
    "on_subagent_stop",
    "on_cost_recorded",
    "on_mcp_call",
]
