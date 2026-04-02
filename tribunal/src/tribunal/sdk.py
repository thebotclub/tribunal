"""Tribunal SDK — programmatic Python API for embedding governance.

Use this module to integrate Tribunal into custom tooling, CI pipelines,
or automated workflows without going through the CLI.

Example:
    from tribunal.sdk import TribunalSDK

    sdk = TribunalSDK("/path/to/project")
    result = sdk.evaluate("PreToolUse", tool_name="FileEdit", tool_input={"path": "app.py"})
    if result.blocked:
        print(f"Blocked: {result.message}")

    # Cost tracking
    snapshot = sdk.cost_snapshot()
    print(f"Session cost: ${snapshot['session_cost_usd']:.4f}")

    # Rule management
    rules = sdk.list_rules()
    sdk.install_pack("soc2")

    # Health check
    health = sdk.doctor()
    print(f"Issues: {health['issues']}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    """Result of evaluating an event through Tribunal rules."""

    allowed: bool
    blocked: bool
    messages: list[str]
    triggered_rules: list[str]
    verdict_context: str = ""

    @property
    def message(self) -> str:
        return "; ".join(self.messages) if self.messages else ""


class TribunalSDK:
    """Programmatic interface to Tribunal governance.

    All methods operate on the project at `cwd`.
    """

    def __init__(self, cwd: str | None = None):
        self.cwd = str(Path(cwd) if cwd else Path.cwd())

    # ── Rule Evaluation ───────────────────────────────────────────────────

    def evaluate(
        self,
        hook_event_name: str,
        tool_name: str = "",
        tool_input: dict[str, Any] | None = None,
        session_id: str = "sdk",
    ) -> EvalResult:
        """Evaluate a simulated event against all active rules.

        Returns an EvalResult with allow/block status and messages.
        """
        from .protocol import HookEvent
        from .rules import RuleEngine

        event = HookEvent(
            hook_event_name=hook_event_name,
            session_id=session_id,
            cwd=self.cwd,
            tool_name=tool_name,
            tool_input=tool_input or {},
        )

        rules_path = Path(self.cwd) / ".tribunal" / "rules.yaml"
        engine = RuleEngine.from_config(str(rules_path))
        verdict = engine.evaluate(event)

        # Extract messages from verdict reason/context
        messages = []
        if verdict.reason:
            messages.append(verdict.reason)
        if verdict.additional_context:
            messages.append(verdict.additional_context)

        return EvalResult(
            allowed=verdict.allow,
            blocked=not verdict.allow,
            messages=messages,
            triggered_rules=[],  # individual rule names not exposed by HookVerdict
            verdict_context=verdict.additional_context,
        )

    # ── Rules ─────────────────────────────────────────────────────────────

    def list_rules(self) -> list[dict[str, Any]]:
        """List all rules and their status."""
        from .rules import RuleEngine

        rules_path = Path(self.cwd) / ".tribunal" / "rules.yaml"
        engine = RuleEngine.from_config(str(rules_path))

        return [
            {
                "name": r.name,
                "trigger": r.trigger,
                "action": r.action,
                "enabled": r.enabled,
                "condition": r.condition,
                "message": r.message,
                "require_tool": r.require_tool,
            }
            for r in engine.rules
        ]

    def install_pack(self, name: str, merge: bool = True) -> tuple[bool, list[str]]:
        """Install a rule pack."""
        from .packs import install_pack
        return install_pack(name, self.cwd, merge=merge)

    # ── Cost ──────────────────────────────────────────────────────────────

    def cost_snapshot(self) -> dict[str, Any]:
        """Get current cost tracking state."""
        from .cost import load_state
        return load_state(self.cwd)

    def set_budget(self, session_usd: float = 0, daily_usd: float = 0) -> None:
        """Set cost budget."""
        from .cost import set_budget
        set_budget(self.cwd, session_usd=session_usd, daily_usd=daily_usd)

    # ── Audit ─────────────────────────────────────────────────────────────

    def audit_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read recent audit log entries."""
        audit_path = Path(self.cwd) / ".tribunal" / "audit.jsonl"
        if not audit_path.is_file():
            return []
        lines = audit_path.read_text().strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def audit_stats(self) -> dict[str, Any]:
        """Get audit log statistics."""
        from .audit import audit_stats
        return audit_stats(str(Path(self.cwd) / ".tribunal" / "audit.jsonl"))

    def rotate_audit(self) -> bool:
        """Rotate the audit log. Returns True if rotated."""
        from .audit import rotate_audit_log
        audit_path = Path(self.cwd) / ".tribunal" / "audit.jsonl"
        return rotate_audit_log(audit_path)

    # ── Config ────────────────────────────────────────────────────────────

    def resolve_config(self) -> dict[str, Any]:
        """Resolve the full config cascade."""
        from .config import resolve_config
        from dataclasses import asdict
        return asdict(resolve_config(self.cwd))

    def validate_config(self) -> list[str]:
        """Validate project config. Returns list of errors (empty = valid)."""
        from .config import validate_config
        import yaml
        config_path = Path(self.cwd) / ".tribunal" / "config.yaml"
        if not config_path.is_file():
            return []
        data = yaml.safe_load(config_path.read_text()) or {}
        return validate_config(data)

    # ── Memory ────────────────────────────────────────────────────────────

    def memory_stats(self) -> dict[str, Any]:
        """Get memory capacity statistics."""
        from .memory import memory_stats
        return memory_stats(self.cwd)

    def inject_rules_as_memory(self) -> int:
        """Inject rules into Claude Code memory. Returns count."""
        from .memory import inject_rules_as_memory
        return len(inject_rules_as_memory(self.cwd))

    # ── Agents ────────────────────────────────────────────────────────────

    def active_agents(self) -> list[dict[str, Any]]:
        """Get active sub-agents."""
        from .agents import get_active_agents
        from dataclasses import asdict
        return [asdict(a) for a in get_active_agents(self.cwd)]

    def agent_trail(self, agent_id: str) -> list[dict[str, Any]]:
        """Get per-agent audit trail."""
        from .agents import get_agent_trail
        return get_agent_trail(self.cwd, agent_id)

    # ── Doctor ────────────────────────────────────────────────────────────

    def doctor(self) -> dict[str, Any]:
        """Run health checks. Returns dict with issues, warnings, and details."""
        import shutil
        import yaml

        project_dir = Path(self.cwd)
        issues = 0
        warnings = 0
        checks: list[dict[str, str]] = []

        # tribunal-gate on PATH
        if shutil.which("tribunal-gate"):
            checks.append({"check": "tribunal-gate", "status": "ok"})
        else:
            checks.append({"check": "tribunal-gate", "status": "missing"})
            issues += 1

        # .tribunal/ directory
        if (project_dir / ".tribunal").is_dir():
            checks.append({"check": ".tribunal/", "status": "ok"})
        else:
            checks.append({"check": ".tribunal/", "status": "missing"})
            issues += 1

        # rules.yaml
        rules_path = project_dir / ".tribunal" / "rules.yaml"
        if rules_path.is_file():
            try:
                data = yaml.safe_load(rules_path.read_text()) or {}
                rule_count = len(data.get("rules", {}))
                checks.append({"check": "rules.yaml", "status": "ok", "rules": str(rule_count)})
            except yaml.YAMLError:
                checks.append({"check": "rules.yaml", "status": "invalid"})
                issues += 1
        else:
            checks.append({"check": "rules.yaml", "status": "missing"})
            issues += 1

        # claudeconfig.json
        config_path = project_dir / ".claude" / "claudeconfig.json"
        if config_path.is_file():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                has_tribunal = "tribunal-gate" in json.dumps(config.get("hooks", {}))
                status = "ok" if has_tribunal else "no-tribunal-gate"
                checks.append({"check": "claudeconfig.json", "status": status})
                if not has_tribunal:
                    warnings += 1
            except (json.JSONDecodeError, OSError):
                checks.append({"check": "claudeconfig.json", "status": "invalid"})
                issues += 1
        else:
            checks.append({"check": "claudeconfig.json", "status": "missing"})
            issues += 1

        return {
            "issues": issues,
            "warnings": warnings,
            "checks": checks,
            "healthy": issues == 0,
        }
