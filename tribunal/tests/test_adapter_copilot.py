"""Tests for tribunal.adapters.copilot — GitHub Copilot CLI translator."""

from __future__ import annotations

from typing import Any

from tribunal.adapters import copilot
from tribunal.events.schema import validate_event


def _events() -> tuple[list[dict], Any]:
    events: list[dict] = []
    return events, events.append


def _base(**kw: Any) -> dict:
    p = {
        "session_id": "cp-1",
        "user_id": "alice",
        "copilot_version": "1.0.0",
        "cwd": "/repo",
    }
    p.update(kw)
    return p


def test_session_start_emits_session_event() -> None:
    events, emit = _events()
    copilot.on_session_start(
        _base(type="session.start", command="gh copilot suggest", model="gpt-4o"),
        emit,
    )
    assert len(events) == 1
    ev = events[0]
    validate_event(ev)
    assert ev["agent"] == "copilot-cli"
    assert ev["event_type"] == "session.start"
    assert ev["payload"]["model"] == "gpt-4o"


def test_session_end_carries_exit_code() -> None:
    events, emit = _events()
    copilot.on_session_end(_base(type="session.end", exit_code=0), emit)
    assert events[0]["event_type"] == "session.end"
    assert events[0]["payload"]["exit_code"] == 0


def test_turn_complete_fans_out_to_four_events() -> None:
    events, emit = _events()
    copilot.on_turn_complete(
        _base(
            type="turn.complete",
            prompt="commit my changes",
            suggestion="git add -A && git commit -m 'wip'",
            executed=True,
            exit_code=0,
            cost_usd=0.0021,
            input_tokens=120,
            output_tokens=45,
            model="gpt-4o-mini",
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert types == [
        "prompt.submitted",
        "tool.proposed",
        "tool.executed",
        "cost.recorded",
    ]
    for ev in events:
        validate_event(ev)
    # cost event carries the model
    cost_ev = events[-1]
    assert cost_ev["cost"]["usd"] == 0.0021
    assert cost_ev["cost"]["model"] == "gpt-4o-mini"


def test_turn_complete_without_execution_omits_executed_event() -> None:
    events, emit = _events()
    copilot.on_turn_complete(
        _base(
            type="turn.complete",
            prompt="dry-run",
            suggestion="echo hi",
            executed=False,
            cost_usd=0.0001,
        ),
        emit,
    )
    types = [e["event_type"] for e in events]
    assert "tool.executed" not in types
    assert "tool.proposed" in types


def test_turn_complete_with_no_cost_does_not_emit_cost_event() -> None:
    events, emit = _events()
    copilot.on_turn_complete(
        _base(type="turn.complete", prompt="x", suggestion="echo hi", executed=False),
        emit,
    )
    assert all(e["event_type"] != "cost.recorded" for e in events)


def test_translate_unknown_type_emits_error_gate() -> None:
    events, emit = _events()
    n = copilot.translate(_base(type="hypothetical"), emit)
    assert n == 1
    assert events[0]["event_type"] == "error.gate"


def test_translate_routes_to_handler() -> None:
    events, emit = _events()
    n = copilot.translate(
        _base(type="turn.complete", prompt="p", suggestion="s", executed=False), emit
    )
    assert n >= 2  # prompt + tool.proposed at minimum
    assert events[0]["event_type"] == "prompt.submitted"
