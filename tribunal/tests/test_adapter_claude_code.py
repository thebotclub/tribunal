"""Tests for tribunal.adapters.claude_code — Claude Code hook translator."""
from __future__ import annotations

from typing import Any

import pytest

from tribunal.adapters import claude_code as cc
from tribunal.events.schema import validate_event, SchemaError


def _emit_list() -> tuple[list[dict], Any]:
    events: list[dict] = []
    return events, events.append


def _base_payload(**kw: Any) -> dict:
    p = {
        "hook_event_name": "SessionStart",
        "session_id": "sess-abc",
        "claude_code_version": "0.2.10",
        "cwd": "/repo",
        "source": "user",
    }
    p.update(kw)
    return p


# ── session lifecycle ───────────────────────────────────────────────────────


def test_session_start_produces_one_validated_event() -> None:
    events, emit = _emit_list()
    cc.on_session_start(_base_payload(), emit)
    assert len(events) == 1
    ev = events[0]
    validate_event(ev)
    assert ev["agent"] == "claude-code"
    assert ev["event_type"] == "session.start"
    assert ev["session_id"] == "sess-abc"
    assert ev["repo_path"] == "/repo"


def test_session_stop_includes_reason() -> None:
    events, emit = _emit_list()
    cc.on_session_stop(_base_payload(hook_event_name="Stop", stop_reason="user", turn_count=4), emit)
    assert events[0]["event_type"] == "session.end"
    assert events[0]["payload"]["reason"] == "user"
    assert events[0]["payload"]["turns"] == 4


# ── prompts & tools ─────────────────────────────────────────────────────────


def test_user_prompt_captures_text_and_length() -> None:
    events, emit = _emit_list()
    cc.on_user_prompt(_base_payload(prompt="write a function"), emit)
    ev = events[0]
    assert ev["event_type"] == "prompt.submitted"
    assert ev["payload"]["prompt"] == "write a function"
    assert ev["payload"]["prompt_length"] == len("write a function")


def test_pre_tool_use_bash_extracts_command() -> None:
    events, emit = _emit_list()
    cc.on_pre_tool_use(
        _base_payload(tool_name="Bash", tool_input={"command": "ls /etc"}),
        emit,
    )
    ev = events[0]
    assert ev["event_type"] == "tool.proposed"
    assert ev["payload"]["tool_name"] == "Bash"
    assert ev["payload"]["command"] == "ls /etc"


def test_pre_tool_use_mcp_extracts_server() -> None:
    events, emit = _emit_list()
    cc.on_pre_tool_use(
        _base_payload(tool_name="mcp__github__create_pr", tool_input={"title": "x"}),
        emit,
    )
    assert events[0]["payload"]["mcp_server"] == "github"


def test_post_tool_use_success_emits_executed_plus_file_write() -> None:
    events, emit = _emit_list()
    cc.on_post_tool_use(
        _base_payload(
            tool_name="Write",
            tool_input={"file_path": "/repo/x.py", "content": "abc"},
            tool_response={"ok": True},
            success=True,
        ),
        emit,
    )
    assert [e["event_type"] for e in events] == ["tool.executed", "file.write"]
    assert events[1]["payload"]["path"] == "/repo/x.py"
    assert events[1]["payload"]["bytes"] == 3


def test_post_tool_use_failure_emits_failed_only() -> None:
    events, emit = _emit_list()
    cc.on_post_tool_use(
        _base_payload(
            tool_name="Write",
            tool_input={"file_path": "/repo/x.py", "content": "abc"},
            success=False,
            error="permission denied",
        ),
        emit,
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "tool.failed"
    assert events[0]["payload"]["error"] == "permission denied"


def test_post_tool_use_bash_emits_bash_executed_with_truncation() -> None:
    events, emit = _emit_list()
    big = "X" * 1000
    cc.on_post_tool_use(
        _base_payload(
            tool_name="Bash",
            tool_input={"command": "echo X"},
            tool_response={"exit_code": 0, "stdout": big},
            success=True,
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert types == ["tool.executed", "bash.executed"]
    assert len(events[1]["payload"]["stdout_truncated"]) == 500


def test_read_tool_emits_file_read() -> None:
    events, emit = _emit_list()
    cc.on_post_tool_use(
        _base_payload(
            tool_name="Read",
            tool_input={"file_path": "/repo/a.py"},
            success=True,
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert types == ["tool.executed", "file.read"]


# ── subagents, cost, mcp ────────────────────────────────────────────────────


def test_subagent_start_and_stop() -> None:
    events, emit = _emit_list()
    cc.on_subagent_start(
        _base_payload(subagent_id="sub-1", subagent_type="searcher"), emit
    )
    cc.on_subagent_stop(_base_payload(subagent_id="sub-1", reason="done"), emit)
    assert [e["event_type"] for e in events] == ["subagent.start", "subagent.stop"]


def test_cost_recorded_populates_cost_object() -> None:
    events, emit = _emit_list()
    cc.on_cost_recorded(
        _base_payload(
            cost={"usd": 0.21, "model": "claude-3.5-sonnet", "input_tokens": 100, "output_tokens": 50},
        ),
        emit,
    )
    ev = events[0]
    validate_event(ev)
    assert ev["cost"]["usd"] == 0.21
    assert ev["cost"]["input_tokens"] == 100


def test_mcp_call_emits_before() -> None:
    events, emit = _emit_list()
    cc.on_mcp_call(
        _base_payload(mcp_server="filesystem", mcp_method="read", mcp_args={"path": "/x"}),
        emit,
    )
    assert events[0]["event_type"] == "mcp.call.before"
    assert events[0]["payload"]["server"] == "filesystem"


# ── Dispatcher ──────────────────────────────────────────────────────────────


def test_translate_known_hook_returns_count() -> None:
    events, emit = _emit_list()
    n = cc.translate(_base_payload(hook_event_name="UserPromptSubmit", prompt="hi"), emit)
    assert n == 1
    assert events[0]["event_type"] == "prompt.submitted"


def test_translate_unknown_hook_emits_error_gate() -> None:
    events, emit = _emit_list()
    n = cc.translate(_base_payload(hook_event_name="MysteryEvent"), emit)
    assert n == 1
    assert events[0]["event_type"] == "error.gate"
    assert events[0]["payload"]["unknown_hook"] == "MysteryEvent"


def test_translate_all_known_hooks_produce_valid_events() -> None:
    """Sanity check: every HOOK_MAP entry passes validate_event."""
    for hook_name in cc.HOOK_MAP:
        events, emit = _emit_list()
        payload = _base_payload(hook_event_name=hook_name)
        if hook_name in ("PreToolUse", "PostToolUse"):
            payload.update(tool_name="Bash", tool_input={"command": "ls"})
        if hook_name == "CostRecorded":
            payload["cost"] = {"usd": 0.1, "model": "x", "input_tokens": 1, "output_tokens": 1}
        n = cc.translate(payload, emit)
        assert n >= 1
        for ev in events:
            validate_event(ev)
