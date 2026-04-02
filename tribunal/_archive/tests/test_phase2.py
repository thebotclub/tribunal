"""Tests for Phase 2 features: cost tracking, skills, permissions, run conditions."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tribunal.cost import (
    CostBudget,
    CostSnapshot,
    check_budget,
    format_cost_report,
    get_budget,
    get_cost_snapshot,
    load_state,
    save_state,
    set_budget,
    update_session_cost,
)
from tribunal.permissions import (
    PermissionPolicy,
    PermissionRule,
    apply_policy,
    format_policy,
    get_preset,
    list_presets,
)
from tribunal.protocol import HookEvent
from tribunal.rules import Rule, RuleEngine, RuleMatch
from tribunal.skills import (
    Skill,
    create_skill_scaffold,
    format_skill_list,
    install_skill,
    list_all_skills,
    load_bundled_skills,
    load_skills_dir,
    parse_skill,
)


# ── Cost Module Tests ─────────────────────────────────────────────────────────


class TestCostState:
    def test_save_and_load_state(self, tmp_path):
        save_state(str(tmp_path), {"session_cost_usd": 1.50, "model": "opus"})
        state = load_state(str(tmp_path))
        assert state["session_cost_usd"] == 1.50
        assert state["model"] == "opus"

    def test_load_missing_state(self, tmp_path):
        state = load_state(str(tmp_path))
        assert state == {}

    def test_get_cost_snapshot(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 2.50,
            "input_tokens": 1000,
            "output_tokens": 500,
            "model": "sonnet",
        })
        snap = get_cost_snapshot(str(tmp_path))
        assert snap.session_cost_usd == 2.50
        assert snap.input_tokens == 1000
        assert snap.model == "sonnet"

    def test_set_budget_session(self, tmp_path):
        set_budget(str(tmp_path), session_usd=5.00)
        budget = get_budget(str(tmp_path))
        assert budget.session_usd == 5.00
        # Also check the legacy field
        state = load_state(str(tmp_path))
        assert state["cost_budget_usd"] == 5.00

    def test_set_budget_daily(self, tmp_path):
        set_budget(str(tmp_path), daily_usd=20.00)
        budget = get_budget(str(tmp_path))
        assert budget.daily_usd == 20.00

    def test_update_session_cost(self, tmp_path):
        update_session_cost(str(tmp_path), 0.50, session_id="s1", model="haiku")
        snap = get_cost_snapshot(str(tmp_path))
        assert snap.session_cost_usd == 0.50
        assert snap.session_id == "s1"


class TestCostBudgetCheck:
    def test_under_budget(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 1.00,
            "budget": {"session_usd": 5.00, "warn_at_percent": 80.0},
        })
        result = check_budget(str(tmp_path))
        assert not result.exceeded
        assert not result.warning

    def test_over_budget(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 6.00,
            "budget": {"session_usd": 5.00},
        })
        result = check_budget(str(tmp_path))
        assert result.exceeded
        assert "$6.00" in result.message

    def test_warning_threshold(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 4.50,
            "budget": {"session_usd": 5.00, "warn_at_percent": 80.0},
        })
        result = check_budget(str(tmp_path))
        assert result.warning
        assert not result.exceeded
        assert "90%" in result.message

    def test_no_budget_set(self, tmp_path):
        save_state(str(tmp_path), {"session_cost_usd": 100.0})
        result = check_budget(str(tmp_path))
        assert not result.exceeded
        assert not result.warning

    def test_daily_budget_exceeded(self, tmp_path):
        save_state(str(tmp_path), {
            "daily_cost_usd": 25.0,
            "budget": {"daily_usd": 20.0},
        })
        result = check_budget(str(tmp_path))
        assert result.exceeded
        assert "Daily" in result.message


class TestCostReport:
    def test_format_with_data(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 1.50,
            "model": "sonnet",
            "input_tokens": 5000,
            "output_tokens": 2000,
            "budget": {"session_usd": 5.00},
        })
        report = format_cost_report(str(tmp_path))
        assert "$1.50" in report
        assert "sonnet" in report
        assert "5,000" in report

    def test_format_no_data(self, tmp_path):
        report = format_cost_report(str(tmp_path))
        assert "no cost data" in report


# ── Cost Condition in Rules ───────────────────────────────────────────────────


class TestCostConditionV2:
    def test_cost_exceeded_blocks(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 6.00,
            "budget": {"session_usd": 5.00},
        })
        engine = RuleEngine([
            Rule(name="budget", trigger="PostToolUse",
                 match=RuleMatch(), action="block", condition="cost-exceeded"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={},
        )
        verdict = engine.evaluate(event)
        assert not verdict.allow

    def test_cost_under_budget_allows(self, tmp_path):
        save_state(str(tmp_path), {
            "session_cost_usd": 1.00,
            "budget": {"session_usd": 5.00, "warn_at_percent": 80.0},
        })
        engine = RuleEngine([
            Rule(name="budget", trigger="PostToolUse",
                 match=RuleMatch(), action="block", condition="cost-exceeded"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow


# ── Run Command Condition Tests ───────────────────────────────────────────────


class TestRunCommandCondition:
    def test_run_passing_command(self, tmp_path):
        engine = RuleEngine([
            Rule(name="check", trigger="PostToolUse",
                 match=RuleMatch(tool="FileEdit"),
                 action="block", run="true"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={"file_path": "test.py"},
        )
        verdict = engine.evaluate(event)
        assert verdict.allow

    def test_run_failing_command(self, tmp_path):
        engine = RuleEngine([
            Rule(name="check", trigger="PostToolUse",
                 match=RuleMatch(tool="FileEdit"),
                 action="block", run="false"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={"file_path": "test.py"},
        )
        verdict = engine.evaluate(event)
        assert not verdict.allow
        assert "Command failed" in verdict.reason

    def test_run_missing_command_graceful(self, tmp_path):
        engine = RuleEngine([
            Rule(name="check", trigger="PostToolUse",
                 match=RuleMatch(tool="FileEdit"),
                 action="block", run="nonexistent_command_xyz_123"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={"file_path": "test.py"},
        )
        verdict = engine.evaluate(event)
        # Should allow when command not found (graceful degradation)
        assert verdict.allow

    def test_run_with_output(self, tmp_path):
        engine = RuleEngine([
            Rule(name="check", trigger="PostToolUse",
                 match=RuleMatch(tool="FileEdit"),
                 action="block", run="echo 'error: bad code' && exit 1"),
        ])
        event = HookEvent(
            hook_event_name="PostToolUse", session_id="s1", cwd=str(tmp_path),
            tool_name="FileEdit", tool_input={"file_path": "test.py"},
        )
        verdict = engine.evaluate(event)
        assert not verdict.allow
        assert "bad code" in verdict.reason


# ── Skills Module Tests ───────────────────────────────────────────────────────


class TestSkillParsing:
    def test_parse_with_frontmatter(self):
        text = """---
name: test-skill
description: A test skill
tags:
  - testing
trigger: manual
---

# Test Skill

This is the body.
"""
        skill = parse_skill(text)
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert "testing" in skill.tags
        assert skill.trigger == "manual"
        assert "This is the body" in skill.content

    def test_parse_without_frontmatter(self):
        text = "# Just Markdown\n\nNo frontmatter here."
        skill = parse_skill(text, path="/skills/simple.md")
        assert skill.name == "simple"
        assert skill.content == text.strip()

    def test_parse_empty_frontmatter(self):
        text = "---\n---\n\nBody content."
        skill = parse_skill(text, path="/skills/empty.md")
        assert skill.name == "empty"
        assert "Body content" in skill.content


class TestSkillsDirectory:
    def test_load_skills_dir(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "one.md").write_text("---\nname: one\n---\n# One")
        (skills_dir / "two.md").write_text("---\nname: two\n---\n# Two")

        skills = load_skills_dir(skills_dir)
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert "one" in names
        assert "two" in names

    def test_load_empty_dir(self, tmp_path):
        skills = load_skills_dir(tmp_path / "nonexistent")
        assert skills == []

    def test_load_bundled_skills(self):
        bundled = load_bundled_skills()
        assert len(bundled) >= 4  # We created 5 bundled skills
        names = {s.name for s in bundled}
        assert "tdd-cycle" in names
        assert "security-audit" in names
        assert "quality-gate" in names
        for s in bundled:
            assert s.bundled is True


class TestSkillInstall:
    def test_install_skill(self, tmp_path):
        skill = Skill(
            name="my-skill",
            description="Custom skill",
            tags=["custom"],
            trigger="auto",
            content="# My Skill\n\nDo the thing.",
        )
        dest = install_skill(skill, str(tmp_path))
        assert dest.exists()
        text = dest.read_text()
        assert "my-skill" in text
        assert "Do the thing" in text

    def test_create_scaffold(self, tmp_path):
        dest = create_skill_scaffold("review-check", str(tmp_path))
        assert dest.exists()
        text = dest.read_text()
        assert "review-check" in text

    def test_list_all_merges(self, tmp_path):
        # Install a project skill that overrides a bundled one
        skills_dir = tmp_path / ".tribunal" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "tdd-cycle.md").write_text(
            "---\nname: tdd-cycle\ndescription: Custom TDD\n---\n# Custom"
        )
        all_skills = list_all_skills(str(tmp_path))
        tdd = [s for s in all_skills if s.name == "tdd-cycle"]
        assert len(tdd) == 1
        assert tdd[0].description == "Custom TDD"  # project overrides bundled

    def test_format_skill_list(self):
        skills = [
            Skill(name="a", description="Skill A", bundled=True),
            Skill(name="b", description="Skill B", bundled=False),
        ]
        output = format_skill_list(skills)
        assert "📦" in output  # bundled
        assert "📝" in output  # project
        assert "Skill A" in output


# ── Permissions Module Tests ──────────────────────────────────────────────────


class TestPermissions:
    def test_presets_exist(self):
        presets = list_presets()
        assert "strict" in presets
        assert "standard" in presets
        assert "minimal" in presets

    def test_get_strict_preset(self):
        policy = get_preset("strict")
        assert policy is not None
        assert len(policy.deny) > 0
        # Strict should deny sudo
        deny_patterns = [r.pattern for r in policy.deny]
        assert any("sudo" in p for p in deny_patterns)

    def test_policy_to_config(self):
        policy = PermissionPolicy(
            deny=[PermissionRule("Bash", "sudo *")],
            allow=[PermissionRule("Read", "**")],
        )
        config = policy.to_config()
        assert len(config["deny"]) == 1
        assert config["deny"][0]["tool"] == "Bash"
        assert len(config["allow"]) == 1

    def test_apply_policy_new_file(self, tmp_path):
        policy = get_preset("minimal")
        apply_policy(tmp_path, policy)
        config_path = tmp_path / ".claude" / "claudeconfig.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "permissions" in config
        assert "deny" in config["permissions"]

    def test_apply_policy_merge(self, tmp_path):
        # Create existing config
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        existing = {
            "hooks": {},
            "permissions": {
                "deny": [{"tool": "Bash", "pattern": "rm -rf /*"}],
            },
        }
        (claude_dir / "claudeconfig.json").write_text(json.dumps(existing))

        # Apply minimal preset (which also has rm -rf /*)
        policy = get_preset("minimal")
        apply_policy(tmp_path, policy, merge=True)

        config = json.loads((claude_dir / "claudeconfig.json").read_text())
        # Should not duplicate the rm -rf rule
        deny = config["permissions"]["deny"]
        rm_rules = [r for r in deny if "rm -rf" in r["pattern"]]
        assert len(rm_rules) == 1  # No duplicates

    def test_format_policy(self):
        policy = PermissionPolicy(
            deny=[PermissionRule("Bash", "sudo *", "No sudo")],
            allow=[PermissionRule("Read", "**", "Read everything")],
        )
        output = format_policy(policy)
        assert "⛔" in output
        assert "sudo" in output
        assert "✓" in output

    def test_unknown_preset_returns_none(self):
        policy = get_preset("nonexistent")
        assert policy is None


# ── CLI Integration Tests ─────────────────────────────────────────────────────


class TestCLICost:
    def test_cost_report_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cost import save_state
        save_state(str(tmp_path), {"session_cost_usd": 1.23})
        from tribunal.cli import cmd_cost
        import argparse
        args = argparse.Namespace(cost_command="report")
        result = cmd_cost(args)
        assert result == 0

    def test_cost_budget_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_cost
        import argparse
        args = argparse.Namespace(cost_command="budget", amount=5.00, daily=False)
        result = cmd_cost(args)
        assert result == 0
        budget = get_budget(str(tmp_path))
        assert budget.session_usd == 5.00


class TestCLISkills:
    def test_skills_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_skills
        import argparse
        args = argparse.Namespace(skills_command="list")
        result = cmd_skills(args)
        assert result == 0

    def test_skills_install_bundled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_skills
        import argparse
        args = argparse.Namespace(skills_command="install", name="tdd-cycle")
        result = cmd_skills(args)
        assert result == 0
        assert (tmp_path / ".tribunal" / "skills" / "tdd-cycle.md").exists()

    def test_skills_create(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_skills
        import argparse
        args = argparse.Namespace(skills_command="create", name="my-workflow")
        result = cmd_skills(args)
        assert result == 0
        assert (tmp_path / ".tribunal" / "skills" / "my-workflow.md").exists()


class TestCLIPermissions:
    def test_permissions_show(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_permissions
        import argparse
        args = argparse.Namespace(perm_command="show")
        result = cmd_permissions(args)
        assert result == 0

    def test_permissions_apply_strict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_permissions
        import argparse
        args = argparse.Namespace(perm_command="apply", preset="strict")
        result = cmd_permissions(args)
        assert result == 0
        config_path = tmp_path / ".claude" / "claudeconfig.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "permissions" in config

    def test_permissions_apply_unknown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_permissions
        import argparse
        args = argparse.Namespace(perm_command="apply", preset="unknown_preset")
        result = cmd_permissions(args)
        assert result == 1


# ── Enhanced Rule Engine Tests ────────────────────────────────────────────────


class TestRuleEngineV2:
    def test_load_rules_with_run(self, tmp_path):
        rules_yaml = tmp_path / ".tribunal" / "rules.yaml"
        rules_yaml.parent.mkdir()
        rules_yaml.write_text("""
rules:
  type-check:
    trigger: PostToolUse
    match:
      tool: FileEdit
      path: "**/*.ts"
    run: "npx tsc --noEmit"
    action: block
    message: "TypeScript errors found"
""")
        engine = RuleEngine.from_config(rules_yaml)
        assert len(engine.rules) == 1
        assert engine.rules[0].run == "npx tsc --noEmit"

    def test_load_rules_with_new_conditions(self, tmp_path):
        rules_yaml = tmp_path / ".tribunal" / "rules.yaml"
        rules_yaml.parent.mkdir()
        rules_yaml.write_text("""
rules:
  lint:
    trigger: PostToolUse
    match:
      tool: FileEdit
    condition: lint-check
    action: warn
    message: "Lint errors"
  types:
    trigger: PostToolUse
    match:
      tool: FileEdit
      path: "**/*.ts"
    condition: type-check
    action: warn
    message: "Type errors"
  mypy:
    trigger: PostToolUse
    match:
      tool: FileEdit
      path: "**/*.py"
    condition: mypy-check
    action: warn
    message: "mypy errors"
""")
        engine = RuleEngine.from_config(rules_yaml)
        assert len(engine.rules) == 3
        conditions = {r.condition for r in engine.rules}
        assert "lint-check" in conditions
        assert "type-check" in conditions
        assert "mypy-check" in conditions
