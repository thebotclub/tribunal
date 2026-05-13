"""Tests for tribunal.events.stream -- batched cloud uploader."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tribunal.events.schema import new_event
from tribunal.events.store import EventStore
from tribunal.events.stream import (
    CloudStreamer,
    _PermanentError,
)


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    s = EventStore(db_path=tmp_path / "events.db")
    yield s
    s.close()


def _enqueue(store: EventStore, n: int = 1) -> list[dict]:
    events = []
    for i in range(n):
        e = new_event(
            agent="claude-code",
            agent_version="1.2.3",
            session_id=f"s-{i}",
            user_id="u-1",
            event_type="prompt.submitted",
            payload={"prompt": f"hello-{i}"},
        )
        store.insert(e, queue_for_cloud=True)
        events.append(e)
    return events


# -- Configuration & lifecycle ------------------------------------------------


def test_streamer_disabled_without_url_and_token(store: EventStore) -> None:
    s = CloudStreamer(store)
    assert s.enabled is False


def test_streamer_enabled_when_configured(store: EventStore) -> None:
    s = CloudStreamer(store, url="https://api.example.com", token="t-1")
    assert s.enabled is True


def test_env_vars_pick_up(store: EventStore, monkeypatch) -> None:
    monkeypatch.setenv("TRIBUNAL_CLOUD_URL", "https://envapi.example.com/")
    monkeypatch.setenv("TRIBUNAL_TOKEN", "abc")
    s = CloudStreamer(store)
    assert s.enabled is True
    # trailing slash gets stripped
    assert s.url == "https://envapi.example.com"


def test_start_noop_when_disabled(store: EventStore) -> None:
    s = CloudStreamer(store)
    s.start()  # should silently skip
    assert s._thread is None


# -- Drain semantics ----------------------------------------------------------


def test_drain_returns_zero_when_outbox_empty(store: EventStore) -> None:
    s = CloudStreamer(store, url="https://x", token="t")
    with patch.object(s, "_post") as mock_post:
        n = s._drain_once()
    assert n == 0
    mock_post.assert_not_called()


def test_drain_uploads_and_acks_on_success(store: EventStore) -> None:
    events = _enqueue(store, n=3)
    s = CloudStreamer(store, url="https://x", token="t", batch_size=10)

    with patch.object(s, "_post") as mock_post:
        n = s._drain_once()

    assert n == 3
    mock_post.assert_called_once()
    body = mock_post.call_args[0][0]
    assert len(body["events"]) == 3
    assert {e["event_id"] for e in body["events"]} == {e["event_id"] for e in events}
    assert store.outbox_depth() == 0  # all acked


def test_drain_respects_batch_size(store: EventStore) -> None:
    _enqueue(store, n=5)
    s = CloudStreamer(store, url="https://x", token="t", batch_size=2)
    with patch.object(s, "_post") as mock_post:
        n = s._drain_once()
    assert n == 2
    assert store.outbox_depth() == 3
    body = mock_post.call_args[0][0]
    assert len(body["events"]) == 2


def test_drain_permanent_error_drops_batch(store: EventStore) -> None:
    _enqueue(store, n=2)
    s = CloudStreamer(store, url="https://x", token="t")
    with patch.object(s, "_post", side_effect=_PermanentError("400 bad")):
        n = s._drain_once()
    assert n == 0
    # 4xx -> permanent -> events dropped from outbox so we don't retry forever
    assert store.outbox_depth() == 0


def test_drain_transient_error_records_failure(store: EventStore) -> None:
    events = _enqueue(store, n=2)
    s = CloudStreamer(store, url="https://x", token="t")
    with patch.object(s, "_post", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            s._drain_once()
    # Events still pending; attempts incremented
    assert store.outbox_depth() == 2
    for ev in events:
        with store._lock:
            row = store._conn.execute(
                "SELECT attempts, last_error FROM outbox WHERE event_id=?",
                (ev["event_id"],),
            ).fetchone()
        assert row["attempts"] == 1
        assert row["last_error"] == "boom"


# -- HTTP wire format ---------------------------------------------------------


def test_post_serialises_bearer_and_path(store: EventStore) -> None:
    s = CloudStreamer(store, url="https://api.example.com", token="secret-xyz")
    fake_resp = MagicMock()
    fake_resp.status = 202
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda *a: None

    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_urlopen:
        s._post({"events": [{"x": 1}]})

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://api.example.com/v1/events"
    assert req.get_method() == "POST"
    assert req.headers["Authorization"] == "Bearer secret-xyz"
    assert req.headers["Content-type"] == "application/json"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent == {"events": [{"x": 1}]}


def _make_http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.example.com/v1/events",
        code=code,
        msg=f"status-{code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_post_4xx_is_permanent(store: EventStore, code: int) -> None:
    s = CloudStreamer(store, url="https://api.example.com", token="t")
    with patch("urllib.request.urlopen", side_effect=_make_http_error(code)):
        with pytest.raises(_PermanentError):
            s._post({"events": []})


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503])
def test_post_retryable_codes_propagate(store: EventStore, code: int) -> None:
    s = CloudStreamer(store, url="https://api.example.com", token="t")
    with patch("urllib.request.urlopen", side_effect=_make_http_error(code)):
        with pytest.raises(urllib.error.HTTPError):
            s._post({"events": []})


# -- Backoff ------------------------------------------------------------------


def test_next_backoff_grows_and_caps(store: EventStore) -> None:
    s = CloudStreamer(store, url="https://x", token="t", max_backoff_sec=10)
    seen = [s._next_backoff() for _ in range(20)]
    # All values should be within jittered cap
    assert max(seen) <= 10 * 1.5 + 0.001
    # The internal backoff state caps at max_backoff_sec
    assert s._backoff <= 10
