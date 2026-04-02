"""Tests for agents.py — multi-agent governance (P8)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from tribunal.protocol import HookEvent
from tribunal.agents import (
    AgentInfo,
    MultiAgentPolicy,
    check_agent_policy,
    format_agent_tree,
    get_active_agents,
    get_completed_agents,
    load_multi_agent_policy,
)


def _make_event(hook_name: str, cwd: str, **kwargs) -> HookEvent:
    defaults = {
        "hook_event_name": hook_name,
        "session_id": "sess_test",
        "cwd": cwd,
    }
    defaults.update(kwargs)
    return HookEvent(**defaults)


class TestMultiAgentPolicy:
    def test_load_default_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = load_multi_agent_policy(tmpdir)
            assert policy.max_concurrent_agents == 0
            assert policy.per_agent_budget == 0.0
            assert policy.shared_session_budget == 0.0

    def test_load_policy_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".tribunal"
            config_dir.mkdir()
            config = {
                "multi_agent": {
                    "max_concurrent_agents": 3,
                    "per_agent_budget": 1.0,
                    "shared_session_budget": 5.0,
                    "agent_permissions": {
                        "research": {
                            "allow": ["WebSearch", "Read"],
                            "deny": ["FileEdit"],
                        }
                    },
                }
            }
            (config_dir / "config.yaml").write_text(yaml.dump(config))
            policy = load_multi_agent_policy(tmpdir)
            assert policy.max_concurrent_agents == 3
            assert policy.per_agent_budget == 1.0
            assert policy.shared_session_budget == 5.0
            assert "research" in policy.agent_permissions


class TestCheckAgentPolicy:
    def test_allows_when_no_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _make_event("SubagentStart", tmpdir, agent_id="a1")
            allowed, reason = check_agent_policy(event)
            assert allowed is True

    def test_blocks_on_max_concurrent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".tribunal"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(yaml.dump({
                "multi_agent": {"max_concurrent_agents": 2}
            }))
            # Set up state with 2 active agents
            (config_dir / "state.json").write_text(json.dumps({
                "active_agents": {
                    "a1": {"started_at": "t1", "cost_usd": 0, "tool_calls": 0},
                    "a2": {"started_at": "t2", "cost_usd": 0, "tool_calls": 0},
                }
            }))
            event = _make_event("SubagentStart", tmpdir, agent_id="a3")
            allowed, reason = check_agent_policy(event)
            assert allowed is False
            assert "Max concurrent" in reason

    def test_blocks_on_per_agent_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".tribunal"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(yaml.dump({
                "multi_agent": {"per_agent_budget": 1.0}
            }))
            (config_dir / "state.json").write_text(json.dumps({
                "active_agents": {
                    "a1": {"started_at": "t1", "cost_usd": 1.5, "tool_calls": 10},
                }
            }))
            event = _make_event("PreToolUse", tmpdir, agent_id="a1")
            allowed, reason = check_agent_policy(event)
            assert allowed is False
            assert "exceeds" in reason

    def test_blocks_on_shared_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".tribunal"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(yaml.dump({
                "multi_agent": {"shared_session_budget": 5.0}
            }))
            (config_dir / "state.json").write_text(json.dumps({
                "session_cost_usd": 5.5,
            }))
            event = _make_event("PreToolUse", tmpdir)
            allowed, reason = check_agent_policy(event)
            assert allowed is False
            assert "exceeded" in reason


class TestAgentTracking:
    def test_get_active_agents_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agents = get_active_agents(tmpdir)
            assert agents == []

    def test_get_active_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "active_agents": {
                    "a1": {"agent_type": "worker", "started_at": "t1", "cost_usd": 0.5, "tool_calls": 3},
                }
            }))
            agents = get_active_agents(tmpdir)
            assert len(agents) == 1
            assert agents[0].agent_id == "a1"
            assert agents[0].cost_usd == 0.5

    def test_get_completed_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "completed_agents": [
                    {"agent_id": "a1", "agent_type": "worker", "started_at": "t1", "stopped_at": "t2", "cost_usd": 1.0}
                ]
            }))
            agents = get_completed_agents(tmpdir)
            assert len(agents) == 1
            assert agents[0].stopped_at == "t2"


class TestFormatAgentTree:
    def test_empty_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = format_agent_tree(tmpdir)
            assert "No active agents" in output

    def test_tree_with_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".tribunal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "active_agents": {
                    "agent-1": {"agent_type": "worker", "started_at": "2026-04-02T10:00:00Z", "cost_usd": 0.5, "tool_calls": 3},
                }
            }))
            output = format_agent_tree(tmpdir)
            assert "agent-1" in output
            assert "Active Agents (1)" in output
