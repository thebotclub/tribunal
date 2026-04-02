"""Tests for Phase 10 — Programmatic SDK, Rule Packs, Docs site."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml


# ── Rule Packs ────────────────────────────────────────────────────────────

class TestRulePacks:
    def test_list_packs(self):
        from tribunal.packs import list_packs
        packs = list_packs()
        assert len(packs) >= 4
        names = [p["name"] for p in packs]
        assert "soc2" in names
        assert "startup" in names
        assert "enterprise" in names
        assert "security" in names

    def test_get_pack_exists(self):
        from tribunal.packs import get_pack
        pack = get_pack("soc2")
        assert pack is not None
        assert "rules" in pack
        assert "config" in pack

    def test_get_pack_missing(self):
        from tribunal.packs import get_pack
        assert get_pack("nonexistent") is None

    def test_install_pack_creates_files(self):
        from tribunal.packs import install_pack
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, msgs = install_pack("startup", tmpdir)
            assert ok
            rules_path = Path(tmpdir) / ".tribunal" / "rules.yaml"
            assert rules_path.is_file()
            data = yaml.safe_load(rules_path.read_text())
            assert "rules" in data

    def test_install_pack_merge(self):
        from tribunal.packs import install_pack
        with tempfile.TemporaryDirectory() as tmpdir:
            # Install one pack first
            install_pack("startup", tmpdir)
            # Merge another
            ok, msgs = install_pack("security", tmpdir, merge=True)
            assert ok
            rules_path = Path(tmpdir) / ".tribunal" / "rules.yaml"
            data = yaml.safe_load(rules_path.read_text())
            # Should have rules from both packs
            assert len(data["rules"]) >= 5

    def test_install_pack_invalid(self):
        from tribunal.packs import install_pack
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, msgs = install_pack("fake-pack", tmpdir)
            assert not ok

    def test_format_packs(self):
        from tribunal.packs import format_packs
        output = format_packs()
        assert "soc2" in output
        assert "startup" in output


# ── SDK ───────────────────────────────────────────────────────────────────

class TestSDKInit:
    def test_default_cwd(self):
        from tribunal.sdk import TribunalSDK
        sdk = TribunalSDK()
        assert sdk.cwd == str(Path.cwd())

    def test_custom_cwd(self):
        from tribunal.sdk import TribunalSDK
        sdk = TribunalSDK("/tmp/test-project")
        assert sdk.cwd == "/tmp/test-project"


class TestSDKEvaluate:
    def _setup_project(self, tmpdir: str) -> str:
        """Create a minimal .tribunal project."""
        tribunal_dir = Path(tmpdir) / ".tribunal"
        tribunal_dir.mkdir()
        rules = {
            "rules": {
                "block-bash": {
                    "trigger": "PreToolUse",
                    "action": "block",
                    "match": {"tool": "Bash"},
                    "message": "Bash is blocked",
                },
                "warn-write": {
                    "trigger": "PreToolUse",
                    "action": "warn",
                    "match": {"tool": "FileEdit"},
                    "message": "Write detected",
                },
            }
        }
        (tribunal_dir / "rules.yaml").write_text(yaml.dump(rules))
        return tmpdir

    def test_evaluate_allowed(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            sdk = TribunalSDK(tmpdir)
            # Read tool - not matching any block rule
            result = sdk.evaluate("PreToolUse", tool_name="Read")
            assert result.allowed
            assert not result.blocked

    def test_evaluate_blocked(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            sdk = TribunalSDK(tmpdir)
            result = sdk.evaluate("PreToolUse", tool_name="Bash", tool_input={"command": "echo hello"})
            assert result.blocked
            assert not result.allowed
            assert result.message  # should have a reason

    def test_evaluate_warning(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            sdk = TribunalSDK(tmpdir)
            result = sdk.evaluate("PreToolUse", tool_name="FileEdit", tool_input={"path": "app.py"})
            assert result.allowed
            assert not result.blocked

    def test_evaluate_no_rules_file(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = TribunalSDK(tmpdir)
            # Should handle missing rules gracefully
            result = sdk.evaluate("PreToolUse", tool_name="Bash")
            assert result.allowed


class TestSDKRules:
    def test_list_rules(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            tribunal_dir = Path(tmpdir) / ".tribunal"
            tribunal_dir.mkdir()
            rules = {
                "rules": {
                    "r1": {"trigger": "PreToolUse", "action": "block", "match": {"tool": "Bash"}, "message": "no bash"},
                    "r2": {"trigger": "PreToolUse", "action": "warn", "match": {"tool": "FileEdit"}, "message": "careful"},
                }
            }
            (tribunal_dir / "rules.yaml").write_text(yaml.dump(rules))
            sdk = TribunalSDK(tmpdir)
            rules_list = sdk.list_rules()
            assert len(rules_list) == 2
            names = [r["name"] for r in rules_list]
            assert "r1" in names
            assert "r2" in names

    def test_install_pack(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = TribunalSDK(tmpdir)
            ok, msgs = sdk.install_pack("soc2")
            assert ok
            assert (Path(tmpdir) / ".tribunal" / "rules.yaml").is_file()


class TestSDKCost:
    def test_cost_snapshot_empty(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = TribunalSDK(tmpdir)
            snap = sdk.cost_snapshot()
            assert isinstance(snap, dict)

    def test_set_budget(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .tribunal dir
            (Path(tmpdir) / ".tribunal").mkdir()
            sdk = TribunalSDK(tmpdir)
            sdk.set_budget(session_usd=5.0, daily_usd=20.0)
            snap = sdk.cost_snapshot()
            budget = snap.get("budget", {})
            assert budget.get("session_usd") == 5.0
            assert budget.get("daily_usd") == 20.0


class TestSDKAudit:
    def test_audit_entries_empty(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = TribunalSDK(tmpdir)
            assert sdk.audit_entries() == []

    def test_audit_entries_reads_log(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            tribunal_dir = Path(tmpdir) / ".tribunal"
            tribunal_dir.mkdir()
            entries = [
                {"ts": "2025-01-01T00:00:00Z", "hook": "PreToolUse", "allowed": True},
                {"ts": "2025-01-01T00:01:00Z", "hook": "PreToolUse", "allowed": False},
            ]
            (tribunal_dir / "audit.jsonl").write_text(
                "\n".join(json.dumps(e) for e in entries)
            )
            sdk = TribunalSDK(tmpdir)
            result = sdk.audit_entries()
            assert len(result) == 2
            assert result[0]["allowed"] is True


class TestSDKDoctor:
    def test_doctor_empty_project(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            sdk = TribunalSDK(tmpdir)
            health = sdk.doctor()
            assert "issues" in health
            assert "checks" in health
            assert isinstance(health["healthy"], bool)

    def test_doctor_with_tribunal_dir(self):
        from tribunal.sdk import TribunalSDK
        with tempfile.TemporaryDirectory() as tmpdir:
            tribunal_dir = Path(tmpdir) / ".tribunal"
            tribunal_dir.mkdir()
            rules = {"rules": {"r1": {"trigger": "PreToolUse", "action": "warn", "match": {"tool": "Bash"}}}}
            (tribunal_dir / "rules.yaml").write_text(yaml.dump(rules))
            sdk = TribunalSDK(tmpdir)
            health = sdk.doctor()
            # .tribunal/ and rules.yaml should be OK
            check_names = [c["check"] for c in health["checks"]]
            assert ".tribunal/" in check_names
            assert "rules.yaml" in check_names


class TestEvalResult:
    def test_message_property(self):
        from tribunal.sdk import EvalResult
        r = EvalResult(allowed=False, blocked=True, messages=["a", "b"], triggered_rules=[])
        assert r.message == "a; b"

    def test_message_empty(self):
        from tribunal.sdk import EvalResult
        r = EvalResult(allowed=True, blocked=False, messages=[], triggered_rules=[])
        assert r.message == ""
