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
    Supports agent_permissions matching by agent_type and task description patterns.
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

    # Task-description-based permission matching
    if policy.agent_permissions and event.tool_name:
        agent_type = event.agent_type or "default"
        perms = policy.agent_permissions.get(agent_type, policy.agent_permissions.get("default", {}))
        allowed_tools = perms.get("allowed_tools", [])
        blocked_tools = perms.get("blocked_tools", [])
        # Blocked takes precedence
        if blocked_tools and _tool_matches(event.tool_name, blocked_tools):
            return False, (
                f"Agent type '{agent_type}' is blocked from using '{event.tool_name}'."
            )
        if allowed_tools and not _tool_matches(event.tool_name, allowed_tools):
            return False, (
                f"Agent type '{agent_type}' is not allowed to use '{event.tool_name}'. "
                f"Allowed: {allowed_tools}"
            )

    return True, ""


def _tool_matches(tool_name: str, patterns: list[str]) -> bool:
    """Check if a tool name matches any pattern in the list (glob-style)."""
    import fnmatch
    return any(fnmatch.fnmatch(tool_name, p) for p in patterns)


def log_agent_event(cwd: str, agent_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
    """Write an audit entry to a per-agent audit trail.

    Each agent gets its own JSONL file at .tribunal/agents/<agent_id>.jsonl
    """
    import json

    agents_dir = Path(cwd) / ".tribunal" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize agent_id for filename
    safe_id = "".join(c for c in agent_id if c.isalnum() or c in "-_")[:64] or "unknown"
    trail_path = agents_dir / f"{safe_id}.jsonl"

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_id": agent_id,
        "event": event_type,
    }
    if details:
        entry["details"] = details

    with open(trail_path, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def get_agent_trail(cwd: str, agent_id: str) -> list[dict[str, Any]]:
    """Read the per-agent audit trail."""
    import json

    safe_id = "".join(c for c in agent_id if c.isalnum() or c in "-_")[:64] or "unknown"
    trail_path = Path(cwd) / ".tribunal" / "agents" / f"{safe_id}.jsonl"
    if not trail_path.is_file():
        return []

    entries = []
    for line in trail_path.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


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
