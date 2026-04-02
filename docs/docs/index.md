# Tribunal

**AI Governance Framework for Claude Code**

Tribunal enforces rules, tracks costs, manages compliance, and governs multi-agent workflows — all through Claude Code's native hook system.

## Features

- **Rule Engine** — YAML-based rules that block, warn, or rewrite AI tool usage
- **Cost Tracking** — Real-time budget enforcement with session and daily limits
- **Audit Logging** — JSONL audit trail with rotation, analytics, and HTML reports
- **Multi-Agent Governance** — Per-agent policies, task-based permissions, audit trails
- **Rule Packs** — Pre-built rule sets (SOC 2, Startup, Enterprise, Security)
- **Programmatic SDK** — Python API for embedding governance into custom tooling
- **VS Code Extension** — Visual rule management, audit viewer, cost dashboard
- **Team Dashboard** — HTTP API for centralized project governance

## Quick Install

```bash
pip install tribunal
tribunal init
```

## Next Steps

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)
- [Rules Reference](guides/rules.md)
- [SDK API](api/sdk.md)
