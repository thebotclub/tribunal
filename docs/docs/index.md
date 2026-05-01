# Tribunal

**Quality gates for AI-generated code**

Tribunal enforces TDD, secret scanning, linting, and audit-friendly checks across CI, pre-commit, local development, and AI coding agent workflows.

## Features

- **Rule Engine** — YAML-based rules that block, warn, or rewrite AI tool usage
- **Audit Logging** — JSONL audit trail with rotation for hook-based workflows
- **Rule Packs** — Pre-built rule sets (SOC 2, Startup, Enterprise, Security)
- **Programmatic SDK** — Python API for embedding governance into custom tooling
- **VS Code Extension** — Visual rule management, audit viewer, cost dashboard
- **Agent Hooks** — Optional hook integration for Claude Code-compatible event streams

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
