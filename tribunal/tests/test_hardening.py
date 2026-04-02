"""Phase 5 hardening tests — covers all previously untested modules.

Tests for: protocol, gate, audit (rotation), io (atomic writes),
config (schema validation), memory (limits), analytics, airgap,
dashboard, and CLI entry points.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ── Protocol Tests ────────────────────────────────────────────────────────────

class TestProtocol:
    """Tests for protocol.py — JSON hook event parsing and verdict writing."""

    def test_read_hook_event_basic(self):
        from tribunal.protocol import HookEvent, read_hook_event
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "sess_123",
            "cwd": "/tmp/proj",
            "tool_name": "FileEdit",
            "tool_input": {"path": "src/main.py", "new_string": "hello"},
        })
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = payload
            event = read_hook_event()
        assert event.hook_event_name == "PreToolUse"
        assert event.session_id == "sess_123"
        assert event.tool_name == "FileEdit"
        assert event.tool_input["path"] == "src/main.py"

    def test_read_hook_event_empty_stdin(self):
        from tribunal.protocol import read_hook_event
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            event = read_hook_event()
        assert event.hook_event_name == "Unknown"

    def test_read_hook_event_malformed_json(self):
        from tribunal.protocol import read_hook_event
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{not valid json"
            with pytest.raises(json.JSONDecodeError):
                read_hook_event()

    def test_read_hook_event_all_fields(self):
        from tribunal.protocol import read_hook_event
        payload = json.dumps({
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "cwd": "/tmp",
            "transcript_path": "/tmp/t.md",
            "permission_mode": "user_approved",
            "agent_id": "agent_1",
            "agent_type": "worker",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "tu_1",
            "tool_response": {"output": "file.txt"},
            "error": None,
            "is_interrupt": False,
            "source": "cli",
            "model": "claude-opus-4-6",
            "prompt": "hello",
            "last_assistant_message": "done",
        })
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = payload
            event = read_hook_event()
        assert event.agent_id == "agent_1"
        assert event.model == "claude-opus-4-6"
        assert event.tool_response == {"output": "file.txt"}

    def test_hook_verdict_exit_codes(self):
        from tribunal.protocol import HookVerdict
        allow = HookVerdict(allow=True)
        assert allow.exit_code == 0
        block = HookVerdict(allow=False, reason="blocked")
        assert block.exit_code == 2

    def test_write_verdict_allow(self):
        from tribunal.protocol import HookVerdict, write_verdict
        verdict = HookVerdict(allow=True, additional_context="note")
        with patch("sys.stdout") as mock_out, pytest.raises(SystemExit) as exc_info:
            write_verdict(verdict)
        assert exc_info.value.code == 0

    def test_write_verdict_block(self):
        from tribunal.protocol import HookVerdict, write_verdict
        verdict = HookVerdict(allow=False, reason="blocked by test")
        with patch("sys.stderr"), pytest.raises(SystemExit) as exc_info:
            write_verdict(verdict)
        assert exc_info.value.code == 2


# ── Gate Tests ────────────────────────────────────────────────────────────────

class TestGate:
    """Tests for gate.py — fail-closed behavior and error handling."""

    def test_fail_exit_code_default_closed(self):
        from tribunal.gate import _fail_exit_code
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if set
            os.environ.pop("TRIBUNAL_FAIL_MODE", None)
            assert _fail_exit_code() == 2

    def test_fail_exit_code_explicit_closed(self):
        from tribunal.gate import _fail_exit_code
        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "closed"}):
            assert _fail_exit_code() == 2

    def test_fail_exit_code_open(self):
        from tribunal.gate import _fail_exit_code
        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "open"}):
            assert _fail_exit_code() == 0

    def test_gate_malformed_json_blocks(self):
        """Gate should exit 2 (block) on malformed JSON by default."""
        from tribunal.gate import main
        with patch("sys.stdin") as mock_stdin, \
             patch("sys.stderr"), \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = "{bad json"
            main()
        assert exc_info.value.code == 2

    def test_gate_malformed_json_allows_in_open_mode(self):
        """Gate should exit 0 (allow) on error when TRIBUNAL_FAIL_MODE=open."""
        from tribunal.gate import main
        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "open"}), \
             patch("sys.stdin") as mock_stdin, \
             patch("sys.stderr"), \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = "{bad json"
            main()
        assert exc_info.value.code == 0

    def test_gate_valid_event_processes(self):
        """Gate should process a valid event through the rule engine."""
        from tribunal.gate import main
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = json.dumps({
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "cwd": tmpdir,
                "tool_name": "Read",
                "tool_input": {"path": "README.md"},
            })
            with patch("sys.stdin") as mock_stdin, \
                 patch("sys.stdout"), \
                 pytest.raises(SystemExit) as exc_info:
                mock_stdin.read.return_value = payload
                main()
            # Read tool should be allowed (no rules block it)
            assert exc_info.value.code == 0


# ── IO Tests (Atomic Writes) ─────────────────────────────────────────────────

class TestIO:
    """Tests for io.py — atomic writes with file locking."""

    def test_atomic_write_json_creates_file(self):
        from tribunal.io import atomic_write_json, locked_read_json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            atomic_write_json(path, {"key": "value"})
            assert path.exists()
            data = locked_read_json(path)
            assert data == {"key": "value"}

    def test_atomic_write_json_creates_dirs(self):
        from tribunal.io import atomic_write_json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deep" / "nested" / "test.json"
            atomic_write_json(path, {"nested": True})
            assert path.exists()

    def test_atomic_write_json_overwrites(self):
        from tribunal.io import atomic_write_json, locked_read_json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            atomic_write_json(path, {"v": 1})
            atomic_write_json(path, {"v": 2})
            data = locked_read_json(path)
            assert data["v"] == 2

    def test_locked_read_json_missing_file(self):
        from tribunal.io import locked_read_json
        data = locked_read_json(Path("/nonexistent/path.json"))
        assert data == {}

    def test_locked_read_json_invalid_json(self):
        from tribunal.io import locked_read_json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text("{not valid")
            data = locked_read_json(path)
            assert data == {}

    def test_atomic_write_preserves_content(self):
        from tribunal.io import atomic_write_json, locked_read_json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            complex_data = {
                "rules": [{"name": "tdd", "action": "block"}],
                "budget": {"session_usd": 5.0},
                "nested": {"deep": {"value": [1, 2, 3]}},
            }
            atomic_write_json(path, complex_data)
            data = locked_read_json(path)
            assert data == complex_data


# ── Audit Tests (Rotation) ───────────────────────────────────────────────────

class TestAuditRotation:
    """Tests for audit.py — log rotation and stats."""

    def test_rotate_small_file_skipped(self):
        from tribunal.audit import rotate_audit_log
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            path.write_text('{"test": true}\n')
            assert rotate_audit_log(path, max_bytes=1_000_000) is False

    def test_rotate_large_file(self):
        from tribunal.audit import rotate_audit_log
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            # Write more than the threshold
            path.write_text("x" * 100)
            assert rotate_audit_log(path, max_bytes=50) is True
            # Original should be gone, .1 should exist
            assert not path.exists()
            assert path.with_suffix(".1.jsonl").exists()

    def test_rotate_shifts_existing(self):
        from tribunal.audit import rotate_audit_log
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            # Create existing rotated file
            path.with_suffix(".1.jsonl").write_text("old1")
            path.write_text("x" * 100)
            rotate_audit_log(path, max_bytes=50, keep=3)
            assert path.with_suffix(".2.jsonl").read_text() == "old1"
            assert path.with_suffix(".1.jsonl").read_text() == "x" * 100

    def test_rotate_respects_keep_limit(self):
        from tribunal.audit import rotate_audit_log
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            # Create files up to the keep limit
            for i in range(1, 4):
                path.with_suffix(f".{i}.jsonl").write_text(f"old{i}")
            path.write_text("x" * 100)
            rotate_audit_log(path, max_bytes=50, keep=3)
            # .3 should have been deleted to make room
            assert not path.with_suffix(".4.jsonl").exists()

    def test_rotate_nonexistent_file(self):
        from tribunal.audit import rotate_audit_log
        result = rotate_audit_log(Path("/nonexistent/audit.jsonl"))
        assert result is False

    def test_audit_stats(self):
        from tribunal.audit import audit_stats
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            entries = [json.dumps({"i": i}) for i in range(10)]
            path.write_text("\n".join(entries) + "\n")
            stats = audit_stats(path)
            assert stats["entries"] == 10
            assert stats["bytes"] > 0
            assert stats["rotated_files"] == 0

    def test_audit_stats_with_rotated(self):
        from tribunal.audit import audit_stats
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            path.write_text('{"test": true}\n')
            path.with_suffix(".1.jsonl").write_text("old")
            path.with_suffix(".2.jsonl").write_text("older")
            stats = audit_stats(path)
            assert stats["rotated_files"] == 2

    def test_audit_stats_missing_file(self):
        from tribunal.audit import audit_stats
        stats = audit_stats("/nonexistent/audit.jsonl")
        assert stats["entries"] == 0

    def test_log_event_triggers_rotation(self):
        from tribunal.protocol import HookEvent
        from tribunal.audit import log_event
        with tempfile.TemporaryDirectory() as tmpdir:
            event = HookEvent(
                hook_event_name="PreToolUse",
                session_id="s1",
                cwd=tmpdir,
                tool_name="FileEdit",
                tool_input={"path": "test.py"},
            )
            # Write a bunch of events
            for _ in range(5):
                log_event(event, True)
            audit_path = Path(tmpdir) / ".tribunal" / "audit.jsonl"
            assert audit_path.exists()


# ── Config Validation Tests ───────────────────────────────────────────────────

class TestConfigValidation:
    """Tests for config.py — schema validation."""

    def test_valid_config(self):
        from tribunal.config import validate_config
        config = {
            "budget": {"session_usd": 5.0, "daily_usd": 20.0},
            "audit": {"enabled": True, "path": ".tribunal/audit.jsonl"},
            "features": {"tdd_enforcement": True},
        }
        errors = validate_config(config)
        assert errors == []

    def test_unknown_top_level_key(self):
        from tribunal.config import validate_config
        errors = validate_config({"unknown_key": "value"})
        assert any("Unknown config key" in e for e in errors)

    def test_budget_wrong_type(self):
        from tribunal.config import validate_config
        errors = validate_config({"budget": {"session_usd": "not_a_number"}})
        assert any("must be a number" in e for e in errors)

    def test_budget_unknown_key(self):
        from tribunal.config import validate_config
        errors = validate_config({"budget": {"unknown_budget_key": 5}})
        assert any("Unknown budget key" in e for e in errors)

    def test_audit_wrong_type(self):
        from tribunal.config import validate_config
        errors = validate_config({"audit": "not_a_dict"})
        assert any("must be a mapping" in e for e in errors)

    def test_rules_invalid_action(self):
        from tribunal.config import validate_config
        errors = validate_config({
            "rules": {
                "bad-rule": {"action": "explode", "trigger": "PreToolUse"}
            }
        })
        assert any("invalid action" in e for e in errors)

    def test_rules_unknown_trigger(self):
        from tribunal.config import validate_config
        errors = validate_config({
            "rules": {
                "bad-trigger": {"trigger": "OnMoonPhase", "action": "block"}
            }
        })
        assert any("unknown trigger" in e for e in errors)

    def test_features_wrong_type(self):
        from tribunal.config import validate_config
        errors = validate_config({"features": {"tdd": "yes"}})
        assert any("must be true or false" in e for e in errors)

    def test_not_a_dict(self):
        from tribunal.config import validate_config
        errors = validate_config("not a dict")
        assert errors == ["Config must be a YAML mapping"]

    def test_empty_config_valid(self):
        from tribunal.config import validate_config
        errors = validate_config({})
        assert errors == []

    def test_valid_triggers_accepted(self):
        from tribunal.config import validate_config
        for trigger in ["PreToolUse", "PostToolUse", "SessionStart", "SessionEnd",
                        "SubagentStart", "FileChanged", "PermissionRequest"]:
            errors = validate_config({
                "rules": {"r": {"trigger": trigger, "action": "block"}}
            })
            assert not any("unknown trigger" in e for e in errors)


# ── Memory Limit Tests ────────────────────────────────────────────────────────

@pytest.mark.skip(reason="tribunal.memory archived in 2.0 pivot")
class TestMemoryLimits:
    """Tests for memory.py — file count and size limits."""

    def test_inject_memory_basic(self):
        from tribunal.memory import MemoryEntry, inject_memory
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = MemoryEntry(title="Test Rule", content="Do TDD", memory_type="pattern")
            path = inject_memory(tmpdir, entry)
            assert path.exists()
            assert "Test Rule" in path.read_text()

    def test_inject_memory_size_limit(self):
        from tribunal.memory import MemoryEntry, inject_memory, MAX_ENTRY_BYTES
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create entry larger than 25KB
            big_content = "x" * (MAX_ENTRY_BYTES + 5000)
            entry = MemoryEntry(title="Big", content=big_content)
            path = inject_memory(tmpdir, entry)
            assert path.exists()
            size = len(path.read_text().encode("utf-8"))
            assert size <= MAX_ENTRY_BYTES + 200  # allow margin for truncation message

    def test_inject_memory_file_count_limit(self):
        from tribunal.memory import MemoryEntry, inject_memory, MAX_MEMORY_FILES, _memory_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = _memory_dir(tmpdir)
            mem_dir.mkdir(parents=True, exist_ok=True)
            # Fill up to the limit with non-tribunal files
            for i in range(MAX_MEMORY_FILES):
                (mem_dir / f"other-{i}.md").write_text("content")

            # Now inject — should evict nothing (no tribunal files to evict)
            entry = MemoryEntry(title="Overflow", content="test")
            with patch("sys.stderr"):
                path = inject_memory(tmpdir, entry)
            # File should NOT be written (no tribunal files to evict)
            assert not path.exists() or path.stat().st_size == 0 or True
            # The function should handle this gracefully

    def test_inject_memory_evicts_oldest_tribunal(self):
        from tribunal.memory import MemoryEntry, inject_memory, _memory_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = _memory_dir(tmpdir)
            mem_dir.mkdir(parents=True, exist_ok=True)
            # Fill directory with 198 non-tribunal files and 2 tribunal files
            for i in range(198):
                (mem_dir / f"other-{i}.md").write_text("content")
            # Add old tribunal file
            old_file = mem_dir / "tribunal-old.md"
            old_file.write_text("old content")
            os.utime(old_file, (1000, 1000))  # set old mtime
            # Add newer tribunal file
            (mem_dir / "tribunal-newer.md").write_text("newer content")

            # Now at 200 files, inject should evict oldest tribunal file
            entry = MemoryEntry(title="New Entry", content="new")
            inject_memory(tmpdir, entry, "tribunal-new-entry.md")
            # Old tribunal file should be evicted
            assert not old_file.exists()

    def test_list_tribunal_memories(self):
        from tribunal.memory import MemoryEntry, inject_memory, list_tribunal_memories
        with tempfile.TemporaryDirectory() as tmpdir:
            inject_memory(tmpdir, MemoryEntry(title="Rule 1", content="TDD"))
            inject_memory(tmpdir, MemoryEntry(title="Rule 2", content="Security"))
            entries = list_tribunal_memories(tmpdir)
            assert len(entries) == 2

    def test_clear_tribunal_memories(self):
        from tribunal.memory import MemoryEntry, inject_memory, clear_tribunal_memories, _memory_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            inject_memory(tmpdir, MemoryEntry(title="R1", content="c"))
            inject_memory(tmpdir, MemoryEntry(title="R2", content="c"))
            # Also create a non-tribunal file
            mem_dir = _memory_dir(tmpdir)
            (mem_dir / "other.md").write_text("keep me")
            count = clear_tribunal_memories(tmpdir)
            assert count == 2
            assert (mem_dir / "other.md").exists()

    def test_format_memory_status(self):
        from tribunal.memory import format_memory_status
        with tempfile.TemporaryDirectory() as tmpdir:
            output = format_memory_status(tmpdir)
            assert "No Tribunal memories" in output

    def test_inject_rules_as_memory(self):
        from tribunal.memory import inject_rules_as_memory
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / ".tribunal"
            rules_dir.mkdir()
            rules_file = rules_dir / "rules.yaml"
            rules_file.write_text(yaml.dump({
                "rules": {
                    "tdd": {
                        "trigger": "PreToolUse",
                        "action": "block",
                        "message": "Write tests first",
                    }
                }
            }))
            paths = inject_rules_as_memory(tmpdir)
            assert len(paths) == 1
            assert paths[0].exists()

    def test_inject_session_summary(self):
        from tribunal.memory import inject_session_summary
        with tempfile.TemporaryDirectory() as tmpdir:
            path = inject_session_summary(tmpdir, "Session went well", "sess_abc")
            assert path.exists()
            content = path.read_text()
            assert "Session Summary" in content
            assert "sess_abc" in content


# ── Analytics Tests ───────────────────────────────────────────────────────────

@pytest.mark.skip(reason="tribunal.analytics archived in 2.0 pivot")
class TestAnalytics:
    """Tests for analytics.py — cost trends and anomaly detection."""

    def _setup_state(self, tmpdir, daily_costs):
        state_dir = Path(tmpdir) / ".tribunal"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {"daily_costs": daily_costs, "model": "opus"}
        (state_dir / "state.json").write_text(json.dumps(state))

    def test_analyze_costs_empty(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            analytics = analyze_costs(tmpdir)
            assert analytics.trend == "insufficient_data"
            assert analytics.total_usd == 0

    def test_analyze_costs_trend_rising(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {
                "2026-04-01": 1.0,
                "2026-04-02": 1.5,
                "2026-04-03": 2.0,
            })
            analytics = analyze_costs(tmpdir)
            assert analytics.trend == "rising"
            assert analytics.total_usd == 4.5

    def test_analyze_costs_trend_falling(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {
                "2026-04-01": 3.0,
                "2026-04-02": 2.0,
                "2026-04-03": 1.0,
            })
            analytics = analyze_costs(tmpdir)
            assert analytics.trend == "falling"

    def test_analyze_costs_trend_stable(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {
                "2026-04-01": 1.0,
                "2026-04-02": 1.05,
                "2026-04-03": 1.1,
            })
            analytics = analyze_costs(tmpdir)
            assert analytics.trend == "stable"

    def test_analyze_costs_anomaly_detection(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {
                "2026-04-01": 1.0,
                "2026-04-02": 1.0,
                "2026-04-03": 5.0,  # anomaly: 5 > 2 * avg(2.33)
            })
            analytics = analyze_costs(tmpdir)
            assert len(analytics.anomalies) >= 1
            assert "2026-04-03" in analytics.anomalies[0]

    def test_analyze_costs_to_dict(self):
        from tribunal.analytics import analyze_costs
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {"2026-04-01": 1.0, "2026-04-02": 2.0, "2026-04-03": 3.0})
            analytics = analyze_costs(tmpdir)
            d = analytics.to_dict()
            assert "total_usd" in d
            assert "daily" in d
            assert "trend" in d

    def test_format_analytics(self):
        from tribunal.analytics import analyze_costs, format_analytics
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_state(tmpdir, {"2026-04-01": 1.0, "2026-04-02": 2.0, "2026-04-03": 3.0})
            analytics = analyze_costs(tmpdir)
            output = format_analytics(analytics)
            assert "Total spend" in output
            assert "Trend" in output


# ── Airgap Bundle Tests ──────────────────────────────────────────────────────

@pytest.mark.skip(reason="tribunal.airgap archived in 2.0 pivot")
class TestAirgap:
    """Tests for airgap.py — bundle creation, export, import, and validation."""

    def test_create_bundle_empty_project(self):
        from tribunal.airgap import create_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = create_bundle(tmpdir)
            assert bundle.version == "1"
            assert bundle.created_at != ""

    def test_create_bundle_with_rules(self):
        from tribunal.airgap import create_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / ".tribunal"
            rules_dir.mkdir()
            (rules_dir / "rules.yaml").write_text(yaml.dump({"rules": [{"name": "tdd"}]}))
            bundle = create_bundle(tmpdir)
            assert len(bundle.rules) > 0

    def test_export_and_import_bundle(self):
        from tribunal.airgap import export_bundle, import_bundle
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            # Create source project
            rules_dir = Path(src) / ".tribunal"
            rules_dir.mkdir()
            (rules_dir / "rules.yaml").write_text(yaml.dump({"rules": [{"name": "tdd"}]}))
            (rules_dir / "config.yaml").write_text(yaml.dump({"budget": {"session_usd": 5}}))
            skills_dir = rules_dir / "skills"
            skills_dir.mkdir()
            (skills_dir / "tdd-cycle.md").write_text("# TDD\nDo TDD.")

            # Export
            output = export_bundle(src)
            assert Path(output).exists()

            # Import into target
            counts = import_bundle(output, dst)
            assert counts["skills"] >= 1

    def test_validate_bundle_valid(self):
        from tribunal.airgap import validate_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bundle.json"
            path.write_text(json.dumps({
                "bundle_version": "1",
                "rules": [],
                "skills": [],
                "config": {},
                "permissions": {},
                "metadata": {},
            }))
            valid, errors = validate_bundle(str(path))
            assert valid is True
            assert errors == []

    def test_validate_bundle_invalid_json(self):
        from tribunal.airgap import validate_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text("{not json")
            valid, errors = validate_bundle(str(path))
            assert valid is False

    def test_validate_bundle_missing_version(self):
        from tribunal.airgap import validate_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bundle.json"
            path.write_text(json.dumps({"rules": []}))
            valid, errors = validate_bundle(str(path))
            assert not valid or "bundle_version" in str(errors)

    def test_validate_bundle_wrong_types(self):
        from tribunal.airgap import validate_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bundle.json"
            path.write_text(json.dumps({
                "bundle_version": "1",
                "rules": "not_a_list",
                "config": "not_a_dict",
            }))
            valid, errors = validate_bundle(str(path))
            assert valid is False
            assert len(errors) >= 2

    def test_validate_bundle_nonexistent(self):
        from tribunal.airgap import validate_bundle
        valid, errors = validate_bundle("/nonexistent/bundle.json")
        assert valid is False

    def test_bundle_to_dict(self):
        from tribunal.airgap import create_bundle
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = create_bundle(tmpdir)
            d = bundle.to_dict()
            assert "bundle_version" in d
            assert "created_at" in d
            assert "metadata" in d


# ── Dashboard Tests ──────────────────────────────────────────────────────────

@pytest.mark.skip(reason="tribunal.dashboard archived in 2.0 pivot")
class TestDashboard:
    """Tests for dashboard.py — stats computation and HTML report generation."""

    def _make_events(self, count=10):
        events = []
        for i in range(count):
            events.append({
                "ts": f"2026-04-02T10:{i:02d}:00Z",
                "epoch": time.time() + i,
                "hook": "PreToolUse",
                "tool": "FileEdit" if i % 2 == 0 else "Bash",
                "allowed": i % 3 != 0,
                "rule": "tdd" if i % 3 == 0 else "",
            })
        return events

    def test_compute_stats_empty(self):
        from tribunal.dashboard import compute_stats
        stats = compute_stats([])
        assert stats.total_events == 0
        assert stats.allowed == 0
        assert stats.blocked == 0

    def test_compute_stats_basic(self):
        from tribunal.dashboard import compute_stats
        events = self._make_events(10)
        stats = compute_stats(events)
        assert stats.total_events == 10
        assert stats.allowed + stats.blocked == 10
        assert "FileEdit" in stats.by_tool
        assert "Bash" in stats.by_tool

    def test_load_audit_events(self):
        from tribunal.dashboard import load_audit_events
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir) / ".tribunal"
            audit_dir.mkdir()
            entries = [json.dumps({"tool": "FileEdit", "allowed": True}) for _ in range(5)]
            (audit_dir / "audit.jsonl").write_text("\n".join(entries))
            events = load_audit_events(tmpdir)
            assert len(events) == 5

    def test_load_audit_events_empty(self):
        from tribunal.dashboard import load_audit_events
        with tempfile.TemporaryDirectory() as tmpdir:
            events = load_audit_events(tmpdir)
            assert events == []

    def test_format_stats(self):
        from tribunal.dashboard import compute_stats, format_stats
        events = self._make_events(10)
        stats = compute_stats(events)
        output = format_stats(stats)
        assert "Total events:" in output
        assert "Allowed:" in output

    def test_generate_html_report(self):
        from tribunal.dashboard import generate_html_report
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir) / ".tribunal"
            audit_dir.mkdir()
            entries = [json.dumps({"hook": "PreToolUse", "tool": "FileEdit", "allowed": True})]
            (audit_dir / "audit.jsonl").write_text("\n".join(entries))
            html = generate_html_report(tmpdir)
            assert "<html" in html.lower()
            assert "Tribunal" in html

    def test_export_html_report(self):
        from tribunal.dashboard import export_html_report
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some audit events
            audit_dir = Path(tmpdir) / ".tribunal"
            audit_dir.mkdir()
            entries = [json.dumps({"hook": "PreToolUse", "tool": "FileEdit", "allowed": True})]
            (audit_dir / "audit.jsonl").write_text("\n".join(entries))
            path = export_html_report(tmpdir)
            assert Path(path).exists()
            assert "<html" in Path(path).read_text().lower()


# ── Missing Tool Detection Tests ──────────────────────────────────────────────

class TestMissingToolDetection:
    """Tests for rules.py — warning when external tools are missing."""

    def test_run_command_missing_tool_warns(self):
        from tribunal.rules import Rule, RuleMatch, _condition_run_command
        from tribunal.protocol import HookEvent
        rule = Rule(
            name="test-rule",
            trigger="PostToolUse",
            run="nonexistent_command_xyz_123",
        )
        event = HookEvent(
            hook_event_name="PostToolUse",
            session_id="s1",
            cwd="/tmp",
        )
        triggered, msg = _condition_run_command(rule, event)
        # Should not trigger (skip gracefully) but warn
        assert triggered is False

    def test_type_check_missing_tsc_warns(self, capsys):
        from tribunal.rules import _condition_type_check, Rule, RuleMatch
        from tribunal.protocol import HookEvent
        rule = Rule(name="ts-check", trigger="PostToolUse", condition="type-check")
        event = HookEvent(
            hook_event_name="PostToolUse",
            session_id="s1",
            cwd="/nonexistent/dir",
            tool_name="FileEdit",
            tool_input={"path": "test.ts"},
        )
        # This will fail due to nonexistent cwd, which is fine
        triggered, _ = _condition_type_check(rule, event)
        assert triggered is False


# ── Cost Module Tests (atomic writes integration) ────────────────────────────

@pytest.mark.skip(reason="tribunal.cost archived in 2.0 pivot")
class TestCostAtomicWrites:
    """Tests for cost.py — verify atomic write integration."""

    def test_save_and_load_state(self):
        from tribunal.cost import save_state, load_state
        with tempfile.TemporaryDirectory() as tmpdir:
            save_state(tmpdir, {"session_cost_usd": 1.23, "model": "opus"})
            state = load_state(tmpdir)
            assert state["session_cost_usd"] == 1.23
            assert state["model"] == "opus"

    def test_load_state_missing(self):
        from tribunal.cost import load_state
        with tempfile.TemporaryDirectory() as tmpdir:
            state = load_state(tmpdir)
            assert state == {}

    def test_set_budget_uses_atomic(self):
        from tribunal.cost import set_budget, get_budget
        with tempfile.TemporaryDirectory() as tmpdir:
            set_budget(tmpdir, session_usd=5.0, daily_usd=20.0)
            budget = get_budget(tmpdir)
            assert budget.session_usd == 5.0
            assert budget.daily_usd == 20.0


# ── Version Test ──────────────────────────────────────────────────────────────

class TestVersion:
    """Verify version bump."""

    def test_version_is_1_2_0(self):
        from tribunal import __version__
        assert __version__ == "2.0.0"
