# Cost Tracking

Monitor and enforce budgets for AI-assisted development sessions.

## Set Budgets

```bash
tribunal cost set-budget --session 5.00 --daily 20.00
```

## Check Status

```bash
tribunal cost show
```

## SDK

```python
sdk = TribunalSDK("/path/to/project")
sdk.set_budget(session_usd=5.0, daily_usd=20.0)
snapshot = sdk.cost_snapshot()
```

## Cost-Exceeded Condition

Add to any rule to block when budget is exceeded:

```yaml
rules:
  budget-gate:
    trigger: PreToolUse
    action: block
    match:
      tool: "*"
    condition: cost-exceeded
    message: "Budget exceeded"
```
