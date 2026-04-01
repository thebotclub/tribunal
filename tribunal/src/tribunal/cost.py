"""Cost tracking and budget enforcement.

Reads Claude Code's per-session cost data and enforces spending limits.
Budgets can be set per-session, daily, or weekly via .tribunal/rules.yaml
or the CLI (tribunal cost budget set <amount>).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CostSnapshot:
    """Point-in-time cost information for a session."""

    session_id: str = ""
    session_cost_usd: float = 0.0
    daily_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class CostBudget:
    """Budget limits for cost enforcement."""

    session_usd: float = 0.0  # 0 = unlimited
    daily_usd: float = 0.0
    warn_at_percent: float = 80.0  # warn when hitting this % of budget


def load_state(cwd: str) -> dict[str, Any]:
    """Load .tribunal/state.json from the project directory."""
    from .io import locked_read_json
    state_path = Path(os.path.join(cwd, ".tribunal", "state.json"))
    return locked_read_json(state_path)


def save_state(cwd: str, state: dict[str, Any]) -> None:
    """Save state to .tribunal/state.json (atomic write with locking)."""
    from .io import atomic_write_json
    state_path = Path(os.path.join(cwd, ".tribunal", "state.json"))
    atomic_write_json(state_path, state)


def get_cost_snapshot(cwd: str) -> CostSnapshot:
    """Read current cost data from state."""
    state = load_state(cwd)
    return CostSnapshot(
        session_id=state.get("session_id", ""),
        session_cost_usd=state.get("session_cost_usd", 0.0),
        daily_cost_usd=state.get("daily_cost_usd", 0.0),
        input_tokens=state.get("input_tokens", 0),
        output_tokens=state.get("output_tokens", 0),
        model=state.get("model", ""),
        timestamp=state.get("cost_updated_at", time.time()),
    )


def get_budget(cwd: str) -> CostBudget:
    """Read budget configuration from state."""
    state = load_state(cwd)
    budget = state.get("budget", {})
    return CostBudget(
        session_usd=budget.get("session_usd", 0.0),
        daily_usd=budget.get("daily_usd", 0.0),
        warn_at_percent=budget.get("warn_at_percent", 80.0),
    )


def set_budget(cwd: str, session_usd: float = 0.0, daily_usd: float = 0.0) -> None:
    """Set budget limits in state."""
    state = load_state(cwd)
    state.setdefault("budget", {})
    if session_usd > 0:
        state["budget"]["session_usd"] = session_usd
    if daily_usd > 0:
        state["budget"]["daily_usd"] = daily_usd
    # Also set the legacy field for backward compat with Phase 1's cost-exceeded condition
    if session_usd > 0:
        state["cost_budget_usd"] = session_usd
    save_state(cwd, state)


def update_session_cost(cwd: str, cost_usd: float, session_id: str = "",
                        model: str = "", input_tokens: int = 0,
                        output_tokens: int = 0) -> None:
    """Update session cost tracking in state. Called by PostToolUse hooks."""
    state = load_state(cwd)
    state["session_cost_usd"] = cost_usd
    state["cost_updated_at"] = time.time()
    if session_id:
        state["session_id"] = session_id
    if model:
        state["model"] = model
    if input_tokens:
        state["input_tokens"] = input_tokens
    if output_tokens:
        state["output_tokens"] = output_tokens

    # Track daily costs
    today = time.strftime("%Y-%m-%d", time.gmtime())
    daily = state.get("daily_costs", {})
    daily[today] = daily.get(today, 0.0) + cost_usd
    state["daily_costs"] = daily
    state["daily_cost_usd"] = daily.get(today, 0.0)

    save_state(cwd, state)


@dataclass
class CostCheckResult:
    """Result of checking cost against budget."""

    exceeded: bool = False
    warning: bool = False
    message: str = ""
    session_cost: float = 0.0
    budget_limit: float = 0.0


def check_budget(cwd: str) -> CostCheckResult:
    """Check current costs against configured budgets."""
    snapshot = get_cost_snapshot(cwd)
    budget = get_budget(cwd)

    # Check session budget
    if budget.session_usd > 0:
        if snapshot.session_cost_usd >= budget.session_usd:
            return CostCheckResult(
                exceeded=True,
                message=f"Session cost ${snapshot.session_cost_usd:.2f} exceeds budget ${budget.session_usd:.2f}.",
                session_cost=snapshot.session_cost_usd,
                budget_limit=budget.session_usd,
            )
        warn_threshold = budget.session_usd * (budget.warn_at_percent / 100.0)
        if snapshot.session_cost_usd >= warn_threshold:
            return CostCheckResult(
                warning=True,
                message=f"Session cost ${snapshot.session_cost_usd:.2f} is at {snapshot.session_cost_usd / budget.session_usd * 100:.0f}% of ${budget.session_usd:.2f} budget.",
                session_cost=snapshot.session_cost_usd,
                budget_limit=budget.session_usd,
            )

    # Check daily budget
    if budget.daily_usd > 0:
        if snapshot.daily_cost_usd >= budget.daily_usd:
            return CostCheckResult(
                exceeded=True,
                message=f"Daily cost ${snapshot.daily_cost_usd:.2f} exceeds budget ${budget.daily_usd:.2f}.",
                session_cost=snapshot.daily_cost_usd,
                budget_limit=budget.daily_usd,
            )

    return CostCheckResult(
        session_cost=snapshot.session_cost_usd,
        budget_limit=budget.session_usd,
    )


def format_cost_report(cwd: str) -> str:
    """Generate a human-readable cost report."""
    snapshot = get_cost_snapshot(cwd)
    budget = get_budget(cwd)
    state = load_state(cwd)

    lines = ["\n  ⚖  Tribunal Cost Report\n"]

    if snapshot.session_cost_usd > 0:
        lines.append(f"  Session:  ${snapshot.session_cost_usd:.4f}")
        if snapshot.model:
            lines.append(f"  Model:    {snapshot.model}")
        if snapshot.input_tokens:
            lines.append(f"  Tokens:   {snapshot.input_tokens:,} in / {snapshot.output_tokens:,} out")
    else:
        lines.append("  Session:  no cost data yet")

    lines.append("")

    # Budget
    if budget.session_usd > 0:
        pct = (snapshot.session_cost_usd / budget.session_usd * 100) if budget.session_usd else 0
        bar_len = 20
        filled = min(int(pct / 100 * bar_len), bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"  Budget:   ${budget.session_usd:.2f} per session")
        lines.append(f"  Usage:    [{bar}] {pct:.0f}%")
    else:
        lines.append("  Budget:   not set (tribunal cost budget set <amount>)")

    # Daily costs
    daily = state.get("daily_costs", {})
    if daily:
        lines.append("")
        lines.append("  Daily Costs:")
        for day in sorted(daily.keys())[-7:]:  # last 7 days
            lines.append(f"    {day}: ${daily[day]:.4f}")

    lines.append("")
    return "\n".join(lines)
