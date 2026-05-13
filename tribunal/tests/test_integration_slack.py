"""Tests for tribunal.integrations.slack — webhook notifier."""
from __future__ import annotations

from typing import Any

import pytest

from tribunal.integrations.slack import SlackNotifier


# ── Disabled-by-default semantics ───────────────────────────────────────────


def test_notifier_disabled_when_webhook_unset() -> None:
    n = SlackNotifier(webhook_url="")
    assert n.enabled is False


def test_notifier_no_op_when_disabled() -> None:
    n = SlackNotifier(webhook_url="")
    n.notify_policy_decision({"agent": "x"}, {"action": "deny"})
    n.notify_injection({}, {"severity": "high"})
    n.notify_cost_breach(window="day", spent_usd=1, cap_usd=1)
    # Queue stays empty
    assert n._queue == []  # type: ignore[attr-defined]


def test_from_env_reads_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBUNAL_SLACK_WEBHOOK", "https://hooks.slack.test/abc")
    n = SlackNotifier.from_env()
    assert n.webhook_url == "https://hooks.slack.test/abc"
    assert n.enabled is True


# ── Queueing ────────────────────────────────────────────────────────────────


def test_policy_decision_enqueued_only_for_deny_or_ask() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x")
    n.notify_policy_decision({"agent": "claude-code", "session_id": "s"}, {"action": "allow"})
    assert len(n._queue) == 0  # type: ignore[attr-defined]
    n.notify_policy_decision({"agent": "claude-code", "session_id": "s"}, {"action": "warn"})
    assert len(n._queue) == 0  # type: ignore[attr-defined]
    n.notify_policy_decision(
        {"agent": "claude-code", "session_id": "s"},
        {"action": "deny", "rule_id": "x/y", "pack": "p", "message": "blocked"},
    )
    assert len(n._queue) == 1  # type: ignore[attr-defined]
    n.notify_policy_decision({"agent": "x", "session_id": "s"}, {"action": "ask"})
    assert len(n._queue) == 2  # type: ignore[attr-defined]


def test_injection_low_severity_dropped() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x")
    n.notify_injection({"agent": "x"}, {"severity": "low", "rule_id": "r"})
    assert len(n._queue) == 0  # type: ignore[attr-defined]
    n.notify_injection({"agent": "x"}, {"severity": "high", "rule_id": "r"})
    assert len(n._queue) == 1  # type: ignore[attr-defined]


def test_cost_breach_enqueues_alert() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x")
    n.notify_cost_breach(window="day", spent_usd=120.0, cap_usd=100.0, agent="claude-code")
    assert len(n._queue) == 1  # type: ignore[attr-defined]


def test_queue_caps_at_max() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x", max_queue=3)
    for i in range(10):
        n.notify_injection({"agent": f"a{i}"}, {"severity": "high", "rule_id": "r"})
    assert len(n._queue) == 3  # type: ignore[attr-defined]


# ── Block Kit rendering ─────────────────────────────────────────────────────


def test_render_produces_block_kit_structure() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x")
    n.notify_policy_decision(
        {"agent": "claude-code", "session_id": "abcdef1234"},
        {"action": "deny", "rule_id": "secrets/no-env-write", "pack": "secrets-readonly",
         "message": "Writing secrets blocked."},
    )
    n.notify_injection(
        {"agent": "cursor", "session_id": "x"},
        {"severity": "high", "rule_id": "injection/ignore-previous",
         "message": "ignore-prev detected"},
    )
    with n._lock:  # type: ignore[attr-defined]
        batch = list(n._queue)  # type: ignore[attr-defined]
    body = n._render(batch)  # type: ignore[attr-defined]
    assert "blocks" in body
    assert "text" in body
    assert any("block(s)" in (b.get("text", {}).get("text", "") or "") for b in body["blocks"])
    assert any("Writing secrets blocked." in (b.get("text", {}).get("text", "") or "")
               for b in body["blocks"])


def test_render_truncates_long_batches() -> None:
    n = SlackNotifier(webhook_url="https://hooks.test/x", max_queue=50)
    for i in range(15):
        n.notify_injection({"agent": f"a{i}"}, {"severity": "high", "rule_id": "r"})
    with n._lock:  # type: ignore[attr-defined]
        batch = list(n._queue)  # type: ignore[attr-defined]
    body = n._render(batch)  # type: ignore[attr-defined]
    # Should be 1 header + 10 alert sections + 1 "more" context block = 12
    assert len(body["blocks"]) == 12
    assert any("more alert" in (b.get("elements", [{}])[0].get("text", "") if b.get("type") == "context" else "")
               for b in body["blocks"])


# ── Flush is safe even on webhook failure ───────────────────────────────────


def test_flush_swallows_webhook_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    n = SlackNotifier(webhook_url="http://127.0.0.1:1")  # connection refused

    def boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("nope")

    monkeypatch.setattr(n, "_post", boom)
    n.notify_injection({"agent": "x"}, {"severity": "high", "rule_id": "r"})
    # Should not raise
    n.flush()
    assert n._queue == []  # type: ignore[attr-defined]
