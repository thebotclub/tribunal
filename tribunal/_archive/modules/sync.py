"""Team rules sync — import/export rule sets across teams.

Enables sharing and synchronizing Tribunal rule configurations:
- Export: serialize project rules to a portable YAML bundle
- Import: apply rules from a bundle (URL, file, or inline YAML)
- Validate: check rule bundle integrity before applying
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import __version__


@dataclass
class RuleBundle:
    """A portable bundle of Tribunal rules."""

    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    rules: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    features: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tribunal_bundle": "1.0",
            "name": self.name,
            "version": self.version,
        }
        if self.description:
            result["description"] = self.description
        if self.author:
            result["author"] = self.author
        if self.rules:
            result["rules"] = self.rules
        if self.permissions:
            result["permissions"] = self.permissions
        if self.features:
            result["features"] = self.features
        return result

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)


def validate_bundle(data: dict[str, Any]) -> list[str]:
    """Validate a rule bundle dict. Returns list of errors (empty = valid)."""
    errors = []

    if "tribunal_bundle" not in data:
        errors.append("Missing 'tribunal_bundle' version key.")

    if "name" not in data or not data["name"]:
        errors.append("Missing 'name' field.")

    if "rules" in data:
        rules = data["rules"]
        if not isinstance(rules, dict):
            errors.append("'rules' must be a mapping.")
        else:
            for rule_name, rule in rules.items():
                if not isinstance(rule, dict):
                    errors.append(f"Rule '{rule_name}' must be a mapping.")
                    continue
                if "trigger" not in rule:
                    errors.append(f"Rule '{rule_name}' missing 'trigger'.")
                if "action" not in rule:
                    errors.append(f"Rule '{rule_name}' missing 'action'.")

    return errors


def export_rules(cwd: str | None = None, name: str = "", author: str = "") -> RuleBundle:
    """Export current project rules as a portable bundle."""
    project_dir = Path(cwd) if cwd else Path.cwd()

    # Load rules
    rules_path = project_dir / ".tribunal" / "rules.yaml"
    rules = {}
    if rules_path.is_file():
        try:
            data = yaml.safe_load(rules_path.read_text()) or {}
            rules = data.get("rules", {})
        except yaml.YAMLError:
            pass

    # Load permissions if present
    config_path = project_dir / ".claude" / "claudeconfig.json"
    permissions = {}
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text())
            if "permissions" in config:
                permissions = config["permissions"]
        except (json.JSONDecodeError, OSError):
            pass

    # Load feature flags
    features: dict[str, bool] = {}
    cfg_path = project_dir / ".tribunal" / "config.yaml"
    if cfg_path.is_file():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            features = cfg.get("features", {})
        except yaml.YAMLError:
            pass

    bundle_name = name or project_dir.name
    return RuleBundle(
        name=bundle_name,
        version=__version__,
        description=f"Rules exported from {bundle_name}",
        author=author,
        rules=rules,
        permissions=permissions,
        features=features,
    )


def export_to_file(output_path: str | Path, cwd: str | None = None,
                   name: str = "", author: str = "") -> Path:
    """Export rules to a YAML file."""
    bundle = export_rules(cwd, name, author)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.to_yaml())
    return path


def import_rules(bundle_data: dict[str, Any], cwd: str | None = None,
                 merge: bool = True) -> tuple[bool, list[str]]:
    """Import rules from a bundle dict into the project.

    Returns (success, messages).
    """
    errors = validate_bundle(bundle_data)
    if errors:
        return False, errors

    project_dir = Path(cwd) if cwd else Path.cwd()
    tribunal_dir = project_dir / ".tribunal"
    tribunal_dir.mkdir(parents=True, exist_ok=True)
    messages = []

    # Import rules
    incoming_rules = bundle_data.get("rules", {})
    if incoming_rules:
        rules_path = tribunal_dir / "rules.yaml"
        existing_rules: dict[str, Any] = {}
        if merge and rules_path.is_file():
            try:
                data = yaml.safe_load(rules_path.read_text()) or {}
                existing_rules = data.get("rules", {})
            except yaml.YAMLError:
                pass

        merged = {**existing_rules, **incoming_rules}
        rules_path.write_text(yaml.dump({"rules": merged}, default_flow_style=False))
        new_count = len(incoming_rules)
        total_count = len(merged)
        messages.append(f"Imported {new_count} rule(s) ({total_count} total).")

    # Import features
    incoming_features = bundle_data.get("features", {})
    if incoming_features:
        cfg_path = tribunal_dir / "config.yaml"
        existing_cfg: dict[str, Any] = {}
        if merge and cfg_path.is_file():
            try:
                existing_cfg = yaml.safe_load(cfg_path.read_text()) or {}
            except yaml.YAMLError:
                pass

        existing_features = existing_cfg.get("features", {})
        existing_features.update(incoming_features)
        existing_cfg["features"] = existing_features
        cfg_path.write_text(yaml.dump(existing_cfg, default_flow_style=False))
        messages.append(f"Imported {len(incoming_features)} feature flag(s).")

    if not messages:
        messages.append("Bundle contained no rules or features to import.")

    return True, messages


def import_from_file(file_path: str | Path, cwd: str | None = None,
                     merge: bool = True) -> tuple[bool, list[str]]:
    """Import rules from a YAML file."""
    path = Path(file_path)
    if not path.is_file():
        return False, [f"File not found: {file_path}"]

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        return False, [f"Invalid YAML: {e}"]

    return import_rules(data, cwd, merge)
