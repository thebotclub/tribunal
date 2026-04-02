# SDK API Reference

The `TribunalSDK` class provides a programmatic Python interface to all Tribunal features.

## Installation

```python
from tribunal.sdk import TribunalSDK
```

## Constructor

```python
sdk = TribunalSDK(cwd="/path/to/project")  # defaults to current directory
```

## Methods

### evaluate(hook_event_name, tool_name, tool_input, session_id)

Evaluate a simulated event against all active rules.

```python
result = sdk.evaluate("PreToolUse", tool_name="Bash", tool_input={"command": "rm -rf /"})
result.allowed   # bool
result.blocked   # bool
result.message   # str — combined reason messages
result.messages  # list[str]
```

### list_rules()

Returns all rules as a list of dicts.

```python
rules = sdk.list_rules()
# [{"name": "tdd-python", "trigger": "PreToolUse", "action": "block", ...}]
```

### install_pack(name, merge=True)

Install a rule pack. Returns `(success: bool, messages: list[str])`.

```python
ok, msgs = sdk.install_pack("soc2")
```

### cost_snapshot()

Get current cost tracking state as a dict.

### set_budget(session_usd, daily_usd)

Set cost budgets.

### audit_entries(limit=50)

Read recent audit log entries.

### audit_stats()

Get audit log statistics.

### rotate_audit()

Rotate the audit log. Returns `True` if rotated.

### resolve_config()

Get the full resolved configuration.

### validate_config()

Validate project config. Returns list of errors (empty = valid).

### memory_stats()

Get memory capacity statistics.

### inject_rules_as_memory()

Inject rules into Claude Code memory. Returns count of rules injected.

### active_agents()

Get active sub-agents as list of dicts.

### agent_trail(agent_id)

Get per-agent audit trail.

### doctor()

Run health checks. Returns dict with `issues`, `warnings`, `checks`, `healthy`.
