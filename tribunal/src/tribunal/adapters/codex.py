"""OpenAI Codex CLI adapter -- translate codex CLI events to v1 events.

OpenAI's ``codex`` CLI (the open-source TypeScript repl, sibling of
ChatGPT's agentic interpreter) emits structured JSON to ``--log-json``.
Each line is one of:

  - ``{kind: "session_start", ...}``
  - ``{kind: "user", text: "..."}``
  - ``{kind: "assistant_message", text: "..."}``      (we ignore for now)
  - ``{kind: "tool_call", name: "shell|python|...", input: {...}}``
  - ``{kind: "tool_result", call_id, output, exit_code}``
  - ``{kind: "usage", input_tokens, output_tokens, cost_usd, model}``
  - ``{kind: "session_end", reason}``

The wrapper script ``codex-tribunal`` tails that stream and POSTs each
line to the local daemon, which routes through :func:`translate` here.
"""

import os
import socket
from typing import Any, Callable, Mapping

from tribunal.events.schema import new_event

AGENT_ID = "codex-cli"

Emit = Callable[[dict[str, Any]], None]


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


def _common(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "agent": AGENT_ID,
        "agent_version": str(payload.get("codex_version") or "unknown"),
        "session_id": str(payload.get("session_id") or "unknown"),
        "user_id": _user_id(payload),
        "machine_id": _machine_id(),
        "repo_path": payload.get("cwd") or os.getcwd(),
    }


# -- Translators -------------------------------------------------------------


def on_session_start(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="session.start",
            payload={
                "source": "codex-cli",
                "model": payload.get("model") or "",
                "mode": payload.get("mode") or "interactive",
            },
            **_common(payload),
        )
    )


def on_session_end(payload: Mapping[str, Any], emit: Emit) -> None:
    emit(
        new_event(
            event_type="session.end",
            payload={
                "reason": payload.get("reason") or "exit",
                "turn_count": int(payload.get("turn_count") or 0),
            },
            **_common(payload),
        )
    )


def on_user(payload: Mapping[str, Any], emit: Emit) -> None:
    text = str(payload.get("text") or "")
    emit(
        new_event(
            event_type="prompt.submitted",
            payload={"prompt": text, "prompt_length": len(text)},
            **_common(payload),
        )
    )


def on_tool_call(payload: Mapping[str, Any], emit: Emit) -> None:
    name = str(payload.get("name") or "unknown")
    tool_input = payload.get("input") or {}
    extra: dict[str, Any] = {"tool_name": name, "tool_input": tool_input}
    # Map codex tool names to schema-friendly fields
    if name in ("shell", "bash"):
        if isinstance(tool_input, Mapping):
            extra["command"] = str(
                tool_input.get("command") or tool_input.get("cmd") or ""
            )
    elif name == "python":
        if isinstance(tool_input, Mapping):
            extra["command"] = str(tool_input.get("code") or "")
    elif name in ("read_file", "write_file"):
        if isinstance(tool_input, Mapping):
            extra["path"] = str(tool_input.get("path") or "")
    emit(
        new_event(
            event_type="tool.proposed",
            payload=extra,
            **_common(payload),
        )
    )


def on_tool_result(payload: Mapping[str, Any], emit: Emit) -> None:
    output = payload.get("output")
    if isinstance(output, (dict, list)):
        tool_response: Any = output
    else:
        tool_response = str(output or "")
    exit_code = payload.get("exit_code")
    failed = bool(exit_code) and int(exit_code or 0) != 0
    event_type = "tool.failed" if failed else "tool.executed"
    emit(
        new_event(
            event_type=event_type,
            payload={
                "tool_name": str(payload.get("name") or "unknown"),
                "call_id": str(payload.get("call_id") or ""),
                "exit_code": int(exit_code or 0),
                "tool_response": tool_response,
            },
            **_common(payload),
        )
    )


def on_usage(payload: Mapping[str, Any], emit: Emit) -> None:
    cost = float(payload.get("cost_usd") or 0)
    emit(
        new_event(
            event_type="cost.recorded",
            payload={
                "input_tokens": int(payload.get("input_tokens") or 0),
                "output_tokens": int(payload.get("output_tokens") or 0),
            },
            cost={
                "usd": cost,
                "model": str(payload.get("model") or ""),
                "input_tokens": int(payload.get("input_tokens") or 0),
                "output_tokens": int(payload.get("output_tokens") or 0),
            },
            **_common(payload),
        )
    )


# -- Dispatcher --------------------------------------------------------------


KIND_MAP: dict[str, Callable[[Mapping[str, Any], Emit], None]] = {
    "session_start": on_session_start,
    "session_end": on_session_end,
    "user": on_user,
    "tool_call": on_tool_call,
    "tool_result": on_tool_result,
    "usage": on_usage,
}


def translate(payload: Mapping[str, Any], emit: Emit) -> int:
    kind = str(payload.get("kind") or payload.get("type") or "")
    handler = KIND_MAP.get(kind)
    counter = _Counter()
    if handler is None:
        counter(
            new_event(
                event_type="error.gate",
                payload={"unknown_kind": kind, "raw": str(payload)[:1000]},
                **_common(payload),
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
    "KIND_MAP",
    "translate",
    "on_session_start",
    "on_session_end",
    "on_user",
    "on_tool_call",
    "on_tool_result",
    "on_usage",
]
