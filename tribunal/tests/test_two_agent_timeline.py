"""Two-agent integration test — Claude Code + Cursor in one timeline.

This is the milestone Week-4 acceptance test: events from both adapters
land in the same EventStore, the daemon's /v1/events endpoint returns
them in time order, and /v1/stats correctly attributes counts to each
agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tribunal.adapters import claude_code, cursor  # noqa: E402
from tribunal.daemon import create_app  # noqa: E402
from tribunal.events.store import EventStore  # noqa: E402


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[EventStore, TestClient]]:
    store = EventStore(db_path=tmp_path / "events.db")
    app = create_app(store=store, auth_token=None)
    client = TestClient(app)
    yield store, client
    store.close()


def _run_claude_session(client: TestClient, repo: str = "/repo") -> int:
    """Simulate a small Claude Code session and POST each event. Returns
    the number of events sent."""
    sent: list[dict] = []

    def post(payloads: list[dict]) -> None:
        nonlocal sent
        for p in payloads:
            buf: list[dict] = []
            claude_code.translate(p, buf.append)
            sent.extend(buf)

    post(
        [
            {
                "hook_event_name": "SessionStart",
                "session_id": "cc-1",
                "cwd": repo,
                "claude_code_version": "0.2.10",
                "source": "user",
            },
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "cc-1",
                "cwd": repo,
                "prompt": "implement add()",
            },
            {
                "hook_event_name": "PreToolUse",
                "session_id": "cc-1",
                "cwd": repo,
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/repo/add.py",
                    "content": "def add(a,b): return a+b",
                },
            },
            {
                "hook_event_name": "PostToolUse",
                "session_id": "cc-1",
                "cwd": repo,
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/repo/add.py",
                    "content": "def add(a,b): return a+b",
                },
                "tool_response": {},
                "success": True,
            },
            {
                "hook_event_name": "Stop",
                "session_id": "cc-1",
                "cwd": repo,
                "stop_reason": "user",
                "turn_count": 2,
            },
        ]
    )
    r = client.post("/v1/events", json={"events": sent})
    assert r.status_code == 200
    body = r.json()
    assert body["rejected_count"] == 0
    return body["accepted"]


def _run_cursor_session(client: TestClient, repo: str = "/repo") -> int:
    sent: list[dict] = []

    def emit(p: dict) -> None:
        sent.append(p)

    cursor.translate(
        {
            "type": "chat.open",
            "session_id": "cur-1",
            "workspace_root": repo,
            "cursor_version": "0.40.1",
            "model": "gpt-4o",
        },
        emit,
    )
    cursor.translate(
        {
            "type": "user.message",
            "session_id": "cur-1",
            "workspace_root": repo,
            "text": "fix the failing test",
        },
        emit,
    )
    cursor.translate(
        {
            "type": "tool.call",
            "session_id": "cur-1",
            "workspace_root": repo,
            "tool": "shell",
            "args": {"command": "pytest -q"},
        },
        emit,
    )
    cursor.translate(
        {
            "type": "tool.result",
            "session_id": "cur-1",
            "workspace_root": repo,
            "tool": "shell",
            "ok": True,
            "args": {"command": "pytest -q"},
            "result": {"exit_code": 0, "stdout": "ok"},
        },
        emit,
    )
    cursor.translate(
        {
            "type": "cost.recorded",
            "session_id": "cur-1",
            "workspace_root": repo,
            "cost": {
                "usd": 0.04,
                "model": "gpt-4o",
                "input_tokens": 200,
                "output_tokens": 80,
            },
        },
        emit,
    )
    r = client.post("/v1/events", json={"events": sent})
    assert r.status_code == 200
    body = r.json()
    assert body["rejected_count"] == 0
    return body["accepted"]


# ── Tests ────────────────────────────────────────────────────────────────────


def test_two_agents_share_one_timeline(env: tuple[EventStore, TestClient]) -> None:
    store, client = env

    cc_count = _run_claude_session(client)
    cur_count = _run_cursor_session(client)
    assert cc_count >= 5
    assert cur_count >= 5

    # /v1/stats — every agent attributed
    stats = client.get("/v1/stats").json()
    assert set(stats["by_agent"].keys()) == {"claude-code", "cursor"}
    assert stats["by_agent"]["claude-code"] == cc_count
    assert stats["by_agent"]["cursor"] == cur_count
    assert stats["cost_usd"] == pytest.approx(0.04)

    # /v1/events — newest first
    events = client.get("/v1/events").json()["events"]
    assert len(events) == cc_count + cur_count
    # Last sent (Cursor cost.recorded) should be at the top
    assert events[0]["agent"] == "cursor"
    # Verify a file.write from Claude Code is in the merged timeline
    assert any(
        e["agent"] == "claude-code" and e["event_type"] == "file.write" for e in events
    )


def test_filter_by_agent_isolates_sessions(env: tuple[EventStore, TestClient]) -> None:
    _, client = env
    _run_claude_session(client)
    _run_cursor_session(client)
    only_cursor = client.get("/v1/events?agent=cursor").json()["events"]
    assert all(e["agent"] == "cursor" for e in only_cursor)
    assert len(only_cursor) >= 5


def test_cost_endpoint_aggregates_across_agents(
    env: tuple[EventStore, TestClient],
) -> None:
    _, client = env
    _run_claude_session(client)
    _run_cursor_session(client)
    body = client.get("/v1/cost").json()
    # Only Cursor sent a cost.recorded in this scenario.
    assert body["total_usd"] == pytest.approx(0.04)
    assert body["by_agent"] == {"cursor": pytest.approx(0.04)}
