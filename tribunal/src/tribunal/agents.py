"""Multi-agent governance — enforce policies across Claude Code's coordinator mode.

Tracks sub-agents, enforces per-agent budgets, manages shared session budgets,
and provides task-description-based permission matching for multi-agent sessions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .io import atomic_write_json, locked_read_json
from .protocol import HookEvent


@dataclass
class AgentInfo:
    """Information about a tracked sub-agent."""

    agent_id: str = ""
    agent_type: str = ""
    started_at: str = ""
    stopped_at: str = ""
    cost_usd: float = 0.0
    tool_calls: int = 0
    task_description: str = ""


@dataclass
class MultiAgentPolicy:
    """Multi-agent governance policy from config."""

    max_concurrent_agents: int = 0  # 0 = unlimited
    per_agent_budget: float = 0.0  # 0 = unlimited
    shared_session_budget: float = 0.0  # 0 = unlimited
    agent_permissions: dict[str, dict[str, list[str]]] = field(default_factory=dict)


def load_multi_agent_policy(cwd: str) -> MultiAgentPolicy:
    """Load multi-agent policy from .tribunal/config.yaml."""
    import yaml
    config_path = Path(cwd) / ".tribunal" / "config.yaml"
    if not config_path.is_file():
        return MultiAgentPolicy()
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return MultiAgentPolicy()

    ma = data.get("multi_agent", {})
    if not isinstance(ma, dict):
        return MultiAgentPolicy()

    policy = MultiAgentPolicy(
        max_concurrent_agents=ma.get("max_concurrent_agents", 0),
        per_agent_budget=ma.get("per_agent_budget", 0.0),
        shared_session_budget=ma.get("shared_session_budget", 0.0),
    )

    perms = ma.get("agent_permissions", {})
    if isinstance(perms, dict):
        policy.agent_permissions = perms

    return policy


def get_active_agents(cwd: str) -> list[AgentInfo]:
    """Get currently active sub-agents from state."""
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)
    agents = state.get("active_agents", {})
    return [
        AgentInfo(
            agent_id=aid,
            agent_type=info.get("agent_type", ""),
            started_at=info.get("started_at", ""),
            cost_usd=info.get("cost_usd", 0.0),
            tool_calls=info.get("tool_calls", 0),
        )
        for aid, info in agents.items()
    ]


def get_completed_agents(cwd: str) -> list[AgentInfo]:
    """Get completed sub-agents from state."""
    state_path = Path(cwd) / ".tribunal" / "state.json"
    state = locked_read_json(state_path)
    completed = state.get("completed_agents", [])
    return [
        AgentInfo(
            agent_id=info.get("agent_id", ""),
            agent_type=info.get("agent_type", ""),
            started_at=info.get("started_at", ""),
            stopped_at=info.get("stopped_at", ""),
            cost_usd=info.get("cost_usd", 0.0),
            tool_calls=info.get("tool_calls", 0),
        )
        for info in completed
    ]


def check_agent_policy(event: HookEvent) -> tuple[bool, str]:
    """Check if an agent action is allowed by multi-agent policy.

    Returns (allowed, reason). Called from hooks on SubagentStart and PreToolUse.
    """
    policy = load_multi_agent_policy(event.cwd)

    # Check max concurrent agents
    if policy.max_concurrent_agents > 0 and event.hook_event_name == "SubagentStart":
        active = get_active_agents(event.cwd)
        if len(active) >= policy.max_concurrent_agents:
            return False, (
                f"Max concurrent agents ({policy.max_concurrent_agents}) reached. "
                f"Currently active: {len(active)}."
            )

    # Check per-agent budget
    if policy.per_agent_budget > 0 and event.agent_id:
        state_path = Path(event.cwd) / ".tribunal" / "state.json"
        state = locked_read_json(state_path)
        agents = state.get("active_agents", {})
        agent_id = event.agent_id
        if agent_id in agents:
            agent_cost = agents[agent_id].get("cost_usd", 0.0)
            if agent_cost >= policy.per_agent_budget:
                return False, (
                    f"Agent {agent_id} cost ${agent_cost:.2f} exceeds "
                    f"per-agent budget ${policy.per_agent_budget:.2f}."
                )

    # Check shared session budget
    if policy.shared_session_budget > 0:
        state_path = Path(event.cwd) / ".tribunal" / "state.json"
        state = locked_read_json(state_path)
        total_cost = state.get("session_cost_usd", 0.0)
        if total_cost >= policy.shared_session_budget:
            return False, (
                f"Shared session budget ${policy.shared_session_budget:.2f} exceeded. "
                f"Total cost: ${total_cost:.2f}."
            )

    return True, ""


def format_agent_tree(cwd: str) -> str:
    """Format active and completed agents as a tree view."""
    active = get_active_agents(cwd)
    completed = get_completed_agents(cwd)
    policy = load_multi_agent_policy(cwd)

    lines = ["\n  ⚖  Tribunal Agent Tree\n"]

    if policy.max_concurrent_agents > 0:
        lines.append(f"  Policy: max {policy.max_concurrent_agents} concurrent agents")
    if policy.per_agent_budget > 0:
        lines.append(f"  Per-agent budget: ${policy.per_agent_budget:.2f}")
    if policy.shared_session_budget > 0:
        lines.append(f"  Shared budget: ${policy.shared_session_budget:.2f}")

    if active:
        lines.append(f"\n  Active Agents ({len(active)}):")
        for a in active:
            lines.append(f"    ├── {a.agent_id} [{a.agent_type or 'agent'}]")
            lines.append(f"    │   Started: {a.started_at}")
            lines.append(f"    │   Cost: ${a.cost_usd:.4f}  Tools: {a.tool_calls}")
    else:
        lines.append("\n  No active agents.")

    if completed:
        lines.append(f"\n  Completed Agents ({len(completed)}):")
        for a in completed[-10:]:  # Show last 10
            lines.append(f"    └── {a.agent_id} [{a.agent_type or 'agent'}]")
            lines.append(f"        {a.started_at} → {a.stopped_at}")
            lines.append(f"        Cost: ${a.cost_usd:.4f}  Tools: {a.tool_calls}")

    lines.append("")
    return "\n".join(lines)
