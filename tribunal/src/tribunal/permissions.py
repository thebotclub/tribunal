"""Permission policy generator for Claude Code's deny/allow system.

Generates permission rules for .claude/claudeconfig.json based on
project configuration and Tribunal's analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PermissionRule:
    """A single Claude Code permission rule."""

    tool: str  # Tool name: Bash, FileEdit, FileWrite, etc.
    pattern: str  # Glob pattern for what to match
    description: str = ""


@dataclass
class PermissionPolicy:
    """A complete permission policy with deny and allow rules."""

    deny: list[PermissionRule] = field(default_factory=list)
    allow: list[PermissionRule] = field(default_factory=list)

    def to_config(self) -> dict[str, Any]:
        """Convert to Claude Code claudeconfig.json permissions format."""
        result: dict[str, Any] = {}
        if self.deny:
            result["deny"] = [
                {"tool": r.tool, "pattern": r.pattern}
                for r in self.deny
            ]
        if self.allow:
            result["allow"] = [
                {"tool": r.tool, "pattern": r.pattern}
                for r in self.allow
            ]
        return result


# ── Preset Policies ──────────────────────────────────────────────────────────

_PRESETS: dict[str, PermissionPolicy] = {
    "strict": PermissionPolicy(
        deny=[
            PermissionRule("Bash", "curl *|wget *", "No direct HTTP downloads"),
            PermissionRule("Bash", "rm -rf *", "No recursive force delete"),
            PermissionRule("Bash", "sudo *", "No sudo commands"),
            PermissionRule("Bash", "chmod 777 *", "No world-writable permissions"),
            PermissionRule("FileEdit", "/etc/**", "No system file edits"),
            PermissionRule("FileEdit", "**/.env*", "No .env file edits"),
            PermissionRule("FileWrite", "**/.env*", "No .env file creation"),
            PermissionRule("Bash", "git push *--force*", "No force pushes"),
            PermissionRule("Bash", "npm publish*", "No publishing"),
        ],
        allow=[
            PermissionRule("Read", "**", "Allow reading all files"),
        ],
    ),
    "standard": PermissionPolicy(
        deny=[
            PermissionRule("Bash", "rm -rf /*", "No root deletion"),
            PermissionRule("Bash", "sudo *", "No sudo commands"),
            PermissionRule("FileEdit", "/etc/**", "No system file edits"),
            PermissionRule("Bash", "git push *--force*", "No force pushes"),
        ],
        allow=[
            PermissionRule("Read", "**", "Allow reading all files"),
            PermissionRule("Bash", "git *", "Allow git commands"),
            PermissionRule("Bash", "npm *", "Allow npm commands"),
            PermissionRule("Bash", "python *", "Allow python commands"),
        ],
    ),
    "minimal": PermissionPolicy(
        deny=[
            PermissionRule("Bash", "rm -rf /*", "No root deletion"),
            PermissionRule("Bash", "sudo *", "No sudo commands"),
        ],
    ),
}


def get_preset(name: str) -> PermissionPolicy | None:
    """Get a named permission preset."""
    return _PRESETS.get(name)


def list_presets() -> list[str]:
    """List available preset names."""
    return list(_PRESETS.keys())


def apply_policy(project_dir: str | Path, policy: PermissionPolicy,
                 merge: bool = True) -> None:
    """Write permission policy to .claude/claudeconfig.json."""
    project = Path(project_dir)
    claude_dir = project / ".claude"
    claude_dir.mkdir(exist_ok=True)
    config_path = claude_dir / "claudeconfig.json"

    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {}

    policy_data = policy.to_config()

    if merge and "permissions" in config:
        existing = config["permissions"]
        # Merge deny lists (deduplicate by tool+pattern)
        existing_deny = {(r["tool"], r["pattern"]) for r in existing.get("deny", [])}
        for rule in policy_data.get("deny", []):
            key = (rule["tool"], rule["pattern"])
            if key not in existing_deny:
                existing.setdefault("deny", []).append(rule)

        # Merge allow lists
        existing_allow = {(r["tool"], r["pattern"]) for r in existing.get("allow", [])}
        for rule in policy_data.get("allow", []):
            key = (rule["tool"], rule["pattern"])
            if key not in existing_allow:
                existing.setdefault("allow", []).append(rule)
    else:
        config["permissions"] = policy_data

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def format_policy(policy: PermissionPolicy) -> str:
    """Format a policy for display."""
    lines = []
    if policy.deny:
        lines.append("  Deny rules:")
        for r in policy.deny:
            lines.append(f"    ⛔ {r.tool}: {r.pattern}")
            if r.description:
                lines.append(f"       {r.description}")
    if policy.allow:
        lines.append("  Allow rules:")
        for r in policy.allow:
            lines.append(f"    ✓ {r.tool}: {r.pattern}")
            if r.description:
                lines.append(f"       {r.description}")
    return "\n".join(lines)
