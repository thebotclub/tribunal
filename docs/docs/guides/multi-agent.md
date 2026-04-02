# Multi-Agent Governance

Manage sub-agents spawned by Claude Code with per-agent policies.

## Agent Policies

Configure in `.tribunal/config.yaml`:

```yaml
multi_agent:
  max_agents: 5
  require_approval: true
  agent_permissions:
    coder:
      allowed_tools: ["FileEdit", "Read"]
      blocked_tools: ["Bash"]
    reviewer:
      allowed_tools: ["Read", "Grep"]
```

## CLI Commands

```bash
# List active agents
tribunal agents list

# View agent policies
tribunal agents policy

# View per-agent audit trail
tribunal agents trail <agent-id>
```

## SDK

```python
sdk = TribunalSDK("/path/to/project")
agents = sdk.active_agents()
trail = sdk.agent_trail("agent-123")
```

## Escalation Detection

Tribunal detects permission escalation patterns (grant followed by deny on the same resource) and logs them for audit.
