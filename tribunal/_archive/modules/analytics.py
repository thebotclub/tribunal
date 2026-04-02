"""Cost analytics — aggregate cost data across sessions and projects.

Provides analytics over Tribunal's cost tracking data:
- Session cost history with trends
- Daily/weekly/monthly aggregation
- Per-model cost breakdown
- Cost anomaly detection
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cost import load_state


@dataclass
class CostPeriod:
    """Cost data for a specific time period."""

    period: str  # e.g. "2026-04-02", "2026-W14", "2026-04"
    total_usd: float = 0.0
    session_count: int = 0
    models: dict[str, float] = field(default_factory=dict)

    @property
    def avg_session_cost(self) -> float:
        if self.session_count == 0:
            return 0.0
        return self.total_usd / self.session_count


@dataclass
class CostAnalytics:
    """Aggregated cost analytics."""

    total_usd: float = 0.0
    session_count: int = 0
    daily: list[CostPeriod] = field(default_factory=list)
    by_model: dict[str, float] = field(default_factory=dict)
    trend: str = ""  # "rising", "falling", "stable", "insufficient_data"
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_usd": self.total_usd,
            "session_count": self.session_count,
            "daily": [
                {
                    "period": d.period,
                    "total_usd": d.total_usd,
                    "session_count": d.session_count,
                    "avg_session_cost": d.avg_session_cost,
                }
                for d in self.daily
            ],
            "by_model": self.by_model,
            "trend": self.trend,
            "anomalies": self.anomalies,
        }


def _load_cost_history(cwd: str) -> list[dict[str, Any]]:
    """Load cost history from audit log entries."""
    audit_path = Path(cwd) / ".tribunal" / "audit.jsonl"
    if not audit_path.is_file():
        return []

    entries = []
    for line in audit_path.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def analyze_costs(cwd: str) -> CostAnalytics:
    """Analyze cost data from state and audit log."""
    state = load_state(cwd)
    analytics = CostAnalytics()

    # Get daily costs from state
    daily_costs = state.get("daily_costs", {})
    if not daily_costs:
        analytics.trend = "insufficient_data"
        return analytics

    # Build daily periods
    for date_str in sorted(daily_costs.keys()):
        cost = daily_costs[date_str]
        period = CostPeriod(
            period=date_str,
            total_usd=cost,
            session_count=1,
        )
        analytics.daily.append(period)
        analytics.total_usd += cost

    analytics.session_count = len(analytics.daily)

    # Per-model costs from state
    model_costs = state.get("model_costs", {})
    if model_costs:
        analytics.by_model = dict(model_costs)
    elif model := state.get("model"):
        analytics.by_model[model] = analytics.total_usd

    # Trend detection
    if len(analytics.daily) >= 3:
        recent = [d.total_usd for d in analytics.daily[-3:]]
        if recent[-1] > recent[0] * 1.2:
            analytics.trend = "rising"
        elif recent[-1] < recent[0] * 0.8:
            analytics.trend = "falling"
        else:
            analytics.trend = "stable"
    else:
        analytics.trend = "insufficient_data"

    # Anomaly detection (simple: flag days > 2x average)
    if len(analytics.daily) >= 3:
        avg = analytics.total_usd / len(analytics.daily)
        for d in analytics.daily:
            if d.total_usd > avg * 2 and avg > 0:
                analytics.anomalies.append(
                    f"{d.period}: ${d.total_usd:.2f} (>{2 * avg:.2f} avg)"
                )

    return analytics


def format_analytics(analytics: CostAnalytics) -> str:
    """Format cost analytics for display."""
    lines = ["\n  ⚖  Tribunal Cost Analytics\n"]

    lines.append(f"  Total spend: ${analytics.total_usd:.4f}")
    lines.append(f"  Sessions:    {analytics.session_count}")
    if analytics.session_count > 0:
        avg = analytics.total_usd / analytics.session_count
        lines.append(f"  Avg/session: ${avg:.4f}")

    # Trend
    trend_icons = {
        "rising": "📈",
        "falling": "📉",
        "stable": "➡️",
        "insufficient_data": "❓",
    }
    icon = trend_icons.get(analytics.trend, "")
    lines.append(f"\n  Trend: {icon} {analytics.trend}")

    # Model breakdown
    if analytics.by_model:
        lines.append("\n  By model:")
        for model, cost in sorted(analytics.by_model.items(), key=lambda x: -x[1]):
            pct = (cost / analytics.total_usd * 100) if analytics.total_usd else 0
            lines.append(f"    {model}: ${cost:.4f} ({pct:.0f}%)")

    # Daily history (last 7 days)
    if analytics.daily:
        lines.append("\n  Daily history (recent):")
        for d in analytics.daily[-7:]:
            bar_width = min(int(d.total_usd * 100), 30)
            bar = "█" * bar_width if bar_width > 0 else "▏"
            lines.append(f"    {d.period}  ${d.total_usd:.4f}  {bar}")

    # Anomalies
    if analytics.anomalies:
        lines.append("\n  ⚠️  Cost anomalies:")
        for a in analytics.anomalies:
            lines.append(f"    {a}")

    lines.append("")
    return "\n".join(lines)
