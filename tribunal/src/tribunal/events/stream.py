"""Batched cloud uploader for Tribunal events.

The streamer is a daemon thread that periodically drains the local
``outbox`` table and POSTs batches to the Tribunal Cloud ingest endpoint
(or any HTTP receiver that follows the same contract).

Design choices:

  - Pull-based, not push: the daemon's request handlers only write to
    the outbox. The streamer is the *only* thing that talks to the
    network. This keeps tool-call hot paths offline-friendly.
  - Exponential backoff with jitter; retries forever rather than dropping.
  - Bearer-token auth via ``TRIBUNAL_TOKEN`` env var.
  - The endpoint is configured via ``TRIBUNAL_CLOUD_URL`` (default OFF).

Wire format: ``POST {url}/v1/events`` with body:

    { "events": [<unified-event>, ...] }

The receiver must return 2xx on accept, 4xx for permanent failure
(events get dropped from the outbox), 5xx for transient (retried).
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from tribunal.events.store import EventStore

log = logging.getLogger("tribunal.stream")

DEFAULT_BATCH = 100
DEFAULT_INTERVAL_SEC = 30.0
DEFAULT_MAX_BACKOFF = 300.0  # 5 minutes
_ENV_URL = "TRIBUNAL_CLOUD_URL"
_ENV_TOKEN = "TRIBUNAL_TOKEN"


class CloudStreamer:
    """Background uploader. Start with ``.start()``, stop with ``.stop()``."""

    def __init__(
        self,
        store: EventStore,
        *,
        url: Optional[str] = None,
        token: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        max_backoff_sec: float = DEFAULT_MAX_BACKOFF,
    ):
        self.store = store
        self.url = (url or os.environ.get(_ENV_URL, "")).rstrip("/")
        self.token = token or os.environ.get(_ENV_TOKEN, "")
        self.batch_size = batch_size
        self.interval_sec = interval_sec
        self.max_backoff_sec = max_backoff_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._backoff = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self.enabled:
            log.info(
                "CloudStreamer disabled (set %s and %s to enable)",
                _ENV_URL,
                _ENV_TOKEN,
            )
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tribunal-streamer", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    # -- Main loop --------------------------------------------------------

    def _run(self) -> None:
        log.info("CloudStreamer started -> %s", self.url)
        while not self._stop.is_set():
            try:
                drained = self._drain_once()
                if drained == 0:
                    self._sleep(self.interval_sec)
                else:
                    # Tight loop when there's still backlog
                    self._backoff = 0.0
            except Exception:  # noqa: BLE001
                log.exception("CloudStreamer iteration failed")
                self._sleep(self._next_backoff())
        log.info("CloudStreamer stopped")

    def _sleep(self, secs: float) -> None:
        end = time.time() + secs
        while time.time() < end and not self._stop.is_set():
            time.sleep(min(0.5, end - time.time()))

    def _next_backoff(self) -> float:
        self._backoff = min(max(self._backoff, 1.0) * 2.0, self.max_backoff_sec)
        return self._backoff * (0.5 + random.random())  # jitter

    # -- One upload attempt -----------------------------------------------

    def _drain_once(self) -> int:
        """Send up to ``batch_size`` events. Returns how many were acked."""
        batch = self.store.outbox_pending(limit=self.batch_size)
        if not batch:
            return 0

        try:
            self._post({"events": batch})
        except _PermanentError as perm:
            ids = [ev["event_id"] for ev in batch]
            self.store.outbox_ack(ids)  # drop permanent failures
            log.warning("Dropped %d events on permanent error: %s", len(ids), perm)
            return 0
        except Exception as err:  # noqa: BLE001
            self.store.outbox_fail([ev["event_id"] for ev in batch], str(err))
            raise

        ids = [ev["event_id"] for ev in batch]
        self.store.outbox_ack(ids)
        log.info("Acked %d events", len(ids))
        return len(ids)

    def _post(self, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/v1/events",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "tribunal/streamer",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"unexpected status {resp.status}")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code not in (408, 429):
                raise _PermanentError(f"{e.code} {e.reason}") from e
            raise


class _PermanentError(Exception):
    """4xx that we should NOT retry."""


__all__ = ["CloudStreamer"]
