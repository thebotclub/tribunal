"""Tests for hooks.py — lifecycle event handlers (P7 hook expansion)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tribunal.protocol import HookEvent


def _make_event(hook_name: str, **kwargs) -> HookEvent:
    """Create a HookEvent for testing."""
    defaults = {
        "hook_event_name": hook_name,
        "session_id": "test-session",
        "cwd": kwargs.pop("cwd", "/tmp"),
    }
    defaults.update(kwargs)
    return HookEvent(**defaults)


class TestSessionEnd:
    def test_session_end_allows(self):
        from tribunal.hooks import handle_session_end
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "audit.jsonl").write_text("")
            event = _make_event("SessionEnd", cwd=tmpdir)
            verdict = handle_session_end(event)
            assert verdict.allow is True
            assert "Session ended" in verdict.additional_context

    def test_session_end_logs_event(self):
        from tribunal.hooks import handle_session_end
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "audit.jsonl").write_text("")
            event = _make_event("SessionEnd", cwd=tmpdir, session_id="sess_abc123")
            handle_session_end(event)
            audit = (state_dir / "audit.jsonl").read_text()
            assert "session-end" in audit


class TestPostToolFailure:
    def test_tracks_failure(self):
        from tribunal.hooks import handle_post_tool_failure
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}")
            event = _make_event("PostToolUseFailure", cwd=tmpdir, tool_name="Bash", error="command not found")
            verdict = handle_post_tool_failure(event)
            assert verdict.allow is True
            # Check state was updated
            state = json.loads((state_dir / "state.json").read_text())
            assert state["tool_failures"]["Bash"]["count"] == 1

    def test_warns_on_repeated_failures(self):
        from tribunal.hooks import handle_post_tool_failure
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "tool_failures": {"Bash": {"count": 2, "last_error": "", "last_ts": ""}}
            }))
            event = _make_event("PostToolUseFailure", cwd=tmpdir, tool_name="Bash")
            verdict = handle_post_tool_failure(event)
            assert "failed 3 times" in verdict.additional_context


class TestFileChanged:
    def test_logs_file_change(self):
        from tribunal.hooks import handle_file_changed
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("FileChanged", cwd=tmpdir)
            verdict = handle_file_changed(event)
            assert verdict.allow is True


class TestCwdChanged:
    def test_logs_cwd_change(self):
        from tribunal.hooks import handle_cwd_changed
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("CwdChanged", cwd=tmpdir)
            verdict = handle_cwd_changed(event)
            assert verdict.allow is True
            assert tmpdir in verdict.additional_context


class TestConfigChange:
    def test_warns_on_config_change(self):
        from tribunal.hooks import handle_config_change
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("ConfigChange", cwd=tmpdir)
            verdict = handle_config_change(event)
            assert verdict.allow is True
            assert "modified" in verdict.additional_context


class TestPermissions:
    def test_permission_request_logged(self):
        from tribunal.hooks import handle_permission_request
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("PermissionRequest", cwd=tmpdir, tool_name="Bash")
            verdict = handle_permission_request(event)
            assert verdict.allow is True

    def test_permission_denied_tracked(self):
        from tribunal.hooks import handle_permission_denied
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}")
            event = _make_event("PermissionDenied", cwd=tmpdir, tool_name="Bash")
            verdict = handle_permission_denied(event)
            assert verdict.allow is True
            state = json.loads((state_dir / "state.json").read_text())
            assert len(state["permissions_denied"]) == 1


class TestCompact:
    def test_pre_compact_saves_state(self):
        from tribunal.hooks import handle_pre_compact
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}")
            (state_dir / "audit.jsonl").write_text("")
            event = _make_event("PreCompact", cwd=tmpdir)
            verdict = handle_pre_compact(event)
            assert verdict.allow is True
            state = json.loads((state_dir / "state.json").read_text())
            assert state.get("compaction_count") == 1

    def test_post_compact_reinjects_rules(self):
        from tribunal.hooks import handle_post_compact
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}")
            (state_dir / "audit.jsonl").write_text("")
            event = _make_event("PostCompact", cwd=tmpdir)
            verdict = handle_post_compact(event)
            assert verdict.allow is True
            assert "re-injected" in verdict.additional_context


class TestSubagent:
    def test_subagent_start_tracked(self):
        from tribunal.hooks import handle_subagent_start
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}")
            event = _make_event("SubagentStart", cwd=tmpdir, agent_id="agent_1", agent_type="worker")
            verdict = handle_subagent_start(event)
            assert verdict.allow is True
            state = json.loads((state_dir / "state.json").read_text())
            assert "agent_1" in state["active_agents"]

    def test_subagent_stop_finalized(self):
        from tribunal.hooks import handle_subagent_stop
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "active_agents": {
                    "agent_1": {"started_at": "2026-04-02T10:00:00Z", "cost_usd": 0.5, "tool_calls": 3}
                }
            }))
            event = _make_event("SubagentStop", cwd=tmpdir, agent_id="agent_1")
            verdict = handle_subagent_stop(event)
            assert verdict.allow is True
            state = json.loads((state_dir / "state.json").read_text())
            assert "agent_1" not in state["active_agents"]
            assert len(state["completed_agents"]) == 1


class TestTasks:
    def test_task_created(self):
        from tribunal.hooks import handle_task_created
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("TaskCreated", cwd=tmpdir)
            verdict = handle_task_created(event)
            assert verdict.allow is True

    def test_task_completed(self):
        from tribunal.hooks import handle_task_completed
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("TaskCompleted", cwd=tmpdir)
            verdict = handle_task_completed(event)
            assert verdict.allow is True


class TestHandlerRegistry:
    def test_all_handlers_registered(self):
        from tribunal.hooks import LIFECYCLE_HANDLERS
        expected = [
            "SessionEnd", "PostToolUseFailure", "FileChanged", "CwdChanged",
            "ConfigChange", "PermissionRequest", "PermissionDenied",
            "PreCompact", "PostCompact", "SubagentStart", "SubagentStop",
            "TaskCreated", "TaskCompleted",
        ]
        for name in expected:
            assert name in LIFECYCLE_HANDLERS, f"Missing handler for {name}"

    def test_all_handlers_callable(self):
        from tribunal.hooks import LIFECYCLE_HANDLERS
        for name, handler in LIFECYCLE_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"
