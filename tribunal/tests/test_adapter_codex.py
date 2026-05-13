"""Tests for tribunal.adapters.codex — OpenAI Codex CLI translator."""

from __future__ import annotations

from typing import Any

from tribunal.adapters import codex
from tribunal.events.schema import validate_event


def _events() -> tuple[list[dict], Any]:
    events: list[dict] = []
    return events, events.append


def _base(**kw: Any) -> dict:
    p = {
        "session_id": "codex-1",
        "user_id": "alice",
        "codex_version": "0.1.0",
        "cwd": "/repo",
    }
    p.update(kw)
    return p


def test_session_start_emits_session_event() -> None:
    events, emit = _events()
    codex.on_session_start(
        _base(kind="session_start", model="o4-mini", mode="agent"), emit
    )
    assert events[0]["agent"] == "codex-cli"
    assert events[0]["event_type"] == "session.start"
    assert events[0]["payload"]["mode"] == "agent"
    validate_event(events[0])


def test_session_end_emits_session_event() -> None:
    events, emit = _events()
    codex.on_session_end(_base(kind="session_end", reason="user", turn_count=4), emit)
    assert events[0]["event_type"] == "session.end"
    assert events[0]["payload"]["turn_count"] == 4


def test_user_message_emits_prompt_submitted() -> None:
    events, emit = _events()
    codex.on_user(_base(kind="user", text="refactor this"), emit)
    assert events[0]["event_type"] == "prompt.submitted"
    assert events[0]["payload"]["prompt"] == "refactor this"
    assert events[0]["payload"]["prompt_length"] == len("refactor this")


def test_tool_call_shell_maps_command() -> None:
    events, emit = _events()
    codex.on_tool_call(
        _base(kind="tool_call", name="shell", input={"command": "ls -la"}), emit
    )
    ev = events[0]
    assert ev["event_type"] == "tool.proposed"
    assert ev["payload"]["tool_name"] == "shell"
    assert ev["payload"]["command"] == "ls -la"


def test_tool_call_python_maps_code_as_command() -> None:
    events, emit = _events()
    codex.on_tool_call(
        _base(kind="tool_call", name="python", input={"code": "print(1)"}), emit
    )
    assert events[0]["payload"]["command"] == "print(1)"


def test_tool_call_write_file_maps_path() -> None:
    events, emit = _events()
    codex.on_tool_call(
        _base(kind="tool_call", name="write_file", input={"path": "/repo/x.py"}), emit
    )
    assert events[0]["payload"]["path"] == "/repo/x.py"


def test_tool_result_success_maps_to_executed() -> None:
    events, emit = _events()
    codex.on_tool_result(
        _base(kind="tool_result", name="shell", exit_code=0, output="ok"), emit
    )
    assert events[0]["event_type"] == "tool.executed"


def test_tool_result_failure_maps_to_failed() -> None:
    events, emit = _events()
    codex.on_tool_result(
        _base(kind="tool_result", name="shell", exit_code=1, output="boom"), emit
    )
    assert events[0]["event_type"] == "tool.failed"
    assert events[0]["payload"]["exit_code"] == 1


def test_usage_event_records_cost() -> None:
    events, emit = _events()
    codex.on_usage(
        _base(
            kind="usage",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0125,
            model="o4-mini",
        ),
        emit,
    )
    ev = events[0]
    assert ev["event_type"] == "cost.recorded"
    assert ev["cost"]["usd"] == 0.0125
    assert ev["cost"]["model"] == "o4-mini"


def test_translate_unknown_kind_emits_error_gate() -> None:
    events, emit = _events()
    n = codex.translate(_base(kind="undefined"), emit)
    assert n == 1
    assert events[0]["event_type"] == "error.gate"


def test_translate_dispatches_by_kind() -> None:
    events, emit = _events()
    codex.translate(_base(kind="user", text="hi"), emit)
    assert events[0]["event_type"] == "prompt.submitted"
