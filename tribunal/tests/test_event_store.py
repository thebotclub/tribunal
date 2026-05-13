"""Tests for tribunal.events.store — local SQLite event store."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tribunal.events.schema import SCHEMA_VERSION, new_event, SchemaError
from tribunal.events.store import (
    EventStore,
    TimelineStats,
    _parse_epoch_ms,
    timeline_stats,
)


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    s = EventStore(db_path=tmp_path / "events.db")
    yield s
    s.close()


def _ev(**kwargs) -> dict:
    base = dict(
        agent="claude-code",
        agent_version="1.2.3",
        session_id="s-1",
        user_id="u-1",
        event_type="session.start",
    )
    base.update(kwargs)
    return new_event(**base)


# ── Basic insert/read ────────────────────────────────────────────────────────


def test_init_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "x" / "events.db"
    s = EventStore(db_path=db_path)
    assert db_path.exists()
    # PRAGMA user_version should be > 0
    conn = sqlite3.connect(str(db_path))
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v >= 1
    conn.close()
    s.close()


def test_insert_and_count(store: EventStore) -> None:
    assert store.count() == 0
    store.insert(_ev())
    assert store.count() == 1


def test_insert_is_idempotent_on_event_id(store: EventStore) -> None:
    e = _ev()
    store.insert(e)
    store.insert(e)  # same event_id, should be a no-op
    assert store.count() == 1


def test_insert_validates(store: EventStore) -> None:
    bad = {"agent": "claude-code"}  # missing required fields
    with pytest.raises(SchemaError):
        store.insert(bad)


def test_insert_many_skips_invalid(store: EventStore) -> None:
    good = _ev()
    bad = {"junk": True}
    n = store.insert_many([good, bad, _ev(session_id="s-2")])
    assert n == 2
    assert store.count() == 2


# ── Reads ────────────────────────────────────────────────────────────────────


def test_recent_returns_full_json(store: EventStore) -> None:
    e = _ev(payload={"prompt": "hello"})
    store.insert(e)
    rows = store.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["event_id"] == e["event_id"]
    assert rows[0]["payload"]["prompt"] == "hello"


def test_recent_filters_by_agent_and_type(store: EventStore) -> None:
    store.insert(_ev(agent="claude-code", session_id="a"))
    store.insert(_ev(agent="cursor", session_id="b"))
    store.insert(_ev(agent="cursor", event_type="prompt.submitted", session_id="c"))

    cursor_only = store.recent(agent="cursor")
    assert len(cursor_only) == 2

    prompts = store.recent(event_type="prompt.submitted")
    assert len(prompts) == 1
    assert prompts[0]["agent"] == "cursor"


def test_recent_orders_newest_first(store: EventStore) -> None:
    a = _ev(ts="2026-05-01T00:00:00Z", session_id="a")
    b = _ev(ts="2026-05-02T00:00:00Z", session_id="b")
    store.insert(a)
    store.insert(b)
    rows = store.recent()
    assert rows[0]["event_id"] == b["event_id"]
    assert rows[1]["event_id"] == a["event_id"]


def test_recent_since_filter(store: EventStore) -> None:
    a = _ev(ts="2026-05-01T00:00:00Z", session_id="a")
    b = _ev(ts="2026-05-02T00:00:00Z", session_id="b")
    store.insert(a)
    store.insert(b)
    cutoff = _parse_epoch_ms("2026-05-01T12:00:00Z")
    rows = store.recent(since_epoch_ms=cutoff)
    assert len(rows) == 1
    assert rows[0]["event_id"] == b["event_id"]


def test_agents_seen(store: EventStore) -> None:
    assert store.agents_seen() == []
    store.insert(_ev(agent="claude-code"))
    store.insert(_ev(agent="cursor", session_id="s-2"))
    store.insert(_ev(agent="cursor", session_id="s-3"))
    assert store.agents_seen() == ["claude-code", "cursor"]


# ── Outbox / cloud queuing ───────────────────────────────────────────────────


def test_outbox_is_empty_when_not_queued(store: EventStore) -> None:
    store.insert(_ev(), queue_for_cloud=False)
    assert store.outbox_pending() == []
    assert store.outbox_depth() == 0


def test_queue_for_cloud_adds_to_outbox(store: EventStore) -> None:
    e = _ev()
    store.insert(e, queue_for_cloud=True)
    pending = store.outbox_pending()
    assert len(pending) == 1
    assert pending[0]["event_id"] == e["event_id"]
    assert store.outbox_depth() == 1


def test_outbox_ack_removes_events(store: EventStore) -> None:
    e1 = _ev(session_id="s-1")
    e2 = _ev(session_id="s-2")
    store.insert(e1, queue_for_cloud=True)
    store.insert(e2, queue_for_cloud=True)
    assert store.outbox_depth() == 2
    store.outbox_ack([e1["event_id"]])
    assert store.outbox_depth() == 1
    remaining = store.outbox_pending()
    assert remaining[0]["event_id"] == e2["event_id"]


def test_outbox_fail_increments_attempts(store: EventStore) -> None:
    e = _ev()
    store.insert(e, queue_for_cloud=True)
    store.outbox_fail([e["event_id"]], "oops")
    # Inspect attempts directly
    with store._lock:
        row = store._conn.execute(
            "SELECT attempts, last_error FROM outbox WHERE event_id=?",
            (e["event_id"],),
        ).fetchone()
    assert row["attempts"] == 1
    assert row["last_error"] == "oops"


def test_outbox_ack_empty_is_noop(store: EventStore) -> None:
    store.outbox_ack([])
    store.outbox_fail([], "x")


# ── Stats ────────────────────────────────────────────────────────────────────


def test_timeline_stats_basic(store: EventStore) -> None:
    store.insert(_ev(agent="claude-code", event_type="prompt.submitted"))
    store.insert(_ev(agent="claude-code", session_id="s-2", event_type="policy.block"))
    store.insert(
        _ev(
            agent="cursor",
            session_id="s-3",
            event_type="cost.recorded",
            cost={"usd": 0.42, "model": "claude-3.5-sonnet"},
        )
    )
    store.insert(
        _ev(
            agent="claude-code",
            session_id="s-4",
            event_type="injection.suspected",
        )
    )

    stats = timeline_stats(store)
    assert isinstance(stats, TimelineStats)
    assert stats.total_events == 4
    assert stats.by_agent == {"claude-code": 3, "cursor": 1}
    assert stats.policy_blocks == 1
    assert stats.suspected_injections == 1
    assert stats.cost_usd == pytest.approx(0.42)
    assert stats.by_event_type["cost.recorded"] == 1


def test_timeline_stats_with_since_filter(store: EventStore) -> None:
    store.insert(_ev(ts="2026-05-01T00:00:00Z", session_id="a"))
    store.insert(_ev(ts="2026-05-02T00:00:00Z", session_id="b"))
    cutoff = _parse_epoch_ms("2026-05-01T12:00:00Z")
    stats = timeline_stats(store, since_epoch_ms=cutoff)
    assert stats.total_events == 1


# ── Parser helper ────────────────────────────────────────────────────────────


def test_parse_epoch_ms_handles_z_suffix() -> None:
    ms = _parse_epoch_ms("2026-01-01T00:00:00Z")
    assert ms == 1767225600000


def test_parse_epoch_ms_handles_offset() -> None:
    ms = _parse_epoch_ms("2026-01-01T00:00:00+00:00")
    assert ms == 1767225600000


def test_parse_epoch_ms_rejects_garbage() -> None:
    with pytest.raises(SchemaError):
        _parse_epoch_ms("not-a-date")


def test_parse_epoch_ms_assumes_utc_when_naive() -> None:
    ms = _parse_epoch_ms("2026-01-01T00:00:00")
    assert ms == 1767225600000
