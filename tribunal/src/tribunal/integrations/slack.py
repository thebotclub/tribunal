"""Slack webhook notifier -- fire on policy.block and cost-cap breaches.

Reads ``TRIBUNAL_SLACK_WEBHOOK`` from the env. When unset the notifier
is a no-op so the import is free for OSS users with no Slack workspace.

Posts go to Slack incoming webhooks
(https://api.slack.com/messaging/webhooks). The body is Slack
Block Kit-formatted so it renders nicely in channels.

The notifier batches: it accumulates events for up to ``flush_interval``
seconds (default 5) and posts at most one Slack message per batch to
respect Slack's rate limits and avoid notification storm during agent
loops.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

log = logging.getLogger("tribunal.integrations.slack")


@dataclass
class _PendingAlert:
    severity: str  # "block" | "ask" | "cost" | "injection"
    title: str
    detail: str
    rule_id: str = ""
    pack: str = ""
    agent: str = ""
    session_id: str = ""


@dataclass
class SlackNotifier:
    webhook_url: str = ""
    flush_interval_seconds: float = 5.0
    max_queue: int = 50
    _queue: list[_PendingAlert] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: Optional[threading.Thread] = None
    _stop: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def from_env(cls) -> "SlackNotifier":
        return cls(webhook_url=os.environ.get("TRIBUNAL_SLACK_WEBHOOK", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    # -- Public entry points ---------------------------------------------

    def notify_policy_decision(
        self, event: Mapping[str, Any], decision: Mapping[str, Any]
    ) -> None:
        action = decision.get("action") or ""
        if action not in ("deny", "ask"):
            return
        self._enqueue(
            _PendingAlert(
                severity="block" if action == "deny" else "ask",
                title=f"Tribunal policy {action.upper()} -- {decision.get('rule_id') or 'rule'}",
                detail=str(decision.get("message") or ""),
                rule_id=str(decision.get("rule_id") or ""),
                pack=str(decision.get("pack") or ""),
                agent=str(event.get("agent") or ""),
                session_id=str(event.get("session_id") or ""),
            )
        )

    def notify_injection(
        self, event: Mapping[str, Any], finding: Mapping[str, Any]
    ) -> None:
        severity = str(finding.get("severity") or "low")
        if severity == "low":
            return  # don't page on low-confidence injection
        self._enqueue(
            _PendingAlert(
                severity="injection",
                title=f"Possible prompt injection ({severity})",
                detail=str(finding.get("message") or ""),
                rule_id=str(finding.get("rule_id") or ""),
                agent=str(event.get("agent") or ""),
                session_id=str(event.get("session_id") or ""),
            )
        )

    def notify_cost_breach(
        self,
        *,
        window: str,
        spent_usd: float,
        cap_usd: float,
        agent: str = "",
        user_id: str = "",
    ) -> None:
        self._enqueue(
            _PendingAlert(
                severity="cost",
                title=f"Tribunal cost cap breach -- {window}",
                detail=(
                    f"${spent_usd:,.2f} spent against ${cap_usd:,.2f} cap "
                    f"({(spent_usd / cap_usd * 100):.0f}%)."
                ),
                agent=agent,
                session_id=user_id,
            )
        )

    # -- Lifecycle -------------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        t = threading.Thread(target=self._run, name="tribunal-slack", daemon=True)
        self._thread = t
        t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.flush_interval_seconds + 1)
            self._thread = None
        self.flush()

    # -- Internals -------------------------------------------------------

    def _enqueue(self, alert: _PendingAlert) -> None:
        if not self.enabled:
            return
        with self._lock:
            if len(self._queue) >= self.max_queue:
                # Drop oldest -- alerts are notifications, not audit trail.
                self._queue.pop(0)
            self._queue.append(alert)

    def _run(self) -> None:
        while not self._stop.wait(self.flush_interval_seconds):
            self.flush()

    def flush(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()
        try:
            self._post(self._render(batch))
        except Exception:  # noqa: BLE001 -- never let Slack break ingestion
            log.exception("slack webhook post failed; dropping %d alert(s)", len(batch))

    def _render(self, batch: list[_PendingAlert]) -> dict:
        # Slack Block Kit
        blocks: list[dict[str, Any]] = []
        # Header summarising the batch
        block_count = sum(1 for a in batch if a.severity == "block")
        ask_count = sum(1 for a in batch if a.severity == "ask")
        inj_count = sum(1 for a in batch if a.severity == "injection")
        cost_count = sum(1 for a in batch if a.severity == "cost")
        headline = (
            f":shield: Tribunal -- {block_count} block(s), {ask_count} ask(s), "
            f"{inj_count} injection alert(s), {cost_count} cost breach(es)."
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": headline}})
        # First N alerts as detail blocks
        for alert in batch[:10]:
            icon = {
                "block": ":no_entry:",
                "ask": ":question:",
                "injection": ":warning:",
                "cost": ":moneybag:",
            }.get(alert.severity, ":bell:")
            lines = [f"{icon} *{alert.title}*"]
            if alert.detail:
                lines.append(alert.detail.strip())
            meta_parts = []
            if alert.agent:
                meta_parts.append(f"agent `{alert.agent}`")
            if alert.session_id:
                meta_parts.append(f"session `{alert.session_id[:8]}`")
            if alert.pack:
                meta_parts.append(f"pack `{alert.pack}`")
            if alert.rule_id:
                meta_parts.append(f"rule `{alert.rule_id}`")
            if meta_parts:
                lines.append("* ".join(meta_parts))
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)},
                }
            )
        if len(batch) > 10:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_+{len(batch) - 10} more alert(s)..._",
                        }
                    ],
                }
            )
        return {"blocks": blocks, "text": headline}

    def _post(self, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 300:
                    log.warning("slack webhook returned %s", resp.status)
        except urllib.error.URLError as e:
            log.warning("slack webhook unreachable: %s", e)


__all__ = ["SlackNotifier"]
