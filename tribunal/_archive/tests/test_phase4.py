"""Tests for Phase 4 features: team sync, managed settings, model routing, marketplace."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from tribunal.managed import (
    ManagedPolicy,
    apply_managed_policy,
    format_managed_status,
    generate_managed_config,
    load_managed_policy,
)
from tribunal.marketplace import (
    MarketplaceEntry,
    format_marketplace,
    install_from_marketplace,
    list_marketplace,
    register_bundle,
    unregister_bundle,
)
from tribunal.routing import (
    ModelConfig,
    ModelRoute,
    format_model_config,
    load_model_config,
)
from tribunal.sync import (
    RuleBundle,
    export_rules,
    export_to_file,
    import_from_file,
    import_rules,
    validate_bundle,
)


# ── Team Rules Sync Tests ────────────────────────────────────────────────────


class TestRuleBundle:
    def test_bundle_to_dict(self):
        b = RuleBundle(name="test-bundle", version="1.0", rules={"rule1": {"trigger": "PreToolUse", "action": "block"}})
        d = b.to_dict()
        assert d["tribunal_bundle"] == "1.0"
        assert d["name"] == "test-bundle"
        assert "rule1" in d["rules"]

    def test_bundle_to_yaml(self):
        b = RuleBundle(name="test", version="1.0")
        text = b.to_yaml()
        parsed = yaml.safe_load(text)
        assert parsed["name"] == "test"

    def test_empty_bundle(self):
        b = RuleBundle(name="empty", version="1.0")
        d = b.to_dict()
        assert "rules" not in d  # empty rules not included


class TestValidateBundle:
    def test_valid_bundle(self):
        data = {
            "tribunal_bundle": "1.0",
            "name": "valid",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }
        errors = validate_bundle(data)
        assert errors == []

    def test_missing_version(self):
        data = {"name": "test"}
        errors = validate_bundle(data)
        assert any("tribunal_bundle" in e for e in errors)

    def test_missing_name(self):
        data = {"tribunal_bundle": "1.0"}
        errors = validate_bundle(data)
        assert any("name" in e for e in errors)

    def test_invalid_rules(self):
        data = {"tribunal_bundle": "1.0", "name": "test", "rules": "not a dict"}
        errors = validate_bundle(data)
        assert any("mapping" in e for e in errors)

    def test_rule_missing_trigger(self):
        data = {
            "tribunal_bundle": "1.0",
            "name": "test",
            "rules": {"r1": {"action": "block"}},
        }
        errors = validate_bundle(data)
        assert any("trigger" in e for e in errors)

    def test_rule_missing_action(self):
        data = {
            "tribunal_bundle": "1.0",
            "name": "test",
            "rules": {"r1": {"trigger": "PreToolUse"}},
        }
        errors = validate_bundle(data)
        assert any("action" in e for e in errors)


class TestExportRules:
    def test_export_empty_project(self, tmp_path):
        bundle = export_rules(str(tmp_path))
        assert bundle.name == tmp_path.name
        assert bundle.rules == {}

    def test_export_with_rules(self, tmp_path):
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text(
            "rules:\n  tdd:\n    trigger: PreToolUse\n    action: block\n"
        )
        bundle = export_rules(str(tmp_path))
        assert "tdd" in bundle.rules

    def test_export_with_name(self, tmp_path):
        bundle = export_rules(str(tmp_path), name="my-team-rules")
        assert bundle.name == "my-team-rules"

    def test_export_to_file(self, tmp_path):
        out = tmp_path / "output" / "bundle.yaml"
        path = export_to_file(out, str(tmp_path))
        assert path.exists()
        data = yaml.safe_load(path.read_text())
        assert data["tribunal_bundle"] == "1.0"


class TestImportRules:
    def test_import_rules(self, tmp_path):
        bundle_data = {
            "tribunal_bundle": "1.0",
            "name": "test",
            "rules": {"tdd": {"trigger": "PreToolUse", "action": "block", "message": "Tests first"}},
        }
        ok, msgs = import_rules(bundle_data, str(tmp_path))
        assert ok is True
        assert any("Imported" in m for m in msgs)

        # Verify rules file was created
        rules_path = tmp_path / ".tribunal" / "rules.yaml"
        assert rules_path.exists()
        data = yaml.safe_load(rules_path.read_text())
        assert "tdd" in data["rules"]

    def test_import_merge(self, tmp_path):
        """Importing merges with existing rules by default."""
        rules_dir = tmp_path / ".tribunal"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text(
            "rules:\n  existing:\n    trigger: PreToolUse\n    action: warn\n"
        )

        bundle_data = {
            "tribunal_bundle": "1.0",
            "name": "test",
            "rules": {"new_rule": {"trigger": "PostToolUse", "action": "block"}},
        }
        ok, msgs = import_rules(bundle_data, str(tmp_path))
        assert ok is True

        data = yaml.safe_load((rules_dir / "rules.yaml").read_text())
        assert "existing" in data["rules"]
        assert "new_rule" in data["rules"]

    def test_import_invalid_bundle(self, tmp_path):
        ok, msgs = import_rules({"name": ""}, str(tmp_path))
        assert ok is False

    def test_import_features(self, tmp_path):
        bundle_data = {
            "tribunal_bundle": "1.0",
            "name": "test",
            "features": {"mcp_server": True, "cost_tracking": True},
        }
        ok, msgs = import_rules(bundle_data, str(tmp_path))
        assert ok is True
        assert any("feature" in m.lower() for m in msgs)

    def test_import_from_file(self, tmp_path):
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "file-bundle",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }))
        project = tmp_path / "project"
        project.mkdir()
        ok, msgs = import_from_file(str(bundle), str(project))
        assert ok is True

    def test_import_missing_file(self, tmp_path):
        ok, msgs = import_from_file("/nonexistent/file.yaml", str(tmp_path))
        assert ok is False


# ── Managed Settings Tests ────────────────────────────────────────────────────


class TestManagedPolicy:
    def test_default_policy(self):
        p = ManagedPolicy()
        assert p.max_session_budget_usd == 0.0
        assert p.denied_tools == []
        assert p.audit_required is False

    def test_load_managed_no_file(self, tmp_path):
        result = load_managed_policy(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_load_managed_policy(self, tmp_path):
        cfg = tmp_path / "managed.yaml"
        cfg.write_text(yaml.dump({
            "max_session_budget_usd": 10.0,
            "max_daily_budget_usd": 50.0,
            "denied_tools": ["Bash"],
            "required_review_agents": ["security", "tdd"],
            "audit_required": True,
            "required_features": {"secret_scanning": True},
            "allowed_models": ["sonnet", "haiku"],
        }))
        policy = load_managed_policy(cfg)
        assert policy is not None
        assert policy.max_session_budget_usd == 10.0
        assert policy.max_daily_budget_usd == 50.0
        assert "Bash" in policy.denied_tools
        assert "security" in policy.required_review_agents
        assert policy.audit_required is True
        assert policy.allowed_models == ["sonnet", "haiku"]


class TestApplyManagedPolicy:
    def test_enforce_budget_cap(self):
        policy = ManagedPolicy(max_session_budget_usd=5.0)
        config = {"budget": {"session_usd": 20.0}}
        result = apply_managed_policy(config, policy)
        assert result["budget"]["session_usd"] == 5.0

    def test_set_budget_when_zero(self):
        policy = ManagedPolicy(max_session_budget_usd=5.0)
        config: dict = {}
        result = apply_managed_policy(config, policy)
        assert result["budget"]["session_usd"] == 5.0

    def test_no_override_when_under_cap(self):
        policy = ManagedPolicy(max_session_budget_usd=10.0)
        config = {"budget": {"session_usd": 3.0}}
        result = apply_managed_policy(config, policy)
        assert result["budget"]["session_usd"] == 3.0

    def test_enforce_audit_required(self):
        policy = ManagedPolicy(audit_required=True)
        config: dict = {"audit": {"enabled": False}}
        result = apply_managed_policy(config, policy)
        assert result["audit"]["enabled"] is True

    def test_enforce_required_features(self):
        policy = ManagedPolicy(required_features={"secret_scanning": True})
        config: dict = {"features": {"secret_scanning": False}}
        result = apply_managed_policy(config, policy)
        assert result["features"]["secret_scanning"] is True

    def test_enforce_review_agents(self):
        policy = ManagedPolicy(required_review_agents=["security"])
        config = {"review_agents": ["tdd"]}
        result = apply_managed_policy(config, policy)
        assert "security" in result["review_agents"]
        assert "tdd" in result["review_agents"]


class TestGenerateManagedConfig:
    def test_generate(self):
        policy = ManagedPolicy(
            max_session_budget_usd=10.0,
            denied_tools=["Bash"],
            audit_required=True,
        )
        text = generate_managed_config(policy)
        data = yaml.safe_load(text)
        assert data["max_session_budget_usd"] == 10.0
        assert "Bash" in data["denied_tools"]
        assert data["audit_required"] is True


class TestFormatManagedStatus:
    def test_no_policy(self):
        text = format_managed_status(None)
        assert "No managed policy" in text

    def test_active_policy(self):
        policy = ManagedPolicy(
            max_session_budget_usd=10.0,
            audit_required=True,
        )
        text = format_managed_status(policy)
        assert "ACTIVE" in text
        assert "$10.00" in text


# ── Model Routing Tests ──────────────────────────────────────────────────────


class TestModelRoute:
    def test_matches_pattern(self):
        route = ModelRoute(name="test", pattern="FileEdit*", model="haiku")
        assert route.matches(tool_name="FileEdit") is True
        assert route.matches(tool_name="Bash") is False

    def test_empty_pattern_matches_all(self):
        route = ModelRoute(name="default", pattern="", model="sonnet")
        assert route.matches(tool_name="anything") is True

    def test_case_insensitive(self):
        route = ModelRoute(name="test", pattern="bash*", model="haiku")
        assert route.matches(tool_name="Bash") is True


class TestModelConfig:
    def test_default_model(self):
        config = ModelConfig()
        assert config.resolve_model() == "sonnet"

    def test_route_priority(self):
        config = ModelConfig(
            routes=[
                ModelRoute(name="cheap", pattern="Bash*", model="haiku"),
                ModelRoute(name="smart", pattern="FileEdit*", model="opus"),
            ]
        )
        assert config.resolve_model(tool_name="Bash") == "haiku"
        assert config.resolve_model(tool_name="FileEdit") == "opus"
        assert config.resolve_model(tool_name="Unknown") == "sonnet"

    def test_cost_aware_downgrade(self):
        config = ModelConfig(cost_aware=True, budget_threshold_pct=80.0)
        assert config.resolve_model(budget_used_pct=90.0) == "haiku"
        assert config.resolve_model(budget_used_pct=50.0) == "sonnet"

    def test_cost_aware_disabled(self):
        config = ModelConfig(cost_aware=False)
        assert config.resolve_model(budget_used_pct=99.0) == "sonnet"

    def test_load_empty_config(self, tmp_path):
        config = load_model_config(str(tmp_path))
        assert config.default_model == "sonnet"
        assert config.routes == []

    def test_load_config_with_routes(self, tmp_path):
        cfg_dir = tmp_path / ".tribunal"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(yaml.dump({
            "model_routing": {
                "default": "opus",
                "cost_aware": True,
                "budget_threshold_pct": 70.0,
                "routes": [
                    {"name": "cheap", "pattern": "Bash*", "model": "haiku", "description": "Shell ops"},
                    {"name": "smart", "pattern": "FileEdit*", "model": "opus"},
                ],
            }
        }))
        config = load_model_config(str(tmp_path))
        assert config.default_model == "opus"
        assert config.budget_threshold_pct == 70.0
        assert len(config.routes) == 2
        assert config.routes[0].model == "haiku"

    def test_format_config(self):
        config = ModelConfig(
            default_model="opus",
            routes=[ModelRoute(name="test", pattern="Bash*", model="haiku", description="Shell ops")],
        )
        text = format_model_config(config)
        assert "opus" in text
        assert "Bash*" in text
        assert "haiku" in text


# ── Marketplace Tests ─────────────────────────────────────────────────────────


class TestMarketplace:
    def test_empty_marketplace(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        entries = list_marketplace()
        assert entries == []

    def test_register_and_list(self, tmp_path, monkeypatch):
        registry = tmp_path / "market.json"
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: registry)

        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "test-rules",
            "version": "1.0",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }))

        ok, msg = register_bundle(str(bundle))
        assert ok is True
        assert "Registered" in msg

        entries = list_marketplace()
        assert len(entries) == 1
        assert entries[0].name == "test-rules"

    def test_register_update(self, tmp_path, monkeypatch):
        """Re-registering same name updates the entry."""
        registry = tmp_path / "market.json"
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: registry)

        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "test-rules",
            "version": "1.0",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }))
        register_bundle(str(bundle))

        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "test-rules",
            "version": "2.0",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "warn"}},
        }))
        ok, msg = register_bundle(str(bundle))
        assert ok is True
        assert "Updated" in msg

        entries = list_marketplace()
        assert len(entries) == 1
        assert entries[0].version == "2.0"

    def test_unregister(self, tmp_path, monkeypatch):
        registry = tmp_path / "market.json"
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: registry)

        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "test-rules",
            "version": "1.0",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }))
        register_bundle(str(bundle))

        ok, msg = unregister_bundle("test-rules")
        assert ok is True

        entries = list_marketplace()
        assert len(entries) == 0

    def test_unregister_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        ok, msg = unregister_bundle("nonexistent")
        assert ok is False

    def test_install_from_marketplace(self, tmp_path, monkeypatch):
        registry = tmp_path / "market.json"
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: registry)

        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "team-rules",
            "version": "1.0",
            "rules": {"tdd": {"trigger": "PreToolUse", "action": "block"}},
        }))
        register_bundle(str(bundle))

        project = tmp_path / "project"
        project.mkdir()
        ok, msgs = install_from_marketplace("team-rules", str(project))
        assert ok is True

        # Verify rules were imported
        rules_path = project / ".tribunal" / "rules.yaml"
        assert rules_path.exists()

    def test_install_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        ok, msgs = install_from_marketplace("nonexistent", str(tmp_path))
        assert ok is False

    def test_register_invalid_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        ok, msg = register_bundle("/nonexistent/file.yaml")
        assert ok is False

    def test_register_invalid_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        bundle = tmp_path / "bad.yaml"
        bundle.write_text(yaml.dump({"name": ""}))
        ok, msg = register_bundle(str(bundle))
        assert ok is False


class TestFormatMarketplace:
    def test_empty(self):
        text = format_marketplace([])
        assert "No bundles" in text

    def test_with_entries(self):
        entries = [
            MarketplaceEntry(
                name="team-rules",
                version="1.0",
                description="Company standards",
                author="Security Team",
                installed=True,
            )
        ]
        text = format_marketplace(entries)
        assert "team-rules" in text
        assert "installed" in text
        assert "Security Team" in text


# ── CLI Phase 4 Tests ────────────────────────────────────────────────────────


class TestCLIPhase4:
    def test_sync_export(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_sync

        class Args:
            sync_command = "export"
            output = str(tmp_path / "export.yaml")
            name = "test-export"

        result = cmd_sync(Args())
        assert result == 0
        assert (tmp_path / "export.yaml").exists()

    def test_sync_import(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)

        bundle = tmp_path / "bundle.yaml"
        bundle.write_text(yaml.dump({
            "tribunal_bundle": "1.0",
            "name": "import-test",
            "rules": {"r1": {"trigger": "PreToolUse", "action": "block"}},
        }))

        from tribunal.cli import cmd_sync

        class Args:
            sync_command = "import"
            file = str(bundle)
            replace = False

        result = cmd_sync(Args())
        assert result == 0

    def test_managed_status(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_managed

        class Args:
            pass

        result = cmd_managed(Args())
        captured = capsys.readouterr()
        assert "Managed Policy" in captured.out
        assert result == 0

    def test_model_show(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_model

        class Args:
            model_command = None

        result = cmd_model(Args())
        captured = capsys.readouterr()
        assert "Model Routing" in captured.out
        assert result == 0

    def test_model_resolve(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tribunal.cli import cmd_model

        class Args:
            model_command = "resolve"
            tool = "FileEdit"

        result = cmd_model(Args())
        captured = capsys.readouterr()
        assert "Model:" in captured.out
        assert result == 0

    def test_marketplace_list_empty(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("tribunal.marketplace._registry_path", lambda: tmp_path / "market.json")
        from tribunal.cli import cmd_marketplace

        class Args:
            market_command = "list"

        result = cmd_marketplace(Args())
        captured = capsys.readouterr()
        assert "Marketplace" in captured.out
        assert result == 0
