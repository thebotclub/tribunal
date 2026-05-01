"""Tests for the Tribunal package."""

import json
from unittest.mock import patch


from tribunal.protocol import HookEvent, HookVerdict, read_hook_event
from tribunal.rules import Rule, RuleEngine, RuleMatch, _extract_path
from tribunal.audit import log_event


# ── Protocol Tests ────────────────────────────────────────────────────────────


class TestHookEvent:
    def test_basic_fields(self):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp/test",
            tool_name="FileEdit",
            tool_input={"file_path": "/tmp/test/foo.py"},
        )
        assert event.hook_event_name == "PreToolUse"
        assert event.session_id == "s1"
        assert event.tool_name == "FileEdit"

    def test_defaults(self):
        event = HookEvent(hook_event_name="SessionStart", session_id="s1", cwd="/tmp")
        assert event.tool_name is None
        assert event.tool_input == {}
        assert event.tool_response == {}
        assert event.error is None


class TestHookVerdict:
    def test_allow_exit_code(self):
        v = HookVerdict(allow=True)
        assert v.exit_code == 0

    def test_block_exit_code(self):
        v = HookVerdict(allow=False, reason="Blocked")
        assert v.exit_code == 2

    def test_block_with_reason(self):
        v = HookVerdict(allow=False, reason="No tests found")
        assert not v.allow
        assert "No tests found" in v.reason


class TestReadHookEvent:
    def test_parse_pretooluse(self):
        data = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "abc",
                "cwd": "/project",
                "tool_name": "FileEdit",
                "tool_input": {"file_path": "/project/main.py", "content": "x = 1"},
            }
        )
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = data
            event = read_hook_event()
        assert event.hook_event_name == "PreToolUse"
        assert event.tool_name == "FileEdit"
        assert event.tool_input["file_path"] == "/project/main.py"

    def test_empty_stdin(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            event = read_hook_event()
        assert event.hook_event_name == "Unknown"


# ── Rule Matching Tests ───────────────────────────────────────────────────────


class TestRuleMatch:
    def test_tool_matches(self):
        m = RuleMatch(tool="FileEdit|FileWrite")
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={},
        )
        assert m.matches(event)

    def test_tool_no_match(self):
        m = RuleMatch(tool="FileEdit|FileWrite")
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="Bash",
            tool_input={},
        )
        assert not m.matches(event)

    def test_path_matches_glob(self):
        m = RuleMatch(tool="FileEdit", path="*.py")
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"file_path": "main.py"},
        )
        assert m.matches(event)

    def test_path_no_match(self):
        m = RuleMatch(tool="FileEdit", path="*.py")
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"file_path": "main.ts"},
        )
        assert not m.matches(event)

    def test_no_constraints_matches_all(self):
        m = RuleMatch()
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="Bash",
            tool_input={},
        )
        assert m.matches(event)


# ── Extract Path Tests ────────────────────────────────────────────────────────


class TestExtractPath:
    def test_file_path_key(self):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"file_path": "/tmp/foo.py"},
        )
        assert _extract_path(event) == "/tmp/foo.py"

    def test_path_key(self):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"path": "/tmp/bar.py"},
        )
        assert _extract_path(event) == "/tmp/bar.py"

    def test_no_path(self):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
        )
        assert _extract_path(event) is None


# ── Rule Engine Tests ─────────────────────────────────────────────────────────


class TestRuleEngine:
    def test_from_yaml(self, tmp_path):
        rules_yaml = tmp_path / ".tribunal" / "rules.yaml"
        rules_yaml.parent.mkdir()
        rules_yaml.write_text("""
rules:
  test-rule:
    trigger: PreToolUse
    match:
      tool: FileEdit
    action: block
    message: "Blocked by test rule"
""")
        engine = RuleEngine.from_config(rules_yaml)
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "test-rule"
        assert engine.rules[0].action == "block"

    def test_evaluate_blocking_rule(self, tmp_path):
        rules_yaml = tmp_path / ".tribunal" / "rules.yaml"
        rules_yaml.parent.mkdir()
        rules_yaml.write_text("""
rules:
  always-block:
    trigger: PreToolUse
    match:
      tool: FileEdit
    action: block
    message: "Always blocked"
""")
        engine = RuleEngine.from_config(rules_yaml)
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": "test.txt"},
        )
        verdict = engine.evaluate(event)
        assert not verdict.allow
        assert "Always blocked" in verdict.reason

    def test_evaluate_warn_rule_allows(self, tmp_path):
        rules_yaml = tmp_path / ".tribunal" / "rules.yaml"
        rules_yaml.parent.mkdir()
        rules_yaml.write_text("""
rules:
  just-warn:
    trigger: PreToolUse
    match:
      tool: Bash
    action: warn
    message: "Be careful"
""")
        engine = RuleEngine.from_config(rules_yaml)
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow
        assert "Be careful" in verdict.additional_context

    def test_evaluate_no_matching_rules_allows(self):
        engine = RuleEngine(
            [
                Rule(
                    name="py-only",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit", path="*.py"),
                    action="block",
                    message="Blocked",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"file_path": "main.ts"},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_wrong_trigger_skips(self):
        engine = RuleEngine(
            [
                Rule(
                    name="post-only",
                    trigger="PostToolUse",
                    match=RuleMatch(tool="FileEdit"),
                    action="block",
                    message="Blocked",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_disabled_rule_skipped(self):
        engine = RuleEngine(
            [
                Rule(
                    name="disabled",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit"),
                    action="block",
                    message="Blocked",
                    enabled=False,
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_empty_rules_allows_everything(self):
        engine = RuleEngine([])
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow


# ── TDD Condition Tests ───────────────────────────────────────────────────────


class TestTDDCondition:
    def test_blocks_py_without_test(self, tmp_path):
        engine = RuleEngine(
            [
                Rule(
                    name="tdd",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit", path="*.py"),
                    action="block",
                    condition="no-matching-test",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "app.py")},
        )
        verdict = engine.evaluate(event)
        assert not verdict.allow
        assert "test" in verdict.reason.lower()

    def test_allows_py_with_test(self, tmp_path):
        # Create the test file
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text("def test_pass(): pass")

        engine = RuleEngine(
            [
                Rule(
                    name="tdd",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit", path="*.py"),
                    action="block",
                    condition="no-matching-test",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "app.py")},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_allows_test_files_themselves(self, tmp_path):
        engine = RuleEngine(
            [
                Rule(
                    name="tdd",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit", path="*.py"),
                    action="block",
                    condition="no-matching-test",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "tests" / "test_app.py")},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_allows_init_py(self, tmp_path):
        engine = RuleEngine(
            [
                Rule(
                    name="tdd",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit", path="*.py"),
                    action="block",
                    condition="no-matching-test",
                ),
            ]
        )
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "__init__.py")},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow


# ── Secret Detection Tests ────────────────────────────────────────────────────


class TestSecretCondition:
    def _make_event(self, content: str) -> HookEvent:
        return HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd="/tmp",
            tool_name="FileEdit",
            tool_input={"file_path": "/tmp/config.py", "content": content},
        )

    def _engine(self):
        return RuleEngine(
            [
                Rule(
                    name="secrets",
                    trigger="PreToolUse",
                    match=RuleMatch(tool="FileEdit"),
                    action="block",
                    condition="contains-secret",
                ),
            ]
        )

    def test_blocks_api_key(self):
        verdict = self._engine().evaluate(
            self._make_event('api_key = "sk-proj-abc1234567890123456789"')
        )
        assert not verdict.allow

    def test_blocks_private_key(self):
        verdict = self._engine().evaluate(
            self._make_event("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        )
        assert not verdict.allow

    def test_blocks_github_token(self):
        verdict = self._engine().evaluate(
            self._make_event('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678"')
        )
        assert not verdict.allow

    def test_allows_safe_content(self):
        verdict = self._engine().evaluate(
            self._make_event('name = "hello world"\ncount = 42')
        )
        assert verdict.allow

    def test_allows_env_var_reference(self):
        verdict = self._engine().evaluate(
            self._make_event('api_key = os.environ["API_KEY"]')
        )
        assert verdict.allow


# ── Audit Log Tests ───────────────────────────────────────────────────────────


class TestAuditLog:
    def test_log_event_creates_jsonl(self, tmp_path):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "app.py")},
        )
        (tmp_path / ".tribunal").mkdir()
        log_event(event, verdict_allow=True, rule_name="")

        audit_path = tmp_path / ".tribunal" / "audit.jsonl"
        assert audit_path.exists()
        entry = json.loads(audit_path.read_text().strip())
        assert entry["hook"] == "PreToolUse"
        assert entry["tool"] == "FileEdit"
        assert entry["allowed"] is True

    def test_log_blocked_event(self, tmp_path):
        event = HookEvent(
            hook_event_name="PreToolUse",
            session_id="s1",
            cwd=str(tmp_path),
            tool_name="FileEdit",
            tool_input={"file_path": str(tmp_path / "app.py")},
        )
        (tmp_path / ".tribunal").mkdir()
        log_event(event, verdict_allow=False, rule_name="tdd-python")

        audit_path = tmp_path / ".tribunal" / "audit.jsonl"
        entry = json.loads(audit_path.read_text().strip())
        assert entry["allowed"] is False
        assert entry["rule"] == "tdd-python"


# ── CLI Init Tests ────────────────────────────────────────────────────────────


class TestCLIInit:
    def test_init_creates_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_init
        import argparse

        args = argparse.Namespace(force=False)
        result = cmd_init(args)
        assert result == 0
        assert (tmp_path / ".tribunal" / "rules.yaml").exists()
        assert (tmp_path / ".claude" / "claudeconfig.json").exists()

    def test_init_config_has_hooks(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_init
        import argparse

        args = argparse.Namespace(force=False)
        cmd_init(args)

        config = json.loads((tmp_path / ".claude" / "claudeconfig.json").read_text())
        assert "hooks" in config
        assert "PreToolUse" in config["hooks"]
        assert "PostToolUse" in config["hooks"]

    def test_init_merges_existing_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        existing = {"permissions": {"allow": ["Read"]}, "hooks": {}}
        (claude_dir / "claudeconfig.json").write_text(json.dumps(existing))

        from tribunal.cli import cmd_init
        import argparse

        args = argparse.Namespace(force=False)
        cmd_init(args)

        config = json.loads((claude_dir / "claudeconfig.json").read_text())
        assert "permissions" in config  # preserved
        assert "PreToolUse" in config["hooks"]  # added

    def test_init_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_init
        import argparse

        args = argparse.Namespace(force=False)
        cmd_init(args)
        cmd_init(args)  # second call should not error
        config = json.loads((tmp_path / ".claude" / "claudeconfig.json").read_text())
        # Should not duplicate hooks
        assert len(config["hooks"]["PreToolUse"]) == 1
