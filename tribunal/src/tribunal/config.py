"""Config cascade — multi-level configuration resolution.

Resolves Tribunal settings by merging configs from multiple levels,
matching Claude Code's managed → enterprise → user → project cascade.

Resolution order (later overrides earlier):
1. Built-in defaults
2. User config: ~/.tribunal/config.yaml
3. Project config: .tribunal/rules.yaml + .tribunal/config.yaml
4. Environment variables: TRIBUNAL_*
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

import yaml


# ── TypedDict definitions for config schema ────────────────────────────────────

class BudgetConfig(TypedDict, total=False):
    """Budget configuration section."""
    session_usd: float
    daily_usd: float
    warn_percent: float


class AuditConfig(TypedDict, total=False):
    """Audit configuration section."""
    enabled: bool
    path: str
    max_bytes: int
    keep_rotated: int


class MultiAgentConfig(TypedDict, total=False):
    """Multi-agent governance section."""
    max_concurrent_agents: int
    per_agent_budget: float
    shared_session_budget: float
    agent_permissions: dict[str, dict[str, list[str]]]


class RuleConfig(TypedDict, total=False):
    """Individual rule definition."""
    trigger: str
    match: dict[str, str]
    action: str
    message: str
    condition: str
    run: str
    enabled: bool
    require_tool: bool


class TribunalConfigDict(TypedDict, total=False):
    """Top-level config.yaml schema."""
    budget: BudgetConfig
    audit: AuditConfig
    skills_dirs: list[str]
    permission_preset: str
    review_agents: list[str]
    mcp_enabled: bool
    features: dict[str, bool]
    rules: dict[str, RuleConfig]
    model_routing: dict[str, Any]
    managed: dict[str, Any]
    multi_agent: MultiAgentConfig


@dataclass
class TribunalConfig:
    """Resolved Tribunal configuration."""

    rules_file: str = ""
    budget_session_usd: float = 0.0
    budget_daily_usd: float = 0.0
    budget_warn_percent: float = 80.0
    audit_enabled: bool = True
    audit_path: str = ".tribunal/audit.jsonl"
    skills_dirs: list[str] = field(default_factory=list)
    permission_preset: str = ""
    review_agents: list[str] = field(default_factory=lambda: ["tdd", "security", "quality", "spec"])
    mcp_enabled: bool = False
    # Feature flags
    features: dict[str, bool] = field(default_factory=dict)


_DEFAULTS = TribunalConfig(
    skills_dirs=[".tribunal/skills/"],
    features={
        "tdd_enforcement": True,
        "secret_scanning": True,
        "cost_tracking": True,
        "review_agents": True,
        "mcp_server": False,
    },
)


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML config file safely."""
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}


# ── Config Schema Validation ──────────────────────────────────────────────────

# Known top-level keys and their expected types
_KNOWN_KEYS: dict[str, type | tuple[type, ...]] = {
    "budget": dict,
    "audit": dict,
    "skills_dirs": list,
    "permission_preset": str,
    "review_agents": list,
    "mcp_enabled": bool,
    "features": dict,
    "rules": dict,
    "model_routing": dict,
    "managed": dict,
    "multi_agent": dict,
}

_KNOWN_BUDGET_KEYS = {"session_usd", "daily_usd", "warn_percent"}
_KNOWN_AUDIT_KEYS = {"enabled", "path", "max_bytes", "keep_rotated"}
_VALID_ACTIONS = {"block", "warn", "log"}
_VALID_TRIGGERS = {"PreToolUse", "PostToolUse", "SessionStart", "SessionEnd",
                   "SubagentStart", "SubagentStop", "FileChanged", "CwdChanged",
                   "PermissionRequest", "PermissionDenied", "ConfigChange",
                   "TaskCreated", "TaskCompleted", "PreCompact", "PostCompact"}


def validate_config(data: dict[str, Any]) -> list[str]:
    """Validate config dict against the Tribunal schema.

    Returns list of validation error/warning strings. Empty = valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Config must be a YAML mapping"]

    # Check for unknown top-level keys
    for key in data:
        if key not in _KNOWN_KEYS:
            errors.append(f"Unknown config key: '{key}'")

    # Validate budget section
    if "budget" in data:
        b = data["budget"]
        if not isinstance(b, dict):
            errors.append("'budget' must be a mapping")
        else:
            for k in b:
                if k not in _KNOWN_BUDGET_KEYS:
                    errors.append(f"Unknown budget key: '{k}'")
            for k in ("session_usd", "daily_usd", "warn_percent"):
                if k in b and not isinstance(b[k], (int, float)):
                    errors.append(f"budget.{k} must be a number")

    # Validate audit section
    if "audit" in data:
        a = data["audit"]
        if not isinstance(a, dict):
            errors.append("'audit' must be a mapping")
        else:
            for k in a:
                if k not in _KNOWN_AUDIT_KEYS:
                    errors.append(f"Unknown audit key: '{k}'")

    # Validate rules section
    if "rules" in data:
        rules = data["rules"]
        if not isinstance(rules, dict):
            errors.append("'rules' must be a mapping")
        else:
            for name, rdef in rules.items():
                if not isinstance(rdef, dict):
                    errors.append(f"Rule '{name}' must be a mapping")
                    continue
                action = rdef.get("action", "block")
                if action not in _VALID_ACTIONS:
                    errors.append(f"Rule '{name}': invalid action '{action}' (expected: {_VALID_ACTIONS})")
                trigger = rdef.get("trigger", "")
                if trigger and trigger not in _VALID_TRIGGERS:
                    errors.append(f"Rule '{name}': unknown trigger '{trigger}'")

    # Validate features section
    if "features" in data:
        features = data["features"]
        if not isinstance(features, dict):
            errors.append("'features' must be a mapping")
        else:
            for k, v in features.items():
                if not isinstance(v, bool):
                    errors.append(f"Feature '{k}' must be true or false")

    return errors


def _apply_config(base: TribunalConfig, data: dict[str, Any]) -> TribunalConfig:
    """Apply a config dict onto a base config (shallow merge)."""
    if "budget" in data:
        b = data["budget"]
        if "session_usd" in b:
            base.budget_session_usd = float(b["session_usd"])
        if "daily_usd" in b:
            base.budget_daily_usd = float(b["daily_usd"])
        if "warn_percent" in b:
            base.budget_warn_percent = float(b["warn_percent"])

    if "audit" in data:
        a = data["audit"]
        if "enabled" in a:
            base.audit_enabled = bool(a["enabled"])
        if "path" in a:
            base.audit_path = str(a["path"])

    if "skills_dirs" in data:
        base.skills_dirs = list(data["skills_dirs"])

    if "permission_preset" in data:
        base.permission_preset = str(data["permission_preset"])

    if "review_agents" in data:
        base.review_agents = list(data["review_agents"])

    if "mcp_enabled" in data:
        base.mcp_enabled = bool(data["mcp_enabled"])

    if "features" in data:
        base.features.update(data["features"])

    return base


def _apply_env(config: TribunalConfig) -> TribunalConfig:
    """Apply environment variable overrides."""
    if v := os.environ.get("TRIBUNAL_BUDGET_SESSION"):
        config.budget_session_usd = float(v)
    if v := os.environ.get("TRIBUNAL_BUDGET_DAILY"):
        config.budget_daily_usd = float(v)
    if os.environ.get("TRIBUNAL_AUDIT_DISABLED"):
        config.audit_enabled = False
    if os.environ.get("TRIBUNAL_MCP_ENABLED"):
        config.mcp_enabled = True
    return config


def resolve_config(cwd: str | None = None) -> TribunalConfig:
    """Resolve the full config cascade for the given project directory.

    Cascade order: defaults → user → project → environment
    """
    import copy
    config = copy.deepcopy(_DEFAULTS)

    # 1. User config: ~/.tribunal/config.yaml
    user_config_path = Path.home() / ".tribunal" / "config.yaml"
    user_data = _load_yaml_config(user_config_path)
    if user_data:
        config = _apply_config(config, user_data)

    # 2. Project config: .tribunal/config.yaml
    project_dir = Path(cwd) if cwd else Path.cwd()
    project_config_path = project_dir / ".tribunal" / "config.yaml"
    project_data = _load_yaml_config(project_config_path)
    if project_data:
        # Validate and warn on issues
        errors = validate_config(project_data)
        for err in errors:
            sys.stderr.write(f"tribunal: config warning: {err}\n")
        config = _apply_config(config, project_data)

    # 3. Check for project rules file
    rules_path = project_dir / ".tribunal" / "rules.yaml"
    if rules_path.is_file():
        config.rules_file = str(rules_path)

    # 4. Environment overrides
    config = _apply_env(config)

    return config


def is_feature_enabled(name: str, cwd: str | None = None) -> bool:
    """Check if a feature flag is enabled."""
    config = resolve_config(cwd)
    return config.features.get(name, False)


def format_config(config: TribunalConfig) -> str:
    """Format resolved config for display."""
    lines = ["\n  ⚖  Tribunal Configuration\n"]

    lines.append("  Budget:")
    if config.budget_session_usd > 0:
        lines.append(f"    Session: ${config.budget_session_usd:.2f}")
    else:
        lines.append("    Session: unlimited")
    if config.budget_daily_usd > 0:
        lines.append(f"    Daily:   ${config.budget_daily_usd:.2f}")
    else:
        lines.append("    Daily:   unlimited")

    lines.append(f"\n  Audit: {'enabled' if config.audit_enabled else 'disabled'}")
    lines.append(f"  MCP Server: {'enabled' if config.mcp_enabled else 'disabled'}")

    lines.append(f"\n  Skills dirs: {', '.join(config.skills_dirs)}")
    lines.append(f"  Review agents: {', '.join(config.review_agents)}")

    if config.features:
        lines.append("\n  Features:")
        for name, enabled in sorted(config.features.items()):
            icon = "✓" if enabled else "✗"
            lines.append(f"    {icon} {name}")

    lines.append("")
    return "\n".join(lines)
