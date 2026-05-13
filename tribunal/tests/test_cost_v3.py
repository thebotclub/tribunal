"""Tests for tribunal.cost (v3 -- cross-agent, event-store driven)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tribunal.cost import (
    CostCaps,
    CostWindow,
    aggregate,
    check_caps,
    format_report,
    hourly_buckets,
    load_caps,
    save_caps,
    session_spend,
)
from tribunal.events.schema import new_event
from tribunal.events.store import EventStore, _parse_epoch_ms


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    s = EventStore(db_path=tmp_path / "events.db")
    yield s
    s.close()


def _cost_event(
    *,
    usd: float,
    agent: str = "claude-code",
    model: str = "claude-3.5-sonnet",
    session_id: str = "s-1",
    user_id: str = "u-1",
    repo_path: str = "owner/repo",
    ts: str = "2026-05-10T12:00:00Z",
) -> dict:
    return new_event(
        agent=agent,
        agent_version="1.0.0",
        session_id=session_id,
        user_id=user_id,
        event_type="cost.recorded",
        repo_path=repo_path,
        ts=ts,
        cost={"usd": usd, "model": model, "input_tokens": 100, "output_tokens": 50},
    )


# -- aggregate() --------------------------------------------------------------


def test_aggregate_sums_across_agents(store: EventStore) -> None:
    store.insert(_cost_event(usd=0.50, agent="claude-code", session_id="a"))
    store.insert(_cost_event(usd=0.25, agent="cursor", session_id="b"))
    store.insert(_cost_event(usd=1.00, agent="cursor", session_id="c"))
    win = aggregate(store, since_epoch_ms=0)
    assert isinstance(win, CostWindow)
    assert win.total_usd == pytest.approx(1.75)
    assert win.event_count == 3
    assert win.by_agent == {
        "claude-code": pytest.approx(0.50),
        "cursor": pytest.approx(1.25),
    }


def test_aggregate_filters_by_user_and_repo(store: EventStore) -> None:
    store.insert(_cost_event(usd=1.0, user_id="u-1", repo_path="acme/a"))
    store.insert(
        _cost_event(usd=2.0, user_id="u-2", repo_path="acme/a", session_id="s-2")
    )
    store.insert(
        _cost_event(usd=3.0, user_id="u-1", repo_path="acme/b", session_id="s-3")
    )
    win = aggregate(store, since_epoch_ms=0, user_id="u-1")
    assert win.total_usd == pytest.approx(4.0)
    win2 = aggregate(store, since_epoch_ms=0, user_id="u-1", repo_path="acme/a")
    assert win2.total_usd == pytest.approx(1.0)


def test_aggregate_ignores_non_cost_events(store: EventStore) -> None:
    store.insert(_cost_event(usd=0.5))
    store.insert(
        new_event(
            agent="claude-code",
            agent_version="1.0.0",
            session_id="s-2",
            user_id="u-1",
            event_type="prompt.submitted",
            payload={"prompt": "hi"},
            cost={"usd": 99.0, "model": "x"},  # should be ignored: wrong event_type
        )
    )
    win = aggregate(store, since_epoch_ms=0)
    assert win.total_usd == pytest.approx(0.5)


def test_aggregate_time_window(store: EventStore) -> None:
    early = _cost_event(usd=1.0, ts="2026-05-01T00:00:00Z")
    late = _cost_event(usd=2.0, ts="2026-05-10T00:00:00Z", session_id="s-2")
    store.insert(early)
    store.insert(late)
    cutoff = _parse_epoch_ms("2026-05-05T00:00:00Z")
    win = aggregate(store, since_epoch_ms=cutoff)
    assert win.total_usd == pytest.approx(2.0)


# -- session_spend / hourly_buckets -------------------------------------------


def test_session_spend_aggregates_one_session(store: EventStore) -> None:
    store.insert(_cost_event(usd=0.1, session_id="s-1"))
    store.insert(_cost_event(usd=0.3, session_id="s-1"))
    store.insert(_cost_event(usd=9.0, session_id="other"))
    assert session_spend(store, "s-1") == pytest.approx(0.4)
    assert session_spend(store, "missing") == 0.0


def test_hourly_buckets_groups_correctly(store: EventStore) -> None:
    # Two events in the same hour, one in the next hour
    store.insert(_cost_event(usd=0.10, ts="2026-05-10T12:05:00Z", session_id="a"))
    store.insert(_cost_event(usd=0.20, ts="2026-05-10T12:55:00Z", session_id="b"))
    store.insert(_cost_event(usd=0.50, ts="2026-05-10T13:01:00Z", session_id="c"))

    buckets = hourly_buckets(store, since_epoch_ms=0)
    assert len(buckets) == 2
    # First hour bucket
    assert buckets[0]["total_usd"] == pytest.approx(0.30)
    assert buckets[0]["events"] == 2
    assert buckets[1]["total_usd"] == pytest.approx(0.50)


# -- check_caps() -------------------------------------------------------------


def test_check_caps_allow_when_under_warn(store: EventStore) -> None:
    store.insert(_cost_event(usd=0.10, session_id="s-1"))
    caps = CostCaps(session_usd=10.0, warn_at_fraction=0.80)
    d = check_caps(store, caps, user_id="u-1", session_id="s-1")
    assert d.action == "allow"


def test_check_caps_warn_at_threshold(store: EventStore) -> None:
    store.insert(_cost_event(usd=8.50, session_id="s-1"))  # 85% of 10
    caps = CostCaps(session_usd=10.0, warn_at_fraction=0.80)
    d = check_caps(store, caps, user_id="u-1", session_id="s-1")
    assert d.action == "warn"
    assert d.window == "session"
    assert 0.80 <= d.fraction <= 1.0


def test_check_caps_blocks_at_hard_cap(store: EventStore) -> None:
    store.insert(_cost_event(usd=10.0, session_id="s-1"))
    caps = CostCaps(session_usd=10.0)
    d = check_caps(store, caps, user_id="u-1", session_id="s-1")
    assert d.action == "block"
    assert "session" in d.window.lower()
    assert "10.00" in d.message


def test_check_caps_daily_window(store: EventStore) -> None:
    import time

    now_ms = int(time.time() * 1000)
    # An event 1 hour ago
    one_hour_ago_ms = now_ms - 3600 * 1000
    from datetime import datetime, timezone

    ts = (
        datetime.fromtimestamp(one_hour_ago_ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    store.insert(_cost_event(usd=50.0, session_id="s-1", ts=ts))
    caps = CostCaps(daily_usd=40.0)
    d = check_caps(store, caps, user_id="u-1", now_epoch_ms=now_ms)
    assert d.action == "block"
    assert d.window == "day"


def test_check_caps_zero_means_unlimited(store: EventStore) -> None:
    store.insert(_cost_event(usd=999.0, session_id="s-1"))
    caps = CostCaps()  # all zero
    d = check_caps(store, caps, user_id="u-1", session_id="s-1")
    assert d.action == "allow"


def test_check_caps_session_takes_precedence(store: EventStore) -> None:
    store.insert(_cost_event(usd=12.0, session_id="s-1"))
    caps = CostCaps(session_usd=10.0, daily_usd=1000.0)
    d = check_caps(store, caps, user_id="u-1", session_id="s-1")
    assert d.action == "block"
    assert d.window == "session"


def test_overrides_apply_per_user_repo(store: EventStore) -> None:
    store.insert(_cost_event(usd=5.0, session_id="s-1", repo_path="acme/secret"))
    base = CostCaps(
        session_usd=100.0,
        overrides={"u-1::acme/secret": CostCaps(session_usd=1.0)},
    )
    d = check_caps(
        store, base, user_id="u-1", repo_path="acme/secret", session_id="s-1"
    )
    assert d.action == "block"


# -- Config IO ----------------------------------------------------------------


def test_load_caps_missing_file(tmp_path: Path) -> None:
    c = load_caps(path=tmp_path / "nope.json")
    assert c.session_usd == 0
    assert c.daily_usd == 0


def test_save_and_load_caps_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "caps.json"
    caps = CostCaps(
        session_usd=5.0,
        daily_usd=50.0,
        weekly_usd=200.0,
        warn_at_fraction=0.75,
        overrides={"u-1::repo": CostCaps(daily_usd=10.0)},
    )
    save_caps(caps, path=p)
    loaded = load_caps(path=p)
    assert loaded.session_usd == 5.0
    assert loaded.daily_usd == 50.0
    assert loaded.weekly_usd == 200.0
    assert loaded.warn_at_fraction == 0.75
    assert "u-1::repo" in loaded.overrides
    assert loaded.overrides["u-1::repo"].daily_usd == 10.0


def test_format_report_includes_breakdowns(store: EventStore) -> None:
    store.insert(_cost_event(usd=1.0, agent="claude-code"))
    store.insert(_cost_event(usd=2.0, agent="cursor", session_id="s-2"))
    win = aggregate(store, since_epoch_ms=0)
    win.window = "day"
    report = format_report(win)
    assert "claude-code" in report
    assert "cursor" in report
    assert "$3.0000" in report
