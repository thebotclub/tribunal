"""Tests for tribunal.adapters.cursor — Cursor IDE event translator."""
from __future__ import annotations

from typing import Any

import pytest

from tribunal.adapters import cursor
from tribunal.events.schema import validate_event


def _emit_list() -> tuple[list[dict], Any]:
    events: list[dict] = []
    return events, events.append


def _base(**kw: Any) -> dict:
    p = {
        "type": "chat.open",
        "session_id": "chat-123",
        "cursor_version": "0.40.1",
        "workspace_root": "/repo",
        "user_id": "alice",
    }
    p.update(kw)
    return p


# ── Lifecycle ───────────────────────────────────────────────────────────────


def test_chat_open_emits_session_start() -> None:
    events, emit = _emit_list()
    cursor.on_chat_open(_base(model="gpt-4o"), emit)
    assert len(events) == 1
    ev = events[0]
    validate_event(ev)
    assert ev["agent"] == "cursor"
    assert ev["event_type"] == "session.start"
    assert ev["payload"]["model"] == "gpt-4o"
    assert ev["session_id"] == "chat-123"


def test_chat_close_emits_session_end() -> None:
    events, emit = _emit_list()
    cursor.on_chat_close(_base(type="chat.close", reason="user", turn_count=3), emit)
    assert events[0]["event_type"] == "session.end"
    assert events[0]["payload"]["turns"] == 3


# ── Prompts and tools ───────────────────────────────────────────────────────


def test_user_message_emits_prompt_submitted() -> None:
    events, emit = _emit_list()
    cursor.on_user_message(_base(type="user.message", text="hello"), emit)
    assert events[0]["event_type"] == "prompt.submitted"
    assert events[0]["payload"]["prompt"] == "hello"
    assert events[0]["payload"]["prompt_length"] == 5


def test_tool_call_shell_extracts_command() -> None:
    events, emit = _emit_list()
    cursor.on_tool_call(_base(type="tool.call", tool="shell", args={"command": "ls"}), emit)
    ev = events[0]
    assert ev["event_type"] == "tool.proposed"
    assert ev["payload"]["tool_name"] == "shell"
    assert ev["payload"]["command"] == "ls"


def test_tool_call_mcp_extracts_server() -> None:
    events, emit = _emit_list()
    cursor.on_tool_call(_base(type="tool.call", tool="mcp.github.create_pr", args={}), emit)
    assert events[0]["payload"]["mcp_server"] == "github"


def test_tool_result_success_writes_file_event() -> None:
    events, emit = _emit_list()
    cursor.on_tool_result(
        _base(
            type="tool.result",
            tool="write_file",
            ok=True,
            args={"path": "/repo/a.py", "content": "abc"},
            result={"ok": True},
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert types == ["tool.executed", "file.write"]
    assert events[1]["payload"]["bytes"] == 3


def test_tool_result_failure_only_emits_failed() -> None:
    events, emit = _emit_list()
    cursor.on_tool_result(
        _base(type="tool.result", tool="write_file", ok=False, error="EACCES",
              args={"path": "/x"}),
        emit,
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "tool.failed"
    assert events[0]["payload"]["error"] == "EACCES"


def test_tool_result_shell_emits_bash_executed() -> None:
    events, emit = _emit_list()
    cursor.on_tool_result(
        _base(
            type="tool.result",
            tool="shell",
            ok=True,
            args={"command": "echo hi"},
            result={"exit_code": 0, "stdout": "hi\n"},
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert types == ["tool.executed", "bash.executed"]
    assert events[1]["payload"]["exit_code"] == 0


# ── File save / cost ────────────────────────────────────────────────────────


def test_file_save_emits_file_write() -> None:
    events, emit = _emit_list()
    cursor.on_file_save(_base(type="file.save", path="/repo/x.py", size=200), emit)
    assert events[0]["event_type"] == "file.write"
    assert events[0]["payload"]["bytes"] == 200


def test_file_save_missing_path_is_noop() -> None:
    events, emit = _emit_list()
    cursor.on_file_save(_base(type="file.save"), emit)
    assert events == []


def test_cost_event() -> None:
    events, emit = _emit_list()
    cursor.on_cost(
        _base(
            type="cost.recorded",
            cost={"usd": 0.05, "model": "gpt-4o", "input_tokens": 100, "output_tokens": 30},
        ),
        emit,
    )
    ev = events[0]
    validate_event(ev)
    assert ev["cost"]["usd"] == 0.05
    assert ev["cost"]["model"] == "gpt-4o"


# ── Dispatcher ──────────────────────────────────────────────────────────────


def test_translate_dispatches_known_type() -> None:
    events, emit = _emit_list()
    n = cursor.translate(_base(type="user.message", text="hi"), emit)
    assert n == 1
    assert events[0]["event_type"] == "prompt.submitted"


def test_translate_unknown_type_emits_error_gate() -> None:
    events, emit = _emit_list()
    cursor.translate(_base(type="mystery.event"), emit)
    assert events[0]["event_type"] == "error.gate"
    assert events[0]["payload"]["unknown_type"] == "mystery.event"


def test_all_known_types_produce_valid_events() -> None:
    for type_ in cursor.TYPE_MAP:
        events, emit = _emit_list()
        payload = _base(type=type_)
        if type_ == "tool.call":
            payload.update(tool="shell", args={"command": "ls"})
        if type_ == "tool.result":
            payload.update(tool="shell", ok=True, args={"command": "ls"}, result={"exit_code": 0})
        if type_ == "file.save":
            payload["path"] = "/repo/x.py"
        if type_ == "cost.recorded":
            payload["cost"] = {"usd": 0.1, "model": "x"}
        n = cursor.translate(payload, emit)
        assert n >= 1
        for ev in events:
            validate_event(ev)
