"""Rule Packs — curated rule bundles for common compliance and workflow needs.

Each pack is a YAML bundle that can be installed with:
    tribunal pack install <name>

Packs:
    soc2        SOC 2 compliance: audit everything, no secrets, restrict FS access
    startup     Lightweight startup defaults: TDD, secret scanning, cost limits
    enterprise  Full enterprise: managed policies + review agents + memory injection
    security    Security-focused: secret scanning + dependency audit + code review
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ── Built-in packs ────────────────────────────────────────────────────────────

_PACKS: dict[str, dict[str, Any]] = {
    "soc2": {
        "name": "tribunal-soc2",
        "version": "1.0.0",
        "description": "SOC 2 compliance rules — audit all tool calls, block secrets, restrict file system access.",
        "rules": {
            "audit-all-tools": {
                "trigger": "PostToolUse",
                "match": {},
                "action": "log",
                "message": "SOC 2: all tool calls are audited.",
            },
            "no-secrets": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite"},
                "action": "block",
                "condition": "contains-secret",
                "message": "SOC 2: secrets must not be hardcoded. Use environment variables or a secrets manager.",
            },
            "restrict-fs-writes": {
                "trigger": "PreToolUse",
                "match": {"tool": "Bash"},
                "action": "warn",
                "condition": "run-command",
                "run": "echo $TRIBUNAL_TOOL_INPUT | grep -qE '(rm -rf|chmod 777|dd if=)' && exit 1 || exit 0",
                "message": "SOC 2: dangerous filesystem operations detected.",
            },
            "require-review": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
                "action": "warn",
                "condition": "no-matching-test",
                "message": "SOC 2: production code changes should have test coverage.",
            },
        },
        "config": {
            "audit": {"enabled": True, "max_bytes": 50_000_000, "keep_rotated": 10},
            "budget": {"session_usd": 10.0, "daily_usd": 50.0, "warn_percent": 70},
        },
    },
    "startup": {
        "name": "tribunal-startup",
        "version": "1.0.0",
        "description": "Lightweight startup defaults — TDD enforcement, secret scanning, reasonable cost limits.",
        "rules": {
            "tdd-python": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
                "action": "block",
                "condition": "no-matching-test",
                "message": "Write a failing test first. TDD saves time in the long run.",
            },
            "tdd-typescript": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.ts"},
                "action": "block",
                "condition": "no-matching-test-ts",
                "message": "Write a failing test first. Create <module>.test.ts before editing.",
            },
            "no-secrets": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite"},
                "action": "block",
                "condition": "contains-secret",
                "message": "No hardcoded secrets. Use environment variables.",
            },
        },
        "config": {
            "budget": {"session_usd": 5.0, "daily_usd": 20.0},
        },
    },
    "enterprise": {
        "name": "tribunal-enterprise",
        "version": "1.0.0",
        "description": "Full enterprise governance — all rules, review agents, managed policies, memory injection.",
        "rules": {
            "tdd-python": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
                "action": "block",
                "condition": "no-matching-test",
                "message": "Enterprise: test coverage required before all production code changes.",
            },
            "no-secrets": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite"},
                "action": "block",
                "condition": "contains-secret",
                "message": "Enterprise: secrets must be stored in a secrets manager.",
            },
            "type-check": {
                "trigger": "PostToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
                "action": "warn",
                "condition": "type-check",
                "require_tool": True,
                "message": "Enterprise: type checking required (mypy).",
            },
            "lint-check": {
                "trigger": "PostToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
                "action": "warn",
                "condition": "lint-check",
                "require_tool": True,
                "message": "Enterprise: linting required (ruff/flake8).",
            },
        },
        "config": {
            "audit": {"enabled": True, "max_bytes": 100_000_000, "keep_rotated": 20},
            "budget": {"session_usd": 25.0, "daily_usd": 100.0, "warn_percent": 60},
            "review_agents": ["tdd", "security", "quality", "spec"],
            "features": {
                "tdd_enforcement": True,
                "secret_scanning": True,
                "cost_tracking": True,
                "review_agents": True,
            },
            "multi_agent": {
                "max_concurrent_agents": 5,
                "per_agent_budget": 5.0,
                "shared_session_budget": 25.0,
            },
        },
    },
    "security": {
        "name": "tribunal-security",
        "version": "1.0.0",
        "description": "Security-focused rules — secret scanning, dependency audit, code review enforcement.",
        "rules": {
            "no-secrets": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite"},
                "action": "block",
                "condition": "contains-secret",
                "message": "Security: no hardcoded secrets, tokens, or API keys.",
            },
            "no-unsafe-bash": {
                "trigger": "PreToolUse",
                "match": {"tool": "Bash"},
                "action": "warn",
                "condition": "run-command",
                "run": "echo $TRIBUNAL_TOOL_INPUT | grep -qE '(curl.*\\|.*sh|wget.*\\|.*bash|eval )' && exit 1 || exit 0",
                "message": "Security: potentially unsafe command execution detected.",
            },
            "require-tests-for-auth": {
                "trigger": "PreToolUse",
                "match": {"tool": "FileEdit|FileWrite", "path": "*auth*"},
                "action": "block",
                "condition": "no-matching-test",
                "message": "Security: authentication code must have test coverage.",
            },
        },
        "config": {
            "audit": {"enabled": True},
            "features": {"secret_scanning": True, "tdd_enforcement": True},
        },
    },
}


def list_packs() -> list[dict[str, str]]:
    """List available rule packs."""
    return [
        {"name": name, "description": pack["description"]}
        for name, pack in _PACKS.items()
    ]


def get_pack(name: str) -> dict[str, Any] | None:
    """Get a pack definition by name."""
    return _PACKS.get(name)


def install_pack(name: str, cwd: str, merge: bool = True) -> tuple[bool, list[str]]:
    """Install a rule pack into the project.

    Returns (success, messages).
    """
    pack = get_pack(name)
    if not pack:
        return False, [f"Unknown pack: '{name}'. Available: {', '.join(_PACKS.keys())}"]

    messages = []
    tribunal_dir = Path(cwd) / ".tribunal"
    tribunal_dir.mkdir(exist_ok=True)

    # Install rules
    rules_path = tribunal_dir / "rules.yaml"
    if rules_path.is_file() and merge:
        existing = yaml.safe_load(rules_path.read_text()) or {}
        existing_rules = existing.get("rules", {})
        existing_rules.update(pack["rules"])
        existing["rules"] = existing_rules
        rules_path.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False)
        )
        messages.append(f"Merged {len(pack['rules'])} rules into existing rules.yaml")
    else:
        rules_path.write_text(
            yaml.dump(
                {"rules": pack["rules"]}, default_flow_style=False, sort_keys=False
            )
        )
        messages.append(f"Wrote {len(pack['rules'])} rules to rules.yaml")

    # Install config overrides
    if "config" in pack:
        config_path = tribunal_dir / "config.yaml"
        if config_path.is_file() and merge:
            existing = yaml.safe_load(config_path.read_text()) or {}
            existing.update(pack["config"])
            config_path.write_text(
                yaml.dump(existing, default_flow_style=False, sort_keys=False)
            )
            messages.append("Merged pack config into config.yaml")
        else:
            config_path.write_text(
                yaml.dump(pack["config"], default_flow_style=False, sort_keys=False)
            )
            messages.append("Wrote pack config to config.yaml")

    messages.append(f"Pack '{name}' installed successfully.")
    return True, messages


def format_packs() -> str:
    """Format available packs for CLI display."""
    lines = ["\n  ⚖  Tribunal Rule Packs\n"]
    for name, pack in _PACKS.items():
        rule_count = len(pack.get("rules", {}))
        lines.append(f"  📦 {name} ({rule_count} rules)")
        lines.append(f"     {pack['description']}")
        lines.append("")
    lines.append("  Install with: tribunal pack install <name>")
    lines.append("")
    return "\n".join(lines)
