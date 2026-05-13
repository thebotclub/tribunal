"""Cross-agent cost aggregation and cap enforcement.

This is the v3 rewrite of the legacy ``cost`` module. The v2 cost module
read ``.tribunal/state.json`` (a Claude-Code–specific file) directly. The
v3 module reads from the unified :class:`tribunal.events.store.EventStore`
so it works across every adapter (Claude Code, Cursor, Copilot, Codex,
custom).

Design:

  - Spend is whatever the agents reported via ``cost.recorded`` events.
    The daemon receives those, persists them, and we just SUM here.
  - Aggregation is per ``(user_id, repo_path, agent)`` and per *hour*.
    Hourly buckets are precise enough for budget enforcement and cheap to
    query against the indexed ``epoch_ms`` column.
  - Caps come from a tiny config (loaded from ``~/.tribunal/caps.yaml`` or
    a passed-in dict). They support session, daily, weekly, and monthly
    windows.
  - ``check_caps()`` returns a :class:`CapDecision` the policy engine can
    surface to the user or block on.

Wire format expected for a ``cost.recorded`` event::

    {
      "event_type": "cost.recorded",
      "cost": {"usd": 0.42, "model": "...", "input_tokens": N,
               "output_tokens": M},
      ...
    }
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from tribunal.events.store import EventStore

# ── Public data classes ──────────────────────────────────────────────────────


@dataclass
class CostWindow:
    """A summed cost over a time window, broken down by agent."""

    window: str  # "session" | "hour" | "day" | "week" | "month"
    start_epoch_ms: int
    end_epoch_ms: int
    total_usd: float = 0.0
    by_agent: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    by_repo: dict[str, float] = field(default_factory=dict)
    event_count: int = 0


@dataclass
class CostCaps:
    """Spending caps the user has set. ``0`` means "no cap"."""

    session_usd: float = 0.0
    daily_usd: float = 0.0
    weekly_usd: float = 0.0
    monthly_usd: float = 0.0
    #: Soft warning is emitted once spend crosses this fraction of the cap.
    warn_at_fraction: float = 0.80
    #: Per-(user, repo) overrides, keyed by ``"user_id::repo_path"``.
    overrides: dict[str, "CostCaps"] = field(default_factory=dict)


@dataclass
class CapDecision:
    """Result of evaluating spend against caps.

    ``action`` is one of:
      - ``"allow"``  → under the soft warn threshold
      - ``"warn"``   → between soft and hard cap; surface but do not block
      - ``"block"``  → hard cap exceeded; policy engine should block
    """

    action: str
    window: str  # which window tripped (or "" if allow)
    cap_usd: float = 0.0
    spent_usd: float = 0.0
    fraction: float = 0.0
    message: str = ""


# ── Aggregation queries ──────────────────────────────────────────────────────


def aggregate(
    store: EventStore,
    *,
    since_epoch_ms: int,
    until_epoch_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    repo_path: Optional[str] = None,
    agent: Optional[str] = None,
) -> CostWindow:
    """Sum every ``cost.recorded`` event in the window, with breakdowns.

    The query touches only the indexed columns (``epoch_ms``, ``event_type``,
    optionally ``user_id`` / ``repo_path`` / ``agent``).
    """
    until_epoch_ms = until_epoch_ms if until_epoch_ms is not None else _now_ms()
    where = ["event_type = 'cost.recorded'", "epoch_ms >= ?", "epoch_ms < ?"]
    args: list[Any] = [since_epoch_ms, until_epoch_ms]
    if user_id:
        where.append("user_id = ?")
        args.append(user_id)
    if repo_path:
        where.append("repo_path = ?")
        args.append(repo_path)
    if agent:
        where.append("agent = ?")
        args.append(agent)
    sql_where = " WHERE " + " AND ".join(where)

    with store._lock:  # noqa: SLF001 — we own the store
        conn: sqlite3.Connection = store._conn  # noqa: SLF001
        rows = conn.execute(
            f"""
            SELECT agent, cost_model, repo_path, cost_usd
            FROM events
            {sql_where}
            """,
            args,
        ).fetchall()

    win = CostWindow(
        window="custom",
        start_epoch_ms=since_epoch_ms,
        end_epoch_ms=until_epoch_ms,
    )
    for row in rows:
        usd = float(row["cost_usd"] or 0.0)
        if usd <= 0:
            continue
        win.total_usd += usd
        win.event_count += 1
        agent_key = row["agent"] or "unknown"
        win.by_agent[agent_key] = win.by_agent.get(agent_key, 0.0) + usd
        model_key = row["cost_model"] or "unknown"
        win.by_model[model_key] = win.by_model.get(model_key, 0.0) + usd
        repo_key = row["repo_path"] or ""
        if repo_key:
            win.by_repo[repo_key] = win.by_repo.get(repo_key, 0.0) + usd
    return win


def session_spend(
    store: EventStore,
    session_id: str,
) -> float:
    """Total spend for a single session across all agents."""
    with store._lock:  # noqa: SLF001
        row = store._conn.execute(  # noqa: SLF001
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS total
            FROM events
            WHERE event_type = 'cost.recorded' AND session_id = ?
            """,
            (session_id,),
        ).fetchone()
    return float(row["total"] or 0.0)


def hourly_buckets(
    store: EventStore,
    *,
    since_epoch_ms: int,
    until_epoch_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    repo_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Per-hour ``(user, repo, agent)`` totals for dashboard sparklines.

    Returns a list of dicts sorted oldest→newest::

        [{"hour_epoch_ms": 1717..., "user_id": "u1", "repo_path": "...",
          "agent": "cursor", "total_usd": 0.42, "events": 5}, ...]
    """
    until_epoch_ms = until_epoch_ms if until_epoch_ms is not None else _now_ms()
    where = ["event_type = 'cost.recorded'", "epoch_ms >= ?", "epoch_ms < ?"]
    args: list[Any] = [since_epoch_ms, until_epoch_ms]
    if user_id:
        where.append("user_id = ?")
        args.append(user_id)
    if repo_path:
        where.append("repo_path = ?")
        args.append(repo_path)
    sql_where = " WHERE " + " AND ".join(where)

    with store._lock:  # noqa: SLF001
        rows = store._conn.execute(  # noqa: SLF001
            f"""
            SELECT
                (epoch_ms / 3600000) * 3600000 AS hour_bucket,
                user_id,
                repo_path,
                agent,
                COALESCE(SUM(cost_usd), 0) AS total_usd,
                COUNT(*) AS events
            FROM events
            {sql_where}
            GROUP BY hour_bucket, user_id, repo_path, agent
            ORDER BY hour_bucket
            """,
            args,
        ).fetchall()
    return [
        {
            "hour_epoch_ms": int(r["hour_bucket"]),
            "user_id": r["user_id"],
            "repo_path": r["repo_path"],
            "agent": r["agent"],
            "total_usd": float(r["total_usd"] or 0.0),
            "events": int(r["events"]),
        }
        for r in rows
    ]


# ── Cap evaluation ───────────────────────────────────────────────────────────


def check_caps(
    store: EventStore,
    caps: CostCaps,
    *,
    user_id: str,
    repo_path: Optional[str] = None,
    session_id: Optional[str] = None,
    now_epoch_ms: Optional[int] = None,
) -> CapDecision:
    """Evaluate spend against every configured cap, return the most-severe.

    Order of evaluation: session → day → week → month. We surface the
    *first* cap that's exceeded (block) or warning (warn). If none, allow.
    """
    now_ms = now_epoch_ms if now_epoch_ms is not None else _now_ms()
    effective = _apply_overrides(caps, user_id=user_id, repo_path=repo_path)

    # ── session ──
    if effective.session_usd > 0 and session_id:
        spent = session_spend(store, session_id)
        decision = _evaluate(
            window="session",
            spent=spent,
            cap=effective.session_usd,
            warn_at=effective.warn_at_fraction,
        )
        if decision.action != "allow":
            return decision

    # ── day / week / month ──
    for window_name, hours, cap_value in (
        ("day", 24, effective.daily_usd),
        ("week", 24 * 7, effective.weekly_usd),
        ("month", 24 * 30, effective.monthly_usd),
    ):
        if cap_value <= 0:
            continue
        since_ms = now_ms - hours * 3600 * 1000
        spent = aggregate(
            store,
            since_epoch_ms=since_ms,
            until_epoch_ms=now_ms,
            user_id=user_id,
            repo_path=repo_path,
        ).total_usd
        decision = _evaluate(
            window=window_name,
            spent=spent,
            cap=cap_value,
            warn_at=effective.warn_at_fraction,
        )
        if decision.action != "allow":
            return decision

    return CapDecision(action="allow", window="")


def _evaluate(*, window: str, spent: float, cap: float, warn_at: float) -> CapDecision:
    if cap <= 0:
        return CapDecision(action="allow", window="")
    fraction = spent / cap if cap > 0 else 0.0
    if spent >= cap:
        return CapDecision(
            action="block",
            window=window,
            cap_usd=cap,
            spent_usd=spent,
            fraction=fraction,
            message=(
                f"{window.title()} spend ${spent:.2f} has reached the "
                f"${cap:.2f} cap — blocking further LLM calls."
            ),
        )
    if fraction >= warn_at:
        return CapDecision(
            action="warn",
            window=window,
            cap_usd=cap,
            spent_usd=spent,
            fraction=fraction,
            message=(
                f"{window.title()} spend ${spent:.2f} is at "
                f"{int(fraction * 100)}% of the ${cap:.2f} cap."
            ),
        )
    return CapDecision(
        action="allow",
        window=window,
        cap_usd=cap,
        spent_usd=spent,
        fraction=fraction,
    )


def _apply_overrides(
    caps: CostCaps,
    *,
    user_id: str,
    repo_path: Optional[str],
) -> CostCaps:
    if not caps.overrides:
        return caps
    keys = [f"{user_id}::{repo_path or ''}", f"{user_id}::*", f"*::{repo_path or ''}"]
    for k in keys:
        ovr = caps.overrides.get(k)
        if ovr is not None:
            # Override fields that are set; fall back to base values.
            return CostCaps(
                session_usd=ovr.session_usd or caps.session_usd,
                daily_usd=ovr.daily_usd or caps.daily_usd,
                weekly_usd=ovr.weekly_usd or caps.weekly_usd,
                monthly_usd=ovr.monthly_usd or caps.monthly_usd,
                warn_at_fraction=ovr.warn_at_fraction or caps.warn_at_fraction,
            )
    return caps


# ── Config IO ────────────────────────────────────────────────────────────────


def default_caps_path() -> Path:
    return Path.home() / ".tribunal" / "caps.json"


def load_caps(path: Optional[Path] = None) -> CostCaps:
    """Read caps from disk; returns an empty :class:`CostCaps` if missing.

    The file is JSON for now (no YAML dep). Schema::

        {
          "session_usd": 5.00,
          "daily_usd":  50.00,
          "weekly_usd": 200.00,
          "warn_at_fraction": 0.80,
          "overrides": {"u-1::owner/repo": {"daily_usd": 10}}
        }
    """
    path = path or default_caps_path()
    if not path.exists():
        return CostCaps()
    data = json.loads(path.read_text(encoding="utf-8"))
    overrides_raw = data.get("overrides") or {}
    overrides = {
        k: CostCaps(
            session_usd=float(v.get("session_usd") or 0),
            daily_usd=float(v.get("daily_usd") or 0),
            weekly_usd=float(v.get("weekly_usd") or 0),
            monthly_usd=float(v.get("monthly_usd") or 0),
            warn_at_fraction=float(v.get("warn_at_fraction") or 0.80),
        )
        for k, v in overrides_raw.items()
    }
    return CostCaps(
        session_usd=float(data.get("session_usd") or 0),
        daily_usd=float(data.get("daily_usd") or 0),
        weekly_usd=float(data.get("weekly_usd") or 0),
        monthly_usd=float(data.get("monthly_usd") or 0),
        warn_at_fraction=float(data.get("warn_at_fraction") or 0.80),
        overrides=overrides,
    )


def save_caps(caps: CostCaps, path: Optional[Path] = None) -> None:
    path = path or default_caps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "session_usd": caps.session_usd,
        "daily_usd": caps.daily_usd,
        "weekly_usd": caps.weekly_usd,
        "monthly_usd": caps.monthly_usd,
        "warn_at_fraction": caps.warn_at_fraction,
    }
    if caps.overrides:
        payload["overrides"] = {
            k: {
                "session_usd": v.session_usd,
                "daily_usd": v.daily_usd,
                "weekly_usd": v.weekly_usd,
                "monthly_usd": v.monthly_usd,
                "warn_at_fraction": v.warn_at_fraction,
            }
            for k, v in caps.overrides.items()
        }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def format_report(window: CostWindow) -> str:
    """Human-readable summary used by ``tribunal cost``."""
    lines = ["", "  Tribunal Cost", ""]
    lines.append(f"  Window:   {window.window}")
    lines.append(f"  Events:   {window.event_count}")
    lines.append(f"  Total:    ${window.total_usd:.4f}")
    if window.by_agent:
        lines.append("")
        lines.append("  By agent:")
        for a, v in sorted(window.by_agent.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {a:<14} ${v:.4f}")
    if window.by_model:
        lines.append("")
        lines.append("  By model:")
        for m, v in sorted(window.by_model.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {m:<24} ${v:.4f}")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "CostWindow",
    "CostCaps",
    "CapDecision",
    "aggregate",
    "session_spend",
    "hourly_buckets",
    "check_caps",
    "load_caps",
    "save_caps",
    "default_caps_path",
    "format_report",
]
