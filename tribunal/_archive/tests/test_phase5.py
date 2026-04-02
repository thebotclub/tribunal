"""Tests for Phase 5 — remaining roadmap items.

Covers: memory injection, cost analytics, air-gapped bundles,
        audit dashboard, and new CLI commands.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tribunal.memory import (
    MemoryEntry,
    clear_tribunal_memories,
    format_memory_status,
    inject_memory,
    inject_rules_as_memory,
    inject_session_summary,
    list_tribunal_memories,
)
from tribunal.analytics import (
    CostAnalytics,
    CostPeriod,
    analyze_costs,
    format_analytics,
)
from tribunal.airgap import (
    AirgapBundle,
    create_bundle,
    export_bundle,
    import_bundle,
    validate_bundle,
)
from tribunal.dashboard import (
    AuditStats,
    compute_stats,
    export_html_report,
    format_stats,
    generate_html_report,
    load_audit_events,
)


# ──────────────────────────────────────────────────────────────────────────────
# Memory Injection Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestMemoryEntry:
    def test_to_markdown_basic(self):
        entry = MemoryEntry(title="Test", content="Hello world", memory_type="pattern")
        md = entry.to_markdown()
        assert "---" in md
        assert "# Test" in md
        assert "Hello world" in md
        assert "type: pattern" in md
        assert "source: tribunal" in md

    def test_to_markdown_with_tags(self):
        entry = MemoryEntry(title="Tagged", content="body", tags=["a", "b"])
        md = entry.to_markdown()
        assert "tags:" in md
        assert "- a" in md
        assert "- b" in md

    def test_to_markdown_no_title(self):
        entry = MemoryEntry(content="just content")
        md = entry.to_markdown()
        assert "# " not in md
        assert "just content" in md


class TestInjectMemory:
    def test_inject_creates_file(self, tmp_path):
        entry = MemoryEntry(title="Test Rule", content="Be careful")
        path = inject_memory(str(tmp_path), entry)
        assert path.exists()
        assert path.name == "tribunal-test-rule.md"
        assert "Be careful" in path.read_text()

    def test_inject_custom_filename(self, tmp_path):
        entry = MemoryEntry(title="X", content="Y")
        path = inject_memory(str(tmp_path), entry, filename="custom.md")
        assert path.name == "custom.md"
        assert path.exists()

    def test_inject_creates_directory(self, tmp_path):
        cwd = tmp_path / "deep" / "project"
        entry = MemoryEntry(title="Test", content="test")
        path = inject_memory(str(cwd), entry)
        assert path.parent.is_dir()


class TestInjectRulesAsMemory:
    def test_injects_rules(self, tmp_path):
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text(yaml.dump({
            "rules": {
                "no-secrets": {
                    "trigger": "PreToolUse",
                    "action": "block",
                    "message": "No secrets allowed",
                },
                "tdd": {
                    "trigger": "PreToolUse",
                    "action": "warn",
                    "message": "Write tests first",
                },
            }
        }))
        paths = inject_rules_as_memory(str(tmp_path))
        assert len(paths) == 2
        assert all(p.exists() for p in paths)

    def test_no_rules_yaml(self, tmp_path):
        paths = inject_rules_as_memory(str(tmp_path))
        assert paths == []

    def test_empty_rules(self, tmp_path):
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text(yaml.dump({"rules": {}}))
        paths = inject_rules_as_memory(str(tmp_path))
        assert paths == []


class TestSessionSummary:
    def test_injects_summary(self, tmp_path):
        path = inject_session_summary(str(tmp_path), "Great session")
        assert path.exists()
        content = path.read_text()
        assert "Great session" in content
        assert "session-log" in content

    def test_with_session_id(self, tmp_path):
        path = inject_session_summary(str(tmp_path), "Test", session_id="abc12345-long")
        content = path.read_text()
        assert "abc12345" in content


class TestClearMemories:
    def test_clear_removes_tribunal_files(self, tmp_path):
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "tribunal-rule-x.md").write_text("tribunal file")
        (mem_dir / "tribunal-rule-y.md").write_text("tribunal file")
        (mem_dir / "user-note.md").write_text("user file")

        removed = clear_tribunal_memories(str(tmp_path))
        assert removed == 2
        assert not (mem_dir / "tribunal-rule-x.md").exists()
        assert (mem_dir / "user-note.md").exists()

    def test_clear_no_dir(self, tmp_path):
        removed = clear_tribunal_memories(str(tmp_path))
        assert removed == 0


class TestListMemories:
    def test_list_entries(self, tmp_path):
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        entry = MemoryEntry(title="Rule", content="test", memory_type="warning")
        (mem_dir / "tribunal-rule.md").write_text(entry.to_markdown())

        entries = list_tribunal_memories(str(tmp_path))
        assert len(entries) == 1
        assert entries[0]["file"] == "tribunal-rule.md"
        assert entries[0]["type"] == "warning"

    def test_list_empty(self, tmp_path):
        result = list_tribunal_memories(str(tmp_path))
        assert result == []


class TestFormatMemoryStatus:
    def test_format_with_entries(self, tmp_path):
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        entry = MemoryEntry(title="Test", content="hi")
        (mem_dir / "tribunal-test.md").write_text(entry.to_markdown())

        output = format_memory_status(str(tmp_path))
        assert "Memory Status" in output
        assert "tribunal-test.md" in output

    def test_format_empty(self, tmp_path):
        output = format_memory_status(str(tmp_path))
        assert "No Tribunal memories" in output


# ──────────────────────────────────────────────────────────────────────────────
# Cost Analytics Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestCostPeriod:
    def test_avg_session_cost(self):
        p = CostPeriod(period="2026-04-01", total_usd=1.0, session_count=4)
        assert p.avg_session_cost == 0.25

    def test_avg_session_cost_zero(self):
        p = CostPeriod(period="2026-04-01", total_usd=0, session_count=0)
        assert p.avg_session_cost == 0.0


class TestAnalyzeCosts:
    def test_no_data(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        (tmp_path / ".tribunal" / "state.json").write_text("{}")
        analytics = analyze_costs(str(tmp_path))
        assert analytics.trend == "insufficient_data"
        assert analytics.total_usd == 0.0

    def test_with_daily_costs(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        state = {
            "daily_costs": {
                "2026-04-01": 0.10,
                "2026-04-02": 0.15,
                "2026-04-03": 0.20,
                "2026-04-04": 0.25,
            }
        }
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps(state))
        analytics = analyze_costs(str(tmp_path))
        assert analytics.total_usd == pytest.approx(0.70)
        assert len(analytics.daily) == 4
        assert analytics.trend == "rising"

    def test_falling_trend(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        state = {
            "daily_costs": {
                "2026-04-01": 0.50,
                "2026-04-02": 0.30,
                "2026-04-03": 0.10,
            }
        }
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps(state))
        analytics = analyze_costs(str(tmp_path))
        assert analytics.trend == "falling"

    def test_stable_trend(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        state = {
            "daily_costs": {
                "2026-04-01": 0.10,
                "2026-04-02": 0.10,
                "2026-04-03": 0.10,
            }
        }
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps(state))
        analytics = analyze_costs(str(tmp_path))
        assert analytics.trend == "stable"

    def test_anomaly_detection(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        state = {
            "daily_costs": {
                "2026-04-01": 0.10,
                "2026-04-02": 0.10,
                "2026-04-03": 0.80,  # anomaly
            }
        }
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps(state))
        analytics = analyze_costs(str(tmp_path))
        assert len(analytics.anomalies) >= 1

    def test_with_model_costs(self, tmp_path):
        (tmp_path / ".tribunal").mkdir()
        state = {
            "daily_costs": {"2026-04-01": 0.50},
            "model_costs": {"claude-sonnet": 0.30, "claude-haiku": 0.20},
        }
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps(state))
        analytics = analyze_costs(str(tmp_path))
        assert "claude-sonnet" in analytics.by_model
        assert analytics.by_model["claude-sonnet"] == 0.30

    def test_to_dict(self):
        a = CostAnalytics(total_usd=1.0, session_count=2, trend="stable")
        d = a.to_dict()
        assert d["total_usd"] == 1.0
        assert d["trend"] == "stable"


class TestFormatAnalytics:
    def test_format_with_data(self, tmp_path):
        analytics = CostAnalytics(
            total_usd=0.50,
            session_count=5,
            trend="rising",
            by_model={"claude-sonnet": 0.50},
            daily=[CostPeriod("2026-04-01", 0.50, 5)],
        )
        output = format_analytics(analytics)
        assert "Cost Analytics" in output
        assert "0.50" in output
        assert "rising" in output


# ──────────────────────────────────────────────────────────────────────────────
# Air-gapped Bundle Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestAirgapBundle:
    def test_to_dict(self):
        b = AirgapBundle(version="1", created_at="now", rules=[{"x": 1}])
        d = b.to_dict()
        assert d["bundle_version"] == "1"
        assert len(d["rules"]) == 1


class TestCreateBundle:
    def test_creates_from_project(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        (t_dir / "rules.yaml").write_text(yaml.dump({
            "rules": [{"name": "r1", "action": "block"}]
        }))
        (t_dir / "config.yaml").write_text(yaml.dump({"tdd": True}))

        bundle = create_bundle(str(tmp_path))
        assert len(bundle.rules) == 1
        assert bundle.config.get("tdd") is True
        assert bundle.created_at != ""

    def test_creates_empty_bundle(self, tmp_path):
        bundle = create_bundle(str(tmp_path))
        assert bundle.rules == []
        # Should still include bundled skills
        assert len(bundle.skills) >= 0


class TestExportBundle:
    def test_exports_json(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        (t_dir / "rules.yaml").write_text(yaml.dump({"rules": [{"a": 1}]}))

        output = export_bundle(str(tmp_path))
        path = Path(output)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["bundle_version"] == "1"
        assert len(data["rules"]) == 1

    def test_custom_output(self, tmp_path):
        out = str(tmp_path / "my-bundle.json")
        export_bundle(str(tmp_path), output=out)
        assert Path(out).exists()


class TestImportBundle:
    def test_imports_all(self, tmp_path):
        # Create a bundle file
        bundle = {
            "bundle_version": "1",
            "rules": [{"name": "r1", "action": "block"}],
            "skills": [{"name": "my-skill", "content": "# Skill\nDo stuff"}],
            "config": {"tdd": True},
            "permissions": {"deny": ["rm -rf"]},
            "metadata": {"bundle_format": "tribunal-airgap-v1"},
        }
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps(bundle))

        target = tmp_path / "target"
        target.mkdir()
        counts = import_bundle(str(bundle_path), str(target))
        assert counts["rules"] == 1
        assert counts["skills"] == 1
        assert counts["config"] == 1
        assert counts["permissions"] == 1

        # Verify files
        assert (target / ".tribunal" / "rules.yaml").exists()
        assert (target / ".tribunal" / "skills" / "my-skill.md").exists()


class TestValidateBundle:
    def test_valid_bundle(self, tmp_path):
        bundle = {"bundle_version": "1", "rules": [], "skills": [], "config": {}}
        path = tmp_path / "good.json"
        path.write_text(json.dumps(bundle))
        ok, errors = validate_bundle(str(path))
        assert ok
        assert errors == []

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        ok, errors = validate_bundle(str(path))
        assert not ok
        assert any("JSON" in e for e in errors)

    def test_missing_file(self, tmp_path):
        ok, errors = validate_bundle(str(tmp_path / "missing.json"))
        assert not ok

    def test_missing_version(self, tmp_path):
        path = tmp_path / "noversion.json"
        path.write_text(json.dumps({"rules": []}))
        ok, errors = validate_bundle(str(path))
        assert not ok
        assert any("version" in e for e in errors)

    def test_wrong_types(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"bundle_version": "1", "rules": "not a list"}))
        ok, errors = validate_bundle(str(path))
        assert not ok


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestLoadAuditEvents:
    def test_loads_events(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        events = [
            {"ts": "2026-04-01T00:00:00Z", "hook": "PreToolUse", "tool": "Bash", "allowed": True},
            {"ts": "2026-04-01T00:01:00Z", "hook": "PreToolUse", "tool": "FileEdit", "allowed": False, "rule": "no-secrets"},
        ]
        (t_dir / "audit.jsonl").write_text("\n".join(json.dumps(e) for e in events))

        loaded = load_audit_events(str(tmp_path))
        assert len(loaded) == 2

    def test_no_file(self, tmp_path):
        assert load_audit_events(str(tmp_path)) == []

    def test_handles_bad_json(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        (t_dir / "audit.jsonl").write_text('{"ok": true}\ninvalid\n{"ok": false}\n')
        events = load_audit_events(str(tmp_path))
        assert len(events) == 2


class TestComputeStats:
    def test_computes_stats(self):
        events = [
            {"hook": "PreToolUse", "tool": "Bash", "allowed": True},
            {"hook": "PreToolUse", "tool": "FileEdit", "allowed": False, "rule": "r1"},
            {"hook": "PostToolUse", "tool": "Bash", "allowed": True},
        ]
        stats = compute_stats(events)
        assert stats.total_events == 3
        assert stats.allowed == 2
        assert stats.blocked == 1
        assert stats.by_hook["PreToolUse"] == 2
        assert stats.by_tool["Bash"] == 2
        assert stats.by_rule["r1"] == 1

    def test_empty_events(self):
        stats = compute_stats([])
        assert stats.total_events == 0
        assert stats.allowed == 0
        assert stats.blocked == 0


class TestFormatStats:
    def test_format_with_data(self):
        stats = AuditStats(total_events=10, allowed=8, blocked=2)
        stats.by_hook = {"PreToolUse": 10}
        output = format_stats(stats)
        assert "Dashboard" in output
        assert "10" in output
        assert "20.0%" in output


class TestGenerateHtmlReport:
    def test_generates_html(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        events = [
            {"ts": "2026-04-01", "hook": "PreToolUse", "tool": "Bash", "allowed": True},
            {"ts": "2026-04-01", "hook": "PreToolUse", "tool": "FileEdit", "allowed": False, "rule": "r1"},
        ]
        (t_dir / "audit.jsonl").write_text("\n".join(json.dumps(e) for e in events))

        html = generate_html_report(str(tmp_path))
        assert "<!DOCTYPE html>" in html
        assert "Tribunal Audit Report" in html
        assert "BLOCK" in html
        assert "ALLOW" in html

    def test_empty_report(self, tmp_path):
        html = generate_html_report(str(tmp_path))
        assert "<!DOCTYPE html>" in html
        assert "No events" in html


class TestExportHtmlReport:
    def test_exports_html_file(self, tmp_path):
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        (t_dir / "audit.jsonl").write_text('{"ts":"now","hook":"X","allowed":true}\n')

        output = export_html_report(str(tmp_path))
        assert Path(output).exists()
        assert Path(output).read_text().startswith("<!DOCTYPE html>")

    def test_custom_output(self, tmp_path):
        out = str(tmp_path / "report.html")
        export_html_report(str(tmp_path), output=out)
        assert Path(out).exists()


# ──────────────────────────────────────────────────────────────────────────────
# CLI Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestCLIMemory:
    def test_memory_inject(self, tmp_path, monkeypatch):
        from tribunal.cli import cmd_memory
        import argparse

        # Set up rules
        t_dir = tmp_path / ".tribunal"
        t_dir.mkdir()
        (t_dir / "rules.yaml").write_text(yaml.dump({
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block", "message": "test"}}
        }))
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(mem_command="inject")
        result = cmd_memory(args)
        assert result == 0

    def test_memory_list(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_memory
        import argparse

        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(mem_command="list")
        result = cmd_memory(args)
        assert result == 0
        assert "Memory Status" in capsys.readouterr().out

    def test_memory_clear(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_memory
        import argparse

        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(mem_command="clear")
        result = cmd_memory(args)
        assert result == 0
        assert "Removed" in capsys.readouterr().out

    def test_memory_summary(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_memory
        import argparse

        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(mem_command="summary", text="Test session")
        result = cmd_memory(args)
        assert result == 0


class TestCLIAnalytics:
    def test_analytics_text(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_analytics
        import argparse

        (tmp_path / ".tribunal").mkdir()
        (tmp_path / ".tribunal" / "state.json").write_text(json.dumps({
            "daily_costs": {"2026-04-01": 0.10}
        }))
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(json_output=False)
        result = cmd_analytics(args)
        assert result == 0
        assert "Analytics" in capsys.readouterr().out

    def test_analytics_json(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_analytics
        import argparse

        (tmp_path / ".tribunal").mkdir()
        (tmp_path / ".tribunal" / "state.json").write_text("{}")
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(json_output=True)
        result = cmd_analytics(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "total_usd" in data


class TestCLIBundle:
    def test_bundle_export(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_bundle
        import argparse

        (tmp_path / ".tribunal").mkdir()
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(bundle_command="export", output=None)
        result = cmd_bundle(args)
        assert result == 0
        assert "exported" in capsys.readouterr().out

    def test_bundle_validate_valid(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_bundle
        import argparse

        bundle_file = tmp_path / "b.json"
        bundle_file.write_text(json.dumps({"bundle_version": "1", "rules": []}))
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(bundle_command="validate", file=str(bundle_file))
        result = cmd_bundle(args)
        assert result == 0

    def test_bundle_import(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_bundle
        import argparse

        bundle_file = tmp_path / "b.json"
        bundle_file.write_text(json.dumps({
            "bundle_version": "1",
            "rules": [{"a": 1}],
            "skills": [],
            "config": {},
            "permissions": {},
            "metadata": {},
        }))

        target = tmp_path / "target"
        target.mkdir()
        monkeypatch.chdir(target)

        args = argparse.Namespace(bundle_command="import", file=str(bundle_file))
        result = cmd_bundle(args)
        assert result == 0


class TestCLIDashboard:
    def test_dashboard_show(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_dashboard
        import argparse

        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(dash_command=None)
        result = cmd_dashboard(args)
        assert result == 0
        assert "Dashboard" in capsys.readouterr().out

    def test_dashboard_html(self, tmp_path, monkeypatch, capsys):
        from tribunal.cli import cmd_dashboard
        import argparse

        (tmp_path / ".tribunal").mkdir()
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(dash_command="html", output=None)
        result = cmd_dashboard(args)
        assert result == 0
        out = capsys.readouterr().out
        assert "exported" in out
