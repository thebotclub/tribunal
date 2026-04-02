"""Air-gapped bundles — package Tribunal config for offline use.

Packages all rules, skills, config, and policies into a single
JSON file that can be transferred to air-gapped environments.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BUNDLE_VERSION = "1"


@dataclass
class AirgapBundle:
    """Self-contained Tribunal bundle for offline deployment."""

    version: str = BUNDLE_VERSION
    created_at: str = ""
    rules: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, str]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_version": self.version,
            "created_at": self.created_at,
            "rules": self.rules,
            "skills": self.skills,
            "config": self.config,
            "permissions": self.permissions,
            "metadata": self.metadata,
        }


def create_bundle(cwd: str, *, include_skills: bool = True) -> AirgapBundle:
    """Create an air-gapped bundle from the current project config."""
    import yaml

    bundle = AirgapBundle(
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    base = Path(cwd) / ".tribunal"

    # Rules
    rules_path = base / "rules.yaml"
    if rules_path.is_file():
        data = yaml.safe_load(rules_path.read_text()) or {}
        bundle.rules = data.get("rules", [])

    # Config
    config_path = base / "config.yaml"
    if config_path.is_file():
        bundle.config = yaml.safe_load(config_path.read_text()) or {}

    # Permissions
    perms_path = base / "permissions.yaml"
    if perms_path.is_file():
        bundle.permissions = yaml.safe_load(perms_path.read_text()) or {}

    # Skills
    if include_skills:
        skills_dir = base / "skills"
        if skills_dir.is_dir():
            for skill_file in sorted(skills_dir.glob("*.md")):
                bundle.skills.append(
                    {
                        "name": skill_file.stem,
                        "content": skill_file.read_text(),
                    }
                )
        # Also include bundled skills
        bundled_dir = Path(__file__).parent / "bundled_skills"
        if bundled_dir.is_dir():
            for skill_file in sorted(bundled_dir.glob("*.md")):
                if not any(s["name"] == skill_file.stem for s in bundle.skills):
                    bundle.skills.append(
                        {
                            "name": skill_file.stem,
                            "content": skill_file.read_text(),
                        }
                    )

    bundle.metadata = {
        "source": str(Path(cwd).resolve()),
        "bundle_format": "tribunal-airgap-v1",
    }

    return bundle


def export_bundle(cwd: str, output: str | None = None, **kwargs: Any) -> str:
    """Export bundle to a JSON file. Returns the output path."""
    bundle = create_bundle(cwd, **kwargs)
    if output is None:
        output = str(Path(cwd) / ".tribunal" / "bundle.json")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(bundle.to_dict(), indent=2))
    return output


def import_bundle(bundle_path: str, target_cwd: str) -> dict[str, int]:
    """Import an air-gapped bundle into a project. Returns counts."""
    import yaml

    data = json.loads(Path(bundle_path).read_text())

    if data.get("bundle_format") and data["bundle_format"] != "tribunal-airgap-v1":
        # Check metadata too
        pass
    meta = data.get("metadata", {})
    if meta.get("bundle_format") and meta["bundle_format"] != "tribunal-airgap-v1":
        pass

    base = Path(target_cwd) / ".tribunal"
    base.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"rules": 0, "skills": 0, "config": 0, "permissions": 0}

    # Import rules
    rules = data.get("rules", [])
    if rules:
        rules_path = base / "rules.yaml"
        rules_path.write_text(yaml.dump({"rules": rules}, default_flow_style=False))
        counts["rules"] = len(rules)

    # Import config
    config = data.get("config", {})
    if config:
        config_path = base / "config.yaml"
        config_path.write_text(yaml.dump(config, default_flow_style=False))
        counts["config"] = 1

    # Import permissions
    perms = data.get("permissions", {})
    if perms:
        perms_path = base / "permissions.yaml"
        perms_path.write_text(yaml.dump(perms, default_flow_style=False))
        counts["permissions"] = 1

    # Import skills
    skills = data.get("skills", [])
    if skills:
        skills_dir = base / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            name = skill.get("name", "unknown")
            content = skill.get("content", "")
            (skills_dir / f"{name}.md").write_text(content)
            counts["skills"] += 1

    return counts


def validate_bundle(bundle_path: str) -> tuple[bool, list[str]]:
    """Validate a bundle file. Returns (valid, errors)."""
    errors: list[str] = []

    path = Path(bundle_path)
    if not path.is_file():
        return False, ["Bundle file not found"]

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    if not isinstance(data, dict):
        return False, ["Bundle must be a JSON object"]

    if "bundle_version" not in data:
        errors.append("Missing bundle_version")

    for key in ("rules", "skills"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} must be a list")

    for key in ("config", "permissions", "metadata"):
        if key in data and not isinstance(data[key], dict):
            errors.append(f"{key} must be a dict")

    return len(errors) == 0, errors
