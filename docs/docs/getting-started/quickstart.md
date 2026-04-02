# Quick Start

## 1. Initialize

```bash
tribunal init
```

## 2. Test Your Rules

```bash
tribunal rules list
tribunal rules test --tool Bash --input '{"command": "rm -rf /"}'
```

## 3. Start Coding with Claude Code

Rules are enforced automatically through Claude Code hooks. Every tool call is evaluated against your rules before execution.

## 4. Check the Audit Log

```bash
tribunal audit show
tribunal audit stats
```

## 5. Monitor Costs

```bash
tribunal cost show
tribunal cost set-budget --session 5.00 --daily 20.00
```

## 6. Run a Health Check

```bash
tribunal doctor
```

## Using the SDK

```python
from tribunal.sdk import TribunalSDK

sdk = TribunalSDK("/path/to/project")

# Evaluate an event
result = sdk.evaluate("PreToolUse", tool_name="Bash")
print(f"Allowed: {result.allowed}")

# Check costs
snapshot = sdk.cost_snapshot()

# List rules
rules = sdk.list_rules()
```
