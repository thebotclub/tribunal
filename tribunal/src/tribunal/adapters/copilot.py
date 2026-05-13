"""GitHub Copilot CLI adapter -- translate Copilot CLI events to v1 events.

GitHub Copilot CLI (``gh copilot``) doesn't expose a hook API yet, so
Tribunal taps it via a thin wrapper script (``gh-copilot-tribunal``)
that forks the ``gh copilot`` binary, captures stdin/stdout, and POSTs
turn-level summaries to the local daemon.

This module just normalises those summaries into v1 unified events. The
shape we expect from the wrapper is::

    {
      "type": "turn.complete",
      "session_id": "...",
      "user_id": "...",
      "command": "gh copilot suggest 'commit my changes'",
      "suggestion": "git add -A && git commit -m '...'",
      "model": "gpt-4o-mini",
      "cost_usd": 0.0021,
      "input_tokens": 120,
      "output_tokens": 45,
      "executed": true,
      "exit_code": 0
    }

Copilot CLI is fundamentally turn-oriented (no streaming, no tool calls
beyond \"run the suggested command\"), so the adapter is intentionally
small: ``session.start`` + ``prompt.submitted`` + ``tool.proposed`` +
optional ``tool.executed`` + ``cost.recorded`` + ``session.end``.
"""

import os
import socket
import uuid
from typing import Any, Callable, Mapping

from tribunal.events.schema import new_event

AGENT_ID = "copilot-cli"

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
        or os.environ.get("GITHUB_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )


def _common(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "agent": AGENT_ID,
        "agent_version": str(payload.get("copilot_version") or "unknown"),
        "session_id": str(payload.get("session_id") or uuid.uuid4()),
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
                "source": "copilot-cli",
                "command": payload.get("command") or "",
                "model": payload.get("model") or "",
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
                "exit_code": int(payload.get("exit_code") or 0),
            },
            **_common(payload),
        )
    )


def on_turn_complete(payload: Mapping[str, Any], emit: Emit) -> None:
    """A complete Copilot CLI turn -- fans out to 3-4 events."""
    common = _common(payload)
    prompt = payload.get("prompt") or payload.get("command") or ""
    suggestion = payload.get("suggestion") or ""
    executed = bool(payload.get("executed"))

    emit(
        new_event(
            event_type="prompt.submitted",
            payload={"prompt": str(prompt), "prompt_length": len(str(prompt))},
            **common,
        )
    )
    if suggestion:
        emit(
            new_event(
                event_type="tool.proposed",
                payload={
                    "tool_name": "Bash",
                    "command": str(suggestion),
                    "tool_input": {"command": str(suggestion)},
                },
                **common,
            )
        )
        if executed:
            emit(
                new_event(
                    event_type="tool.executed",
                    payload={
                        "tool_name": "Bash",
                        "command": str(suggestion),
                        "exit_code": int(payload.get("exit_code") or 0),
                        "tool_response": str(payload.get("tool_response") or ""),
                    },
                    **common,
                )
            )
    if payload.get("cost_usd") is not None:
        emit(
            new_event(
                event_type="cost.recorded",
                payload={
                    "input_tokens": int(payload.get("input_tokens") or 0),
                    "output_tokens": int(payload.get("output_tokens") or 0),
                },
                cost={
                    "usd": float(payload.get("cost_usd") or 0),
                    "model": str(payload.get("model") or ""),
                    "input_tokens": int(payload.get("input_tokens") or 0),
                    "output_tokens": int(payload.get("output_tokens") or 0),
                },
                **common,
            )
        )


# -- Dispatcher --------------------------------------------------------------


TYPE_MAP: dict[str, Callable[[Mapping[str, Any], Emit], None]] = {
    "session.start": on_session_start,
    "session.end": on_session_end,
    "turn.complete": on_turn_complete,
}


def translate(payload: Mapping[str, Any], emit: Emit) -> int:
    type_ = str(payload.get("type") or "")
    handler = TYPE_MAP.get(type_)
    counter = _Counter()
    if handler is None:
        counter(
            new_event(
                event_type="error.gate",
                payload={"unknown_type": type_, "raw": str(payload)[:1000]},
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
    "TYPE_MAP",
    "translate",
    "on_session_start",
    "on_session_end",
    "on_turn_complete",
]
