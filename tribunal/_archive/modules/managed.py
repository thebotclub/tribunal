"""Managed settings — enterprise config support.

Supports loading managed settings from system-level paths for
enterprise fleet deployment, matching Claude Code's managed settings model.

Resolution order:
1. /etc/tribunal/config.yaml (system/managed — highest precedence on policy)
2. ~/.tribunal/config.yaml (user)
3. .tribunal/config.yaml (project)
4. Environment variables

Managed settings can enforce policies that project-level config cannot override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ManagedPolicy:
    """Enterprise managed policy that cannot be overridden."""

    enforced_rules: dict[str, Any] = field(default_factory=dict)
    denied_tools: list[str] = field(default_factory=list)
    max_session_budget_usd: float = 0.0
    max_daily_budget_usd: float = 0.0
    required_review_agents: list[str] = field(default_factory=list)
    required_features: dict[str, bool] = field(default_factory=dict)
    allowed_models: list[str] = field(default_factory=list)
    audit_required: bool = False


# Default system-level paths (platform-aware)
_MANAGED_PATHS = {
    "linux": Path("/etc/tribunal/config.yaml"),
    "darwin": Path("/etc/tribunal/config.yaml"),
    "win32": Path("C:/ProgramData/tribunal/config.yaml"),
}


def _get_managed_path() -> Path:
    """Get the managed settings path for the current platform."""
    import sys
    return _MANAGED_PATHS.get(sys.platform, Path("/etc/tribunal/config.yaml"))


def _load_yaml_safe(path: Path) -> dict[str, Any]:
    """Load a YAML file safely."""
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}


def load_managed_policy(path: Path | None = None) -> ManagedPolicy | None:
    """Load managed policy from system path.

    Returns None if no managed policy exists.
    """
    config_path = path or _get_managed_path()
    data = _load_yaml_safe(config_path)
    if not data:
        return None

    policy = ManagedPolicy()

    if rules := data.get("enforced_rules"):
        policy.enforced_rules = dict(rules)

    if denied := data.get("denied_tools"):
        policy.denied_tools = list(denied)

    if budget := data.get("max_session_budget_usd"):
        policy.max_session_budget_usd = float(budget)

    if budget := data.get("max_daily_budget_usd"):
        policy.max_daily_budget_usd = float(budget)

    if agents := data.get("required_review_agents"):
        policy.required_review_agents = list(agents)

    if features := data.get("required_features"):
        policy.required_features = dict(features)

    if models := data.get("allowed_models"):
        policy.allowed_models = list(models)

    if data.get("audit_required"):
        policy.audit_required = True

    return policy


def apply_managed_policy(config: dict[str, Any],
                         policy: ManagedPolicy) -> dict[str, Any]:
    """Apply managed policy constraints to a resolved config dict.

    Managed policies ENFORCE — they cannot be overridden by user/project config.
    """
    result = dict(config)

    # Enforce budget caps
    if policy.max_session_budget_usd > 0:
        current = result.get("budget", {}).get("session_usd", 0)
        if current <= 0 or current > policy.max_session_budget_usd:
            result.setdefault("budget", {})["session_usd"] = policy.max_session_budget_usd

    if policy.max_daily_budget_usd > 0:
        current = result.get("budget", {}).get("daily_usd", 0)
        if current <= 0 or current > policy.max_daily_budget_usd:
            result.setdefault("budget", {})["daily_usd"] = policy.max_daily_budget_usd

    # Force required features
    if policy.required_features:
        result.setdefault("features", {}).update(policy.required_features)

    # Force audit
    if policy.audit_required:
        result.setdefault("audit", {})["enabled"] = True

    # Force required review agents
    if policy.required_review_agents:
        existing = set(result.get("review_agents", []))
        for agent in policy.required_review_agents:
            existing.add(agent)
        result["review_agents"] = sorted(existing)

    return result


def generate_managed_config(policy: ManagedPolicy) -> str:
    """Generate a managed config YAML for deployment."""
    data: dict[str, Any] = {}

    if policy.enforced_rules:
        data["enforced_rules"] = policy.enforced_rules

    if policy.denied_tools:
        data["denied_tools"] = policy.denied_tools

    if policy.max_session_budget_usd > 0:
        data["max_session_budget_usd"] = policy.max_session_budget_usd

    if policy.max_daily_budget_usd > 0:
        data["max_daily_budget_usd"] = policy.max_daily_budget_usd

    if policy.required_review_agents:
        data["required_review_agents"] = policy.required_review_agents

    if policy.required_features:
        data["required_features"] = policy.required_features

    if policy.allowed_models:
        data["allowed_models"] = policy.allowed_models

    if policy.audit_required:
        data["audit_required"] = True

    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def format_managed_status(policy: ManagedPolicy | None) -> str:
    """Format managed policy status for display."""
    lines = ["\n  ⚖  Managed Policy Status\n"]

    if policy is None:
        lines.append("  No managed policy detected.")
        lines.append(f"  Managed path: {_get_managed_path()}")
        lines.append("")
        return "\n".join(lines)

    lines.append("  ✓ Managed policy ACTIVE\n")

    if policy.max_session_budget_usd > 0:
        lines.append(f"  Budget cap (session): ${policy.max_session_budget_usd:.2f}")
    if policy.max_daily_budget_usd > 0:
        lines.append(f"  Budget cap (daily):   ${policy.max_daily_budget_usd:.2f}")

    if policy.denied_tools:
        lines.append(f"\n  Denied tools: {', '.join(policy.denied_tools)}")

    if policy.required_review_agents:
        lines.append(f"  Required agents: {', '.join(policy.required_review_agents)}")

    if policy.allowed_models:
        lines.append(f"  Allowed models: {', '.join(policy.allowed_models)}")

    if policy.audit_required:
        lines.append("  Audit: REQUIRED")

    if policy.required_features:
        lines.append("\n  Required features:")
        for name, enabled in sorted(policy.required_features.items()):
            icon = "✓" if enabled else "✗"
            lines.append(f"    {icon} {name}")

    lines.append("")
    return "\n".join(lines)
