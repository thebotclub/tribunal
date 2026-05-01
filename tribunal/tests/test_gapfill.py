"""Tests for gap-fill features — P5-P8 completion items."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from tribunal.protocol import HookEvent


def _make_event(hook_name: str, cwd: str, **kwargs) -> HookEvent:
    defaults = {
        "hook_event_name": hook_name,
        "session_id": "sess_gapfill",
        "cwd": cwd,
    }
    defaults.update(kwargs)
    return HookEvent(**defaults)


# ── require_tool rule field ──────────────────────────────────────────────────


class TestRequireTool:
    def test_rule_has_require_tool_field(self):
        from tribunal.rules import Rule

        r = Rule(name="test", trigger="PreToolUse")
        assert r.require_tool is False

    def test_rule_from_config_parses_require_tool(self):
        from tribunal.rules import RuleEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = Path(tmpdir) / "rules.yaml"
            rules_path.write_text(
                yaml.dump(
                    {
                        "rules": {
                            "lint": {
                                "trigger": "PreToolUse",
                                "match": {"tool": "FileEdit"},
                                "action": "block",
                                "condition": "lint-check",
                                "require_tool": True,
                            }
                        }
                    }
                )
            )
            engine = RuleEngine.from_config(str(rules_path))
            assert len(engine.rules) == 1
            assert engine.rules[0].require_tool is True


# ── Permission escalation detection ──────────────────────────────────────────


class TestPermissionEscalation:
    def test_permission_request_tracks_grants(self):
        from tribunal.hooks import handle_permission_request

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            event = _make_event("PermissionRequest", cwd=tmpdir, tool_name="Bash")
            verdict = handle_permission_request(event)
            assert verdict.allow is True
            state = json.loads((trib / "state.json").read_text())
            assert len(state.get("permissions_granted", [])) == 1
            assert state["permissions_granted"][0]["tool"] == "Bash"

    def test_permission_denied_tracks_denials(self):
        from tribunal.hooks import handle_permission_denied

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            event = _make_event("PermissionDenied", cwd=tmpdir, tool_name="Bash")
            verdict = handle_permission_denied(event)
            assert verdict.allow is True
            state = json.loads((trib / "state.json").read_text())
            assert len(state.get("permissions_denied", [])) == 1

    def test_escalation_detected_grant_then_deny(self):
        from tribunal.hooks import handle_permission_denied, handle_permission_request

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            # First: grant
            grant_event = _make_event("PermissionRequest", cwd=tmpdir, tool_name="Bash")
            handle_permission_request(grant_event)
            # Then: deny same tool → escalation detected
            deny_event = _make_event("PermissionDenied", cwd=tmpdir, tool_name="Bash")
            handle_permission_denied(deny_event)
            state = json.loads((trib / "state.json").read_text())
            assert len(state.get("permission_escalations", [])) >= 1
            assert state["permission_escalations"][0]["type"] == "grant-then-deny"


# ── Compaction analytics ─────────────────────────────────────────────────────


class TestCompactionAnalytics:
    def test_pre_compact_tracks_frequency(self):
        from tribunal.hooks import handle_pre_compact

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            event = _make_event("PreCompact", cwd=tmpdir)
            handle_pre_compact(event)
            state = json.loads((trib / "state.json").read_text())
            assert state.get("compaction_count") == 1
            assert len(state.get("compaction_events", [])) >= 1
            assert state["compaction_events"][0]["type"] == "pre"

    def test_post_compact_logs_completion(self):
        from tribunal.hooks import handle_post_compact

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            event = _make_event("PostCompact", cwd=tmpdir)
            verdict = handle_post_compact(event)
            assert verdict.allow is True
            assert "re-injected" in verdict.additional_context
            state = json.loads((trib / "state.json").read_text())
            assert len(state.get("compaction_events", [])) >= 1
            assert state["compaction_events"][0]["type"] == "post"

    def test_multiple_compactions_accumulate(self):
        from tribunal.hooks import handle_pre_compact

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "state.json").write_text("{}")
            (trib / "audit.jsonl").write_text("")
            for _ in range(3):
                handle_pre_compact(_make_event("PreCompact", cwd=tmpdir))
            state = json.loads((trib / "state.json").read_text())
            assert state["compaction_count"] == 3


# ── Per-agent audit trails ───────────────────────────────────────────────────


@pytest.mark.skip(reason="tribunal.agents archived in 2.0 pivot")
class TestPerAgentAuditTrails:
    def test_log_agent_event(self):
        from tribunal.agents import log_agent_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_agent_event(tmpdir, "agent-001", "tool_call", {"tool": "FileEdit"})
            trail_path = Path(tmpdir) / ".tribunal" / "agents" / "agent-001.jsonl"
            assert trail_path.is_file()
            entries = [
                json.loads(line) for line in trail_path.read_text().strip().split("\n")
            ]
            assert len(entries) == 1
            assert entries[0]["agent_id"] == "agent-001"
            assert entries[0]["event"] == "tool_call"

    def test_get_agent_trail(self):
        from tribunal.agents import get_agent_trail, log_agent_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_agent_event(tmpdir, "agent-002", "start")
            log_agent_event(tmpdir, "agent-002", "tool_call")
            log_agent_event(tmpdir, "agent-002", "stop")
            trail = get_agent_trail(tmpdir, "agent-002")
            assert len(trail) == 3

    def test_separate_trails_per_agent(self):
        from tribunal.agents import get_agent_trail, log_agent_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_agent_event(tmpdir, "agent-a", "start")
            log_agent_event(tmpdir, "agent-b", "start")
            assert len(get_agent_trail(tmpdir, "agent-a")) == 1
            assert len(get_agent_trail(tmpdir, "agent-b")) == 1

    def test_missing_trail_returns_empty(self):
        from tribunal.agents import get_agent_trail

        with tempfile.TemporaryDirectory() as tmpdir:
            assert get_agent_trail(tmpdir, "nonexistent") == []


# ── Task-description permission matching ─────────────────────────────────────


@pytest.mark.skip(reason="tribunal.agents archived in 2.0 pivot")
class TestAgentPermissions:
    def _write_policy(self, tmpdir, agent_perms):
        config_dir = Path(tmpdir) / ".tribunal"
        config_dir.mkdir(exist_ok=True)
        config_dir.joinpath("config.yaml").write_text(
            yaml.dump(
                {
                    "multi_agent": {
                        "agent_permissions": agent_perms,
                    }
                }
            )
        )

    def test_blocked_tool_denied(self):
        from tribunal.agents import check_agent_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_policy(
                tmpdir,
                {
                    "default": {"blocked_tools": ["Bash", "rm"]},
                },
            )
            (Path(tmpdir) / ".tribunal" / "state.json").write_text("{}")
            event = _make_event("PreToolUse", cwd=tmpdir, tool_name="Bash")
            allowed, reason = check_agent_policy(event)
            assert allowed is False
            assert "blocked" in reason.lower()

    def test_allowed_tool_passes(self):
        from tribunal.agents import check_agent_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_policy(
                tmpdir,
                {
                    "default": {"allowed_tools": ["FileEdit", "FileWrite"]},
                },
            )
            (Path(tmpdir) / ".tribunal" / "state.json").write_text("{}")
            event = _make_event("PreToolUse", cwd=tmpdir, tool_name="FileEdit")
            allowed, reason = check_agent_policy(event)
            assert allowed is True

    def test_unlisted_tool_blocked_when_allowlist_defined(self):
        from tribunal.agents import check_agent_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_policy(
                tmpdir,
                {
                    "default": {"allowed_tools": ["FileEdit"]},
                },
            )
            (Path(tmpdir) / ".tribunal" / "state.json").write_text("{}")
            event = _make_event("PreToolUse", cwd=tmpdir, tool_name="Bash")
            allowed, reason = check_agent_policy(event)
            assert allowed is False
            assert "not allowed" in reason.lower()

    def test_agent_type_specific_permissions(self):
        from tribunal.agents import check_agent_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_policy(
                tmpdir,
                {
                    "reviewer": {"allowed_tools": ["FileRead"]},
                    "default": {"allowed_tools": ["FileEdit", "Bash"]},
                },
            )
            (Path(tmpdir) / ".tribunal" / "state.json").write_text("{}")
            event = _make_event(
                "PreToolUse", cwd=tmpdir, tool_name="FileEdit", agent_type="reviewer"
            )
            allowed, reason = check_agent_policy(event)
            assert allowed is False  # reviewer can only FileRead

    def test_no_permissions_allows_all(self):
        from tribunal.agents import check_agent_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_policy(tmpdir, {})
            (Path(tmpdir) / ".tribunal" / "state.json").write_text("{}")
            event = _make_event("PreToolUse", cwd=tmpdir, tool_name="Bash")
            allowed, reason = check_agent_policy(event)
            assert allowed is True


# ── Memory stats ─────────────────────────────────────────────────────────────


@pytest.mark.skip(reason="tribunal.memory archived in 2.0 pivot")
class TestMemoryStats:
    def test_memory_stats_empty(self):
        from tribunal.memory import memory_stats

        with tempfile.TemporaryDirectory() as tmpdir:
            stats = memory_stats(tmpdir)
            assert stats["total_memory_files"] == 0
            assert stats["tribunal_files"] == 0
            assert stats["capacity_pct"] == 0

    def test_memory_stats_with_entries(self):
        from tribunal.memory import inject_memory, memory_stats, MemoryEntry

        with tempfile.TemporaryDirectory() as tmpdir:
            inject_memory(tmpdir, MemoryEntry(title="Test", content="hello"))
            stats = memory_stats(tmpdir)
            assert stats["total_memory_files"] == 1
            assert stats["tribunal_files"] == 1
            assert stats["tribunal_bytes"] > 0
            assert stats["max_files"] == 200

    def test_format_memory_stats(self):
        from tribunal.memory import format_memory_stats

        with tempfile.TemporaryDirectory() as tmpdir:
            output = format_memory_stats(tmpdir)
            assert "Memory Stats" in output
            assert "Capacity:" in output


# ── Config TypedDict ─────────────────────────────────────────────────────────


class TestConfigTypedDict:
    def test_typeddict_importable(self):
        from tribunal.config import (
            BudgetConfig,
        )

        # TypedDict types are importable and usable
        budget: BudgetConfig = {"session_usd": 1.0}
        assert budget["session_usd"] == 1.0

    def test_validate_config_uses_schema(self):
        from tribunal.config import validate_config

        # Valid config
        assert validate_config({"budget": {"session_usd": 1.0}}) == []
        # Invalid key
        errors = validate_config({"unknown_key": True})
        assert any("Unknown" in e for e in errors)


# ── CLI doctor command ───────────────────────────────────────────────────────


class TestDoctorCommand:
    def test_doctor_no_setup(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_doctor
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("os.getcwd", return_value=tmpdir),
                patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)),
            ):
                result = cmd_doctor(argparse.Namespace())
            assert result == 1  # issues found
            captured = capsys.readouterr()
            assert (
                "missing" in captured.out.lower() or "not found" in captured.out.lower()
            )

    def test_doctor_valid_setup(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_doctor
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up minimal valid project
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "rules.yaml").write_text(
                yaml.dump(
                    {"rules": {"test": {"trigger": "PreToolUse", "action": "block"}}}
                )
            )
            claude = Path(tmpdir) / ".claude"
            claude.mkdir()
            (claude / "claudeconfig.json").write_text(
                json.dumps(
                    {"hooks": {"PreToolUse": [{"run": [{"command": "tribunal-gate"}]}]}}
                )
            )
            with (
                patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)),
                patch("shutil.which", return_value="/usr/local/bin/tribunal-gate"),
            ):
                result = cmd_doctor(argparse.Namespace())
            captured = capsys.readouterr()
            assert result == 0
            assert "tribunal-gate is on PATH" in captured.out


# ── CLI audit rotate ─────────────────────────────────────────────────────────


class TestAuditRotateCLI:
    def test_audit_rotate_no_log(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_audit
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)):
                cmd_audit(argparse.Namespace(audit_command="rotate", count=20))
            captured = capsys.readouterr()
            assert "No audit log" in captured.out

    def test_audit_rotate_small_log(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_audit
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "audit.jsonl").write_text('{"ts":"2025-01-01"}\n')
            with patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)):
                result = cmd_audit(argparse.Namespace(audit_command="rotate", count=20))
            assert result == 0
            captured = capsys.readouterr()
            assert "below rotation threshold" in captured.out


# ── CLI config validate ──────────────────────────────────────────────────────


class TestConfigValidateCLI:
    def test_config_validate_no_file(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_config
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)):
                result = cmd_config(argparse.Namespace(config_command="validate"))
            assert result == 0
            captured = capsys.readouterr()
            assert "No .tribunal/config.yaml" in captured.out

    def test_config_validate_valid(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_config
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "config.yaml").write_text(
                yaml.dump({"budget": {"session_usd": 2.0}})
            )
            with patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)):
                result = cmd_config(argparse.Namespace(config_command="validate"))
            assert result == 0
            captured = capsys.readouterr()
            assert "valid" in captured.out.lower()

    def test_config_validate_invalid(self, capsys):
        from unittest.mock import patch
        from tribunal.cli import cmd_config
        import argparse

        with tempfile.TemporaryDirectory() as tmpdir:
            trib = Path(tmpdir) / ".tribunal"
            trib.mkdir()
            (trib / "config.yaml").write_text(yaml.dump({"bogus_key": True}))
            with patch("tribunal.cli.Path.cwd", return_value=Path(tmpdir)):
                result = cmd_config(argparse.Namespace(config_command="validate"))
            assert result == 1
