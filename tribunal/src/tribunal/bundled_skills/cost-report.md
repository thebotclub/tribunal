---
name: cost-report
description: Session cost breakdown and trend analysis for Claude Code usage.
tags:
  - cost
  - monitoring
  - budget
trigger: manual
---

# Cost Report

Generate a cost breakdown for the current session and historical trends.

## Current Session

Run `tribunal cost report` to see:
- Total session cost in USD
- Token usage (input/output breakdown)
- Model used
- Budget usage percentage

## Budget Management

Set a session budget to prevent runaway costs:

```bash
# Set a $5 per-session budget
tribunal cost budget set 5.00

# Set a $20 daily budget
tribunal cost budget set --daily 20.00
```

When the budget threshold is reached (default 80%), Tribunal will warn.
When exceeded, Tribunal will block further operations.

## Cost Optimization Tips

1. **Use cheaper models for simple tasks** — Haiku for formatting, Opus for architecture
2. **Be specific in prompts** — Less back-and-forth means fewer tokens
3. **Batch related changes** — One session for related work
4. **Review before running** — Check plans before execution to avoid rework
