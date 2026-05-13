"""Local event store -- SQLite-backed queue for the Tribunal daemon.

Every event the daemon receives goes through this module:

  1. INSERT into ``events`` table.
  2. INSERT a copy into ``outbox`` if cloud mode is on (with status='pending').
  3. The dashboard reads from ``events``; the streamer drains ``outbox``.

The store is intentionally small. We use SQLite because:

  - Every dev machine already has it.
  - The daemon process is single-writer; concurrent reads from the
    dashboard work via SQLite's WAL mode without surprises.
  - 100k events per developer per month is < 50 MB; nowhere near a
    scalability limit for the local case.

Schema is versioned via ``PRAGMA user_version`` and migrated forward at
open time. Migrations are idempotent and additive only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

from tribunal.events.schema import SCHEMA_VERSION, SchemaError, validate_event

# Bump when the SQLite schema changes. Migrations live in _MIGRATIONS.
_DB_VERSION = 1

_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS events (
        event_id        TEXT PRIMARY KEY,
        ts              TEXT NOT NULL,
        epoch_ms        INTEGER NOT NULL,
        schema_version  TEXT NOT NULL,
        agent           TEXT NOT NULL,
        agent_version   TEXT,
        session_id      TEXT NOT NULL,
        user_id         TEXT NOT NULL,
        machine_id      TEXT,
        repo_path       TEXT,
        repo_remote     TEXT,
        branch          TEXT,
        event_type      TEXT NOT NULL,
        policy_decision TEXT,
        policy_rule     TEXT,
        cost_usd        REAL,
        cost_model      TEXT,
        input_tokens    INTEGER,
        output_tokens   INTEGER,
        payload_json    TEXT NOT NULL,
        full_json       TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts        ON events(epoch_ms DESC);
    CREATE INDEX IF NOT EXISTS idx_events_session   ON events(session_id);
    CREATE INDEX IF NOT EXISTS idx_events_agent     ON events(agent);
    CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
    CREATE INDEX IF NOT EXISTS idx_events_repo      ON events(repo_path);

    CREATE TABLE IF NOT EXISTS outbox (
        event_id   TEXT PRIMARY KEY,
        queued_at  INTEGER NOT NULL,
        attempts   INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_outbox_queued    ON outbox(queued_at);
    """
}


# -- DB plumbing --------------------------------------------------------------


def _default_db_path() -> Path:
    return Path.home() / ".tribunal" / "events.db"


class EventStore:
    """Thread-safe SQLite-backed event store.

    A single ``EventStore`` instance is shared across the daemon's HTTP
    handlers; SQLite locks the file, and a Python ``RLock`` serialises
    writes from the same process.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # autocommit; we'll wrap our own txns
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.execute("PRAGMA foreign_keys = ON")
        version = cur.execute("PRAGMA user_version").fetchone()[0]
        for v in range(version + 1, _DB_VERSION + 1):
            migration = _MIGRATIONS.get(v)
            if migration:
                cur.executescript(migration)
                cur.execute(f"PRAGMA user_version = {v}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                yield cur
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    # -- Writes -----------------------------------------------------------

    def insert(
        self, event: Mapping[str, Any], *, queue_for_cloud: bool = False
    ) -> None:
        """Insert one validated event. Idempotent on event_id."""
        validate_event(event)
        cost = event.get("cost") or {}
        row = (
            event["event_id"],
            event["ts"],
            _parse_epoch_ms(event["ts"]),
            event["schema_version"],
            event["agent"],
            event.get("agent_version"),
            event["session_id"],
            event["user_id"],
            event.get("machine_id"),
            event.get("repo_path"),
            event.get("repo_remote"),
            event.get("branch"),
            event["event_type"],
            event.get("policy_decision"),
            event.get("policy_rule"),
            cost.get("usd"),
            cost.get("model"),
            cost.get("input_tokens"),
            cost.get("output_tokens"),
            json.dumps(event.get("payload") or {}, sort_keys=True),
            json.dumps(event, sort_keys=True),
        )
        with self._tx() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO events (
                    event_id, ts, epoch_ms, schema_version,
                    agent, agent_version, session_id, user_id, machine_id,
                    repo_path, repo_remote, branch, event_type,
                    policy_decision, policy_rule,
                    cost_usd, cost_model, input_tokens, output_tokens,
                    payload_json, full_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                row,
            )
            if queue_for_cloud and cur.rowcount > 0:
                cur.execute(
                    "INSERT OR IGNORE INTO outbox (event_id, queued_at) VALUES (?, ?)",
                    (event["event_id"], int(time.time() * 1000)),
                )

    def insert_many(
        self, events: Iterable[Mapping[str, Any]], *, queue_for_cloud: bool = False
    ) -> int:
        """Bulk insert. Returns how many rows were newly written."""
        count = 0
        for ev in events:
            try:
                self.insert(ev, queue_for_cloud=queue_for_cloud)
                count += 1
            except SchemaError:
                # Skip invalid events but don't abort the batch -- adapters
                # may produce one bad event in a hundred and we want the
                # rest persisted.
                continue
        return count

    # -- Reads ------------------------------------------------------------

    def recent(
        self,
        *,
        limit: int = 200,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
        since_epoch_ms: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT full_json FROM events WHERE 1=1"
        args: list[Any] = []
        if agent:
            sql += " AND agent = ?"
            args.append(agent)
        if event_type:
            sql += " AND event_type = ?"
            args.append(event_type)
        if since_epoch_ms is not None:
            sql += " AND epoch_ms > ?"
            args.append(since_epoch_ms)
        sql += " ORDER BY epoch_ms DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [json.loads(r["full_json"]) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def agents_seen(self) -> list[str]:
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT DISTINCT agent FROM events ORDER BY agent"
                )
            ]

    # -- Outbox (for cloud streamer) --------------------------------------

    def outbox_pending(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT e.full_json
                FROM outbox o JOIN events e ON o.event_id = e.event_id
                ORDER BY o.queued_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(r["full_json"]) for r in rows]

    def outbox_ack(self, event_ids: Sequence[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" * len(event_ids))
        with self._tx() as cur:
            cur.execute(
                f"DELETE FROM outbox WHERE event_id IN ({placeholders})",
                tuple(event_ids),
            )

    def outbox_fail(self, event_ids: Sequence[str], error: str) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" * len(event_ids))
        with self._tx() as cur:
            cur.execute(
                f"UPDATE outbox SET attempts = attempts + 1, last_error = ? "
                f"WHERE event_id IN ({placeholders})",
                (error[:500], *event_ids),
            )

    def cost_breakdown(
        self,
        *,
        since_ms: int,
        group_by: str = "agent",
    ) -> list[tuple[str, float, int]]:
        """Sum cost_usd grouped by agent / user / model / session.

        Returns a list of (key, total_usd, event_count) ordered DESC by spend.
        Rows with NULL cost_usd are excluded.
        """
        col_map = {
            "agent": "agent",
            "user": "user_id",
            "model": "cost_model",
            "session": "session_id",
        }
        col = col_map.get(group_by, "agent")
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                f"""
                SELECT COALESCE({col}, '(unknown)') AS k,
                       SUM(cost_usd) AS usd,
                       COUNT(*)      AS events
                FROM events
                WHERE cost_usd IS NOT NULL
                  AND epoch_ms >= ?
                GROUP BY k
                ORDER BY usd DESC
                """,
                (since_ms,),
            )
            return [(r[0], float(r[1] or 0.0), int(r[2])) for r in cur.fetchall()]

    def outbox_depth(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]


# -- Stats helpers ------------------------------------------------------------


@dataclass
class TimelineStats:
    total_events: int
    by_agent: dict[str, int]
    by_event_type: dict[str, int]
    policy_blocks: int
    suspected_injections: int
    cost_usd: float


def timeline_stats(
    store: EventStore, *, since_epoch_ms: Optional[int] = None
) -> TimelineStats:
    """Tally events over an optional time range. Used by the dashboard."""
    sql_where = ""
    args: tuple[Any, ...] = ()
    if since_epoch_ms is not None:
        sql_where = " WHERE epoch_ms > ?"
        args = (since_epoch_ms,)
    with store._lock:  # noqa: SLF001
        conn = store._conn  # noqa: SLF001
        total = conn.execute(
            f"SELECT COUNT(*) FROM events{sql_where}", args
        ).fetchone()[0]
        by_agent = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT agent, COUNT(*) FROM events{sql_where} GROUP BY agent",
                args,
            )
        }
        by_type = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT event_type, COUNT(*) FROM events{sql_where} GROUP BY event_type",
                args,
            )
        }
        blocks = conn.execute(
            f"SELECT COUNT(*) FROM events{sql_where}{' AND' if sql_where else ' WHERE'} event_type='policy.block'",
            args,
        ).fetchone()[0]
        injections = conn.execute(
            f"SELECT COUNT(*) FROM events{sql_where}{' AND' if sql_where else ' WHERE'} event_type='injection.suspected'",
            args,
        ).fetchone()[0]
        cost = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) FROM events{sql_where}{' AND' if sql_where else ' WHERE'} event_type='cost.recorded'",
            args,
        ).fetchone()[0]
    return TimelineStats(
        total_events=total,
        by_agent=by_agent,
        by_event_type=by_type,
        policy_blocks=blocks,
        suspected_injections=injections,
        cost_usd=float(cost or 0.0),
    )


# -- Utilities ----------------------------------------------------------------


def _parse_epoch_ms(ts: str) -> int:
    """Convert an RFC-3339 timestamp into epoch milliseconds."""
    from datetime import datetime, timezone

    # Handle both '...Z' and '...+00:00'
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError as e:
        raise SchemaError(f"unparseable timestamp {ts!r}: {e}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


__all__ = [
    "EventStore",
    "TimelineStats",
    "timeline_stats",
    "SCHEMA_VERSION",
]
