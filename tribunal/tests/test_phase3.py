"""Tests for Phase 3 features: plugin manifest, MCP server, review agents, config cascade."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tribunal.config import (
    TribunalConfig,
    format_config,
    is_feature_enabled,
    resolve_config,
)
from tribunal.mcp_server import TOOLS, handle_request
from tribunal.plugin import PluginManifest, generate_manifest, install_plugin_manifest
from tribunal.review import (
    AGENTS,
    ReviewFinding,
    ReviewReport,
    get_changed_files,
    run_review,
)


# ── Plugin Manifest Tests ────────────────────────────────────────────────────


class TestPluginManifest:
    def test_manifest_structure(self):
        m = PluginManifest()
        d = m.to_dict()
        assert d["name"] == "tribunal"
        assert "hooksConfig" in d
        assert "PreToolUse" in d["hooksConfig"]
        assert "PostToolUse" in d["hooksConfig"]
        assert "SessionStart" in d["hooksConfig"]
        assert "skillsPaths" in d
        assert "mcpServers" in d

    def test_manifest_hooks_config(self):
        m = PluginManifest()
        d = m.to_dict()
        pre = d["hooksConfig"]["PreToolUse"]
        assert len(pre) == 1
        assert "tribunal-gate" in pre[0]["run"][0]["command"]

    def test_manifest_mcp_server(self):
        m = PluginManifest()
        d = m.to_dict()
        mcp = d["mcpServers"]["tribunal"]
        assert mcp["command"] == "tribunal"
        assert mcp["args"] == ["mcp-serve"]

    def test_manifest_version_matches_package(self):
        from tribunal import __version__
        m = PluginManifest()
        assert m.version == __version__

    def test_manifest_to_json(self):
        m = PluginManifest()
        text = m.to_json()
        parsed = json.loads(text)
        assert parsed["name"] == "tribunal"

    def test_generate_manifest_returns_json(self):
        text = generate_manifest()
        parsed = json.loads(text)
        assert parsed["name"] == "tribunal"

    def test_generate_manifest_writes_file(self, tmp_path):
        out = tmp_path / "manifest.json"
        generate_manifest(out)
        assert out.exists()
        parsed = json.loads(out.read_text())
        assert parsed["name"] == "tribunal"

    def test_install_plugin_manifest(self, tmp_path):
        path = install_plugin_manifest(str(tmp_path))
        assert path.exists()
        assert path.name == "plugin.json"
        assert path.parent.name == ".tribunal"
        parsed = json.loads(path.read_text())
        assert parsed["name"] == "tribunal"


# ── MCP Server Tests ─────────────────────────────────────────────────────────


class TestMCPServer:
    def test_tools_list(self):
        assert len(TOOLS) == 6
        names = [t["name"] for t in TOOLS]
        assert "tribunal_rules_list" in names
        assert "tribunal_audit_recent" in names
        assert "tribunal_cost_report" in names
        assert "tribunal_evaluate" in names
        assert "tribunal_skills_list" in names
        assert "tribunal_status" in names

    def test_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_handle_initialize(self):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = handle_request(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "tribunal"

    def test_handle_initialized_notification(self):
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = handle_request(req)
        assert resp == {}

    def test_handle_tools_list(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = handle_request(req)
        assert resp["id"] == 2
        assert len(resp["result"]["tools"]) == 6

    def test_handle_ping(self):
        req = {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}
        resp = handle_request(req)
        assert resp["id"] == 3
        assert resp["result"] == {}

    def test_handle_unknown_method(self):
        req = {"jsonrpc": "2.0", "id": 4, "method": "foo/bar", "params": {}}
        resp = handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_handle_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        resp = handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_handle_rules_list_tool(self, tmp_path):
        # Create a rules file
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        rules_file = rules_dir / "rules.yaml"
        rules_file.write_text(
            "rules:\n  test-rule:\n    trigger: PreToolUse\n    action: block\n    "
            "condition: no-matching-test\n    message: Write tests first\n"
        )
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "tribunal_rules_list", "arguments": {"cwd": str(tmp_path)}},
        }
        resp = handle_request(req)
        assert resp["id"] == 6
        content = resp["result"]["content"]
        assert len(content) == 1
        rules = json.loads(content[0]["text"])
        assert len(rules) >= 1

    def test_handle_audit_recent_empty(self, tmp_path):
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "tribunal_audit_recent", "arguments": {"cwd": str(tmp_path)}},
        }
        resp = handle_request(req)
        entries = json.loads(resp["result"]["content"][0]["text"])
        assert entries == []

    def test_handle_audit_recent_with_data(self, tmp_path):
        audit_dir = tmp_path / ".tribunal"
        audit_dir.mkdir()
        audit_file = audit_dir / "audit.jsonl"
        entries = [
            json.dumps({"tool": "FileEdit", "allowed": True, "ts": 1}),
            json.dumps({"tool": "Bash", "allowed": False, "ts": 2}),
        ]
        audit_file.write_text("\n".join(entries) + "\n")

        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "tribunal_audit_recent", "arguments": {"cwd": str(tmp_path)}},
        }
        resp = handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert len(result) == 2

    def test_handle_evaluate_tool(self, tmp_path):
        # Set up rules so we can evaluate
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        rules_file = rules_dir / "rules.yaml"
        rules_file.write_text(
            "rules:\n  tdd:\n    trigger: PreToolUse\n    match:\n"
            "      tool: FileEdit\n      path: '*.py'\n    condition: no-matching-test\n"
            "    action: block\n    message: Tests first\n"
        )

        req = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "tribunal_evaluate",
                "arguments": {
                    "cwd": str(tmp_path),
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo hello"},
                },
            },
        }
        resp = handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert "allowed" in result

    def test_handle_status_tool(self, tmp_path):
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "tribunal_status", "arguments": {"cwd": str(tmp_path)}},
        }
        resp = handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert "hooks_active" in result
        assert "rules_count" in result
        assert "audit_total" in result

    def test_handle_skills_list_tool(self, tmp_path):
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "tribunal_skills_list", "arguments": {"cwd": str(tmp_path)}},
        }
        resp = handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        # Should return at least the bundled skills
        assert isinstance(result, list)
        assert len(result) >= 5


# ── Review Agent Tests ────────────────────────────────────────────────────────


class TestReviewFinding:
    def test_basic_finding(self):
        f = ReviewFinding(agent="tdd", severity="error", message="No test found")
        assert f.agent == "tdd"
        assert f.severity == "error"

    def test_finding_with_location(self):
        f = ReviewFinding(agent="security", severity="warning", file="src/main.py", line=42, message="eval()")
        assert f.file == "src/main.py"
        assert f.line == 42


class TestReviewReport:
    def test_empty_report_passes(self):
        r = ReviewReport()
        assert r.passed is True
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_add_warning_stays_passing(self):
        r = ReviewReport()
        r.add(ReviewFinding(agent="tdd", severity="warning", message="Consider adding tests"))
        assert r.passed is True
        assert r.warning_count == 1

    def test_add_error_fails(self):
        r = ReviewReport()
        r.add(ReviewFinding(agent="tdd", severity="error", message="No test"))
        assert r.passed is False
        assert r.error_count == 1

    def test_to_dict(self):
        r = ReviewReport()
        r.add(ReviewFinding(agent="security", severity="error", message="Secret found"))
        d = r.to_dict()
        assert d["passed"] is False
        assert d["errors"] == 1
        assert len(d["findings"]) == 1

    def test_format(self):
        r = ReviewReport()
        r.add(ReviewFinding(agent="tdd", severity="error", message="No test"))
        text = r.format()
        assert "tdd" in text
        assert "No test" in text


class TestReviewAgents:
    def test_registered_agents(self):
        assert "tdd" in AGENTS
        assert "security" in AGENTS
        assert "quality" in AGENTS
        assert "spec" in AGENTS

    def test_tdd_agent_finds_missing_tests(self, tmp_path):
        """TDD agent flags Python files without matching test files."""
        src = tmp_path / "src" / "app.py"
        src.parent.mkdir(parents=True)
        src.write_text("def main(): pass\n")

        from tribunal.review import _review_tdd

        findings = _review_tdd(str(tmp_path), ["src/app.py"])
        assert len(findings) >= 1
        assert findings[0].agent == "tdd"
        assert findings[0].severity == "error"

    def test_tdd_agent_passes_with_test(self, tmp_path):
        """TDD agent passes when test file exists."""
        src = tmp_path / "src" / "app.py"
        src.parent.mkdir(parents=True)
        src.write_text("def main(): pass\n")

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text("def test_main(): pass\n")

        from tribunal.review import _review_tdd

        findings = _review_tdd(str(tmp_path), ["src/app.py"])
        assert len(findings) == 0

    def test_tdd_agent_skips_test_files(self, tmp_path):
        """TDD agent doesn't flag test files themselves."""
        from tribunal.review import _review_tdd

        findings = _review_tdd(str(tmp_path), ["tests/test_main.py"])
        assert len(findings) == 0

    def test_tdd_agent_skips_init_files(self, tmp_path):
        """TDD agent skips __init__.py."""
        from tribunal.review import _review_tdd

        findings = _review_tdd(str(tmp_path), ["src/__init__.py"])
        assert len(findings) == 0

    def test_tdd_agent_ts_missing_test(self, tmp_path):
        """TDD agent flags TypeScript files without matching test files."""
        src = tmp_path / "src" / "app.ts"
        src.parent.mkdir(parents=True)
        src.write_text("export function main() {}\n")

        from tribunal.review import _review_tdd

        findings = _review_tdd(str(tmp_path), ["src/app.ts"])
        assert len(findings) >= 1
        assert findings[0].severity == "warning"  # TS is a warning, not error

    def test_security_agent_detects_api_key(self, tmp_path):
        """Security agent detects hardcoded API keys."""
        src = tmp_path / "config.py"
        src.write_text('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"\n')

        from tribunal.review import _review_security

        findings = _review_security(str(tmp_path), ["config.py"])
        assert any(f.agent == "security" and f.severity == "error" for f in findings)

    def test_security_agent_detects_eval(self, tmp_path):
        """Security agent flags eval() usage."""
        src = tmp_path / "handler.py"
        src.write_text("result = eval(user_input)\n")

        from tribunal.review import _review_security

        findings = _review_security(str(tmp_path), ["handler.py"])
        assert any(f.rule == "unsafe-code" for f in findings)

    def test_security_agent_clean_file(self, tmp_path):
        """Security agent passes for clean files."""
        src = tmp_path / "clean.py"
        src.write_text("def greet(name):\n    return f'Hello {name}'\n")

        from tribunal.review import _review_security

        findings = _review_security(str(tmp_path), ["clean.py"])
        assert len(findings) == 0

    def test_spec_agent_marks_todo(self, tmp_path):
        """Spec agent finds TODO markers."""
        src = tmp_path / "main.py"
        src.write_text("def main():\n    # TODO: implement this\n    pass\n")

        from tribunal.review import _review_spec

        findings = _review_spec(str(tmp_path), ["main.py"])
        assert any(f.rule == "unresolved-marker" for f in findings)

    def test_spec_agent_no_spec_recommendation(self, tmp_path):
        """Spec agent recommends spec for large changes."""
        from tribunal.review import _review_spec

        files = [f"src/module{i}.py" for i in range(10)]
        findings = _review_spec(str(tmp_path), files)
        assert any(f.rule == "spec-recommended" for f in findings)


class TestRunReview:
    def test_no_files(self, tmp_path):
        report = run_review(cwd=str(tmp_path), files=[])
        assert report.passed is True
        assert "No changed files" in report.summary

    def test_specific_agents(self, tmp_path):
        src = tmp_path / "main.py"
        src.write_text("def main(): pass\n")

        report = run_review(cwd=str(tmp_path), agents=["security"], files=["main.py"])
        # Security agent should pass for clean file
        assert report.passed is True

    def test_review_with_findings(self, tmp_path):
        src = tmp_path / "src" / "app.py"
        src.parent.mkdir(parents=True)
        src.write_text("def main(): pass\n")

        report = run_review(cwd=str(tmp_path), agents=["tdd"], files=["src/app.py"])
        assert report.passed is False
        assert report.error_count >= 1

    def test_review_summary(self, tmp_path):
        src = tmp_path / "clean.py"
        src.write_text("def greet(): return 'hello'\n")

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_clean.py").write_text("def test_greet(): pass\n")

        report = run_review(cwd=str(tmp_path), agents=["tdd", "security"], files=["clean.py"])
        assert "agents passed" in report.summary


# ── Config Cascade Tests ─────────────────────────────────────────────────────


class TestTribunalConfig:
    def test_defaults(self):
        config = TribunalConfig()
        assert config.audit_enabled is True
        assert config.budget_session_usd == 0.0
        assert config.mcp_enabled is False

    def test_resolve_defaults(self, tmp_path):
        """Resolve config with no files — gets defaults."""
        config = resolve_config(str(tmp_path))
        assert config.audit_enabled is True
        assert "tdd_enforcement" in config.features
        assert config.features["tdd_enforcement"] is True

    def test_resolve_project_config(self, tmp_path):
        """Project config overrides defaults."""
        cfg_dir = tmp_path / ".tribunal"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.yaml"
        cfg_file.write_text(
            "budget:\n  session_usd: 5.0\n  daily_usd: 20.0\n"
            "mcp_enabled: true\n"
            "features:\n  mcp_server: true\n"
        )
        config = resolve_config(str(tmp_path))
        assert config.budget_session_usd == 5.0
        assert config.budget_daily_usd == 20.0
        assert config.mcp_enabled is True
        assert config.features["mcp_server"] is True

    def test_resolve_env_overrides(self, tmp_path):
        """Environment variables override everything."""
        with patch.dict(os.environ, {
            "TRIBUNAL_BUDGET_SESSION": "10.0",
            "TRIBUNAL_MCP_ENABLED": "1",
        }):
            config = resolve_config(str(tmp_path))
            assert config.budget_session_usd == 10.0
            assert config.mcp_enabled is True

    def test_resolve_audit_disabled_env(self, tmp_path):
        with patch.dict(os.environ, {"TRIBUNAL_AUDIT_DISABLED": "1"}):
            config = resolve_config(str(tmp_path))
            assert config.audit_enabled is False

    def test_resolve_user_config(self, tmp_path):
        """User config (~/.tribunal/config.yaml) is applied."""
        user_home = tmp_path / "home"
        user_home.mkdir()
        user_tribunal = user_home / ".tribunal"
        user_tribunal.mkdir()
        (user_tribunal / "config.yaml").write_text(
            "budget:\n  session_usd: 3.0\npermission_preset: strict\n"
        )
        with patch("tribunal.config.Path.home", return_value=user_home):
            config = resolve_config(str(tmp_path))
            assert config.budget_session_usd == 3.0
            assert config.permission_preset == "strict"

    def test_project_overrides_user(self, tmp_path):
        """Project config wins over user config."""
        user_home = tmp_path / "home"
        user_home.mkdir()
        user_tribunal = user_home / ".tribunal"
        user_tribunal.mkdir()
        (user_tribunal / "config.yaml").write_text(
            "budget:\n  session_usd: 3.0\n"
        )

        cfg_dir = tmp_path / "project" / ".tribunal"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.yaml").write_text(
            "budget:\n  session_usd: 8.0\n"
        )

        with patch("tribunal.config.Path.home", return_value=user_home):
            config = resolve_config(str(tmp_path / "project"))
            assert config.budget_session_usd == 8.0

    def test_rules_file_detected(self, tmp_path):
        """Config detects .tribunal/rules.yaml if it exists."""
        cfg_dir = tmp_path / ".tribunal"
        cfg_dir.mkdir()
        rules = cfg_dir / "rules.yaml"
        rules.write_text("rules: {}\n")
        config = resolve_config(str(tmp_path))
        assert config.rules_file == str(rules)

    def test_review_agents_config(self, tmp_path):
        """Review agents can be configured."""
        cfg_dir = tmp_path / ".tribunal"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "review_agents:\n  - tdd\n  - security\n"
        )
        config = resolve_config(str(tmp_path))
        assert config.review_agents == ["tdd", "security"]


class TestFeatureFlags:
    def test_default_features(self, tmp_path):
        assert is_feature_enabled("tdd_enforcement", str(tmp_path)) is True
        assert is_feature_enabled("secret_scanning", str(tmp_path)) is True
        assert is_feature_enabled("mcp_server", str(tmp_path)) is False

    def test_unknown_feature(self, tmp_path):
        assert is_feature_enabled("nonexistent", str(tmp_path)) is False

    def test_feature_override(self, tmp_path):
        cfg_dir = tmp_path / ".tribunal"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "features:\n  mcp_server: true\n  tdd_enforcement: false\n"
        )
        assert is_feature_enabled("mcp_server", str(tmp_path)) is True
        assert is_feature_enabled("tdd_enforcement", str(tmp_path)) is False


class TestFormatConfig:
    def test_format_output(self):
        config = TribunalConfig(
            budget_session_usd=5.0,
            budget_daily_usd=20.0,
            audit_enabled=True,
            mcp_enabled=False,
            skills_dirs=[".tribunal/skills/"],
            review_agents=["tdd", "security"],
            features={"tdd_enforcement": True, "mcp_server": False},
        )
        text = format_config(config)
        assert "$5.00" in text
        assert "$20.00" in text
        assert "enabled" in text
        assert "tdd" in text

    def test_format_unlimited_budget(self):
        config = TribunalConfig()
        text = format_config(config)
        assert "unlimited" in text


# ── CLI Integration Tests ────────────────────────────────────────────────────


class TestCLIPhase3:
    def test_plugin_show(self, tmp_path, capsys):
        """tribunal plugin show should output JSON manifest."""
        from tribunal.cli import cmd_plugin

        class Args:
            plugin_command = "show"

        result = cmd_plugin(Args())
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["name"] == "tribunal"
        assert result == 0

    def test_plugin_install(self, tmp_path, capsys, monkeypatch):
        """tribunal plugin install creates manifest file."""
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_plugin

        class Args:
            plugin_command = "install"

        result = cmd_plugin(Args())
        assert result == 0
        manifest_path = tmp_path / ".tribunal" / "plugin.json"
        assert manifest_path.exists()

    def test_config_show(self, tmp_path, capsys, monkeypatch):
        """tribunal config shows resolved configuration."""
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_config

        class Args:
            pass

        result = cmd_config(Args())
        captured = capsys.readouterr()
        assert "Tribunal Configuration" in captured.out
        assert result == 0

    def test_review_no_files(self, tmp_path, capsys, monkeypatch):
        """tribunal review with no changed files."""
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_review

        class Args:
            agents = None
            json_output = False
            files = []

        result = cmd_review(Args())
        captured = capsys.readouterr()
        assert "Tribunal Review Report" in captured.out
        assert result == 0

    def test_review_with_files(self, tmp_path, capsys, monkeypatch):
        """tribunal review with explicit files."""
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "clean.py"
        src.write_text("def greet(): return 'hello'\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_clean.py").write_text("def test_greet(): pass\n")

        from tribunal.cli import cmd_review

        class Args:
            agents = "tdd,security"
            json_output = False
            files = ["clean.py"]

        result = cmd_review(Args())
        assert result == 0

    def test_review_json_output(self, tmp_path, capsys, monkeypatch):
        """tribunal review --json outputs JSON after the formatted report."""
        monkeypatch.chdir(tmp_path)

        from tribunal.cli import cmd_review

        class Args:
            agents = "security"
            json_output = True
            files = []

        result = cmd_review(Args())
        captured = capsys.readouterr()
        # The output has formatted report THEN JSON; extract the JSON part
        lines = captured.out.strip().split("\n")
        # Find the JSON object by looking for the line starting with {
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start = i
                break
        assert json_start is not None
        json_text = "\n".join(lines[json_start:])
        parsed = json.loads(json_text)
        assert "passed" in parsed

    def test_report(self, tmp_path, capsys, monkeypatch):
        """tribunal report generates a report."""
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_report

        class Args:
            format = "text"

        result = cmd_report(Args())
        captured = capsys.readouterr()
        assert "Tribunal" in captured.out
        assert result == 0

    def test_report_json(self, tmp_path, capsys, monkeypatch):
        """tribunal report --format json outputs valid JSON."""
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_report

        class Args:
            format = "json"

        result = cmd_report(Args())
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "passed" in parsed
