"""Cursor adapter — translate Cursor IDE events to v1 unified events.

Cursor's hook model is different from Claude Code:

  - Cursor runs an internal chat agent + the "Agent" sidebar + Composer.
  - There are no first-party shell hooks (yet), so Tribunal taps Cursor
    via three complementary channels:

      1. **MCP server**: Cursor 0.40+ talks to MCP servers, and we ship a
         tiny one that wraps the Tribunal daemon. Every tool call routed
         through MCP becomes a ``tool.proposed`` / ``tool.executed`` pair.

      2. **Cursor Extension** (VS Code extension API, shipped from W5).
         The extension subscribes to ``vscode.workspace.onWillSaveTextDocument``,
         ``onDidChangeTextDocument``, terminal lifecycle, and the
         ``cursorless.agent.*`` event stream Cursor exposes for chat
         turns. Each event is POSTed to the local daemon as JSON.

      3. **Logfile tail** (fallback): for Cursor versions without the
         events API, the extension scrapes Cursor's chat transcript log
         under ``~/Library/Application Support/Cursor/logs``. Lossy but
         keeps audit coverage for older installs.

This module is the translator that the three channels feed into. Each
channel produces a JSON message whose ``type`` field selects a handler.
The function names and shapes mirror ``claude_code.py`` so the daemon
can dispatch by agent without special-casing.
"""

import os
import socket
from typing import Any, Callable, Mapping

from tribunal.events.schema import new_event

AGENT_ID = "cursor"

Emit = Callable[[dict[str, Any]], None]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _machine_id() -> str:
    try:
        return socket.gethostname()
    except OSError:  # pragma: no cover
        return "unknown"


def _user_id(payload: Mapping[str, Any]) -> str:
    return (
        str(payload.get("user_id") or "")
        or os.environ.get("TRIBUNAL_USER_ID")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )


def _common_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "agent": AGENT_ID,
        "agent_version": str(payload.get("cursor_version") or "unknown"),
        "session_id": str(
            payload.get("session_id") or payload.get("chat_id") or "unknown"
        ),
        "user_id": _user_id(payload),
        "machine_id": _machine_id(),
        "repo_path": payload.get("workspace_root") or payload.get("cwd") or os.getcwd(),
    }


# ── Translators ──────────────────────────────────────────────────────────────


def on_chat_open(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="session.start",
            payload={"source": "cursor.chat", "model": payload.get("model") or ""},
            **_common_fields(payload),
        )
    )


def on_chat_close(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="session.end",
            payload={
                "reason": payload.get("reason") or "user",
                "turns": payload.get("turn_count"),
            },
            **_common_fields(payload),
        )
    )


def on_user_message(payload: Mapping[str, Any], emit: Emit) -> None:
    text = payload.get("text") or payload.get("prompt") or ""
    emit(
        new_event(
            event_type="prompt.submitted",
            payload={"prompt": text, "prompt_length": len(text)},
            **_common_fields(payload),
        )
    )


def on_tool_call(payload: Mapping[str, Any], emit: Emit) -> None:
    """Cursor's MCP tool-call lifecycle: one event for the proposal."""
    tool_name = payload.get("tool") or "unknown"
    args = payload.get("args") or {}
    extra: dict[str, Any] = {}
    if tool_name == "shell":
        extra["command"] = args.get("command", "")
    elif tool_name in ("read_file", "write_file", "edit_file"):
        extra["path"] = args.get("path", "")
    elif tool_name.startswith("mcp."):
        extra["mcp_server"] = tool_name[len("mcp.") :].split(".")[0]

    emit(
        new_event(
            event_type="tool.proposed",
            payload={"tool_name": tool_name, "tool_input": args, **extra},
            **_common_fields(payload),
        )
    )


def on_tool_result(payload: Mapping[str, Any], emit: Emit) -> None:
    success = bool(payload.get("ok", True))
    tool_name = payload.get("tool") or "unknown"
    emit(
        new_event(
            event_type="tool.executed" if success else "tool.failed",
            payload={
                "tool_name": tool_name,
                "tool_response": payload.get("result") or {},
                "error": payload.get("error") or "",
            },
            **_common_fields(payload),
        )
    )

    args = payload.get("args") or {}
    if not success:
        return
    if tool_name == "write_file":
        emit(
            new_event(
                event_type="file.write",
                payload={
                    "path": args.get("path", ""),
                    "bytes": len(str(args.get("content", ""))),
                },
                **_common_fields(payload),
            )
        )
    elif tool_name == "read_file":
        emit(
            new_event(
                event_type="file.read",
                payload={"path": args.get("path", "")},
                **_common_fields(payload),
            )
        )
    elif tool_name == "shell":
        emit(
            new_event(
                event_type="bash.executed",
                payload={
                    "command": args.get("command", ""),
                    "exit_code": (payload.get("result") or {}).get("exit_code"),
                    "stdout_truncated": str(
                        (payload.get("result") or {}).get("stdout", "")
                    )[:500],
                },
                **_common_fields(payload),
            )
        )


def on_file_save(payload: Mapping[str, Any], emit: Emit) -> None:
    """vscode.workspace.onDidSaveTextDocument fired from the extension."""
    path = payload.get("path") or ""
    if not path:
        return
    emit(
        new_event(
            event_type="file.write",
            payload={"path": path, "bytes": int(payload.get("size") or 0)},
            **_common_fields(payload),
        )
    )


def on_cost(payload: Mapping[str, Any], emit: Emit) -> None:
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


# ── Dispatcher ───────────────────────────────────────────────────────────────


TYPE_MAP: dict[str, Callable[[Mapping[str, Any], Emit], None]] = {
    "chat.open": on_chat_open,
    "chat.close": on_chat_close,
    "user.message": on_user_message,
    "tool.call": on_tool_call,
    "tool.result": on_tool_result,
    "file.save": on_file_save,
    "cost.recorded": on_cost,
}


def translate(payload: Mapping[str, Any], emit: Emit) -> int:
    """Translate a Cursor channel message; returns events emitted."""
    type_ = str(payload.get("type") or "")
    handler = TYPE_MAP.get(type_)
    counter = _Counter()
    if handler is None:
        # Unknown type — emit as error.gate so the audit log doesn't
        # silently lose data.
        counter(
            new_event(
                event_type="error.gate",
                payload={"unknown_type": type_, "raw": str(payload)[:1000]},
                **_common_fields(payload),
            )
        )
    else:
        handler(payload, counter)
    counter.flush(emit)
    return counter.count


class _Counter:
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
    "TYPE_MAP",
    "translate",
    "on_chat_open",
    "on_chat_close",
    "on_user_message",
    "on_tool_call",
    "on_tool_result",
    "on_file_save",
    "on_cost",
]
