# Tribunal

**Enterprise-grade discipline for Claude Code.** v1.1.0

Tribunal enforces TDD, quality gates, and team standards on Claude Code sessions via the hook protocol. It includes a fail-closed safety gate, lifecycle hooks for all 13 event types, multi-agent governance, an MCP server, review agents, cost governance, memory injection, and enterprise fleet tools.

> 21 modules · 371 tests · 21+ CLI commands

## Quick Start

```bash
pip install tribunal
cd your-project
tribunal init
```

This generates:
- `.tribunal/rules.yaml` — your project rules
- `.claude/claudeconfig.json` — hook wiring for Claude Code

## What It Does

| Feature | How |
|---------|-----|
| **TDD enforcement** | Blocks file edits unless tests exist first |
| **Secret scanning** | Prevents hardcoded credentials in code |
| **Fail-closed gate** | Blocks on errors by default — never fails open silently |
| **Audit trail** | Logs every tool call with automatic log rotation at 10 MB |
| **Atomic I/O** | File locking + atomic writes prevent concurrent session corruption |
| **Config validation** | Schema validation catches misconfigs on load |
| **Cost budgets** | Per-session and daily budgets with analytics and anomaly detection |
| **Hook lifecycle** | 13 event handlers — sessions, failures, files, permissions, compaction |
| **Multi-agent governance** | Per-agent budgets, max concurrency, shared session budget, agent tree |
| **Review agents** | 4 parallel agents (TDD, security, quality, spec) |
| **MCP server** | Expose rules/audit as MCP tools for multi-agent workflows |
| **Skills system** | 5 bundled skills + custom skill support |
| **Memory injection** | Rules into Claude's memory with 200-file limit and LRU eviction |
| **Model routing** | Cost-aware routing between models |
| **Air-gapped bundles** | Package config for offline deployment |
| **Audit dashboard** | HTML report + terminal stats for audit data |
| **Marketplace** | Share and discover community rule bundles |
| **Enterprise managed** | Fleet policies via `/etc/tribunal/config.yaml` |

## Commands

```bash
# Foundation
tribunal init            # Set up hooks in current project
tribunal status          # Show active rules and audit summary
tribunal rules           # List all rules and their config
tribunal audit           # View recent audit log entries
tribunal audit -n 50     # Show last 50 entries

# Cost Management
tribunal cost            # Show cost report
tribunal cost budget 5   # Set $5 per-session budget
tribunal cost budget 20 --daily  # Set $20 daily budget
tribunal cost reset      # Reset session counters
tribunal analytics       # Cost trends and anomaly detection
tribunal analytics --json  # Machine-readable output

# Skills & Permissions
tribunal skills list     # List available skills
tribunal skills install tdd-cycle  # Install a bundled skill
tribunal skills create my-flow     # Create a custom skill
tribunal permissions show          # List permission presets
tribunal permissions apply strict  # Apply strict permissions

# Review & Reports
tribunal review          # Run all 4 review agents
tribunal review --agents tdd,security  # Run specific agents
tribunal report          # Text report for CI/CD
tribunal report --format json  # JSON report for CI/CD

# Configuration
tribunal config          # Show resolved config (4-level cascade)
tribunal plugin show     # Show plugin manifest
tribunal plugin install  # Write manifest to .tribunal/

# MCP Server
tribunal mcp-serve       # Start MCP server (stdin/stdout)

# Team & Enterprise
tribunal sync export     # Export rules to YAML bundle
tribunal sync import rules.yaml  # Import rules from bundle
tribunal managed         # Show managed policy status
tribunal model           # Show model routing config
tribunal model resolve FileEdit  # Resolve model for a tool

# Marketplace
tribunal marketplace list       # List marketplace bundles
tribunal marketplace register bundle.yaml  # Register a bundle
tribunal marketplace install my-rules     # Install from marketplace
tribunal marketplace remove my-rules      # Remove from marketplace

# Memory
tribunal memory list     # List tribunal memory entries
tribunal memory inject   # Inject rules into Claude memory
tribunal memory summary "Session done"  # Write session summary
tribunal memory clear    # Clear tribunal memory entries

# Air-Gapped Bundles
tribunal bundle export   # Export self-contained bundle
tribunal bundle import bundle.json  # Import bundle
tribunal bundle validate bundle.json  # Validate bundle file

# Dashboard
tribunal dashboard       # Show audit stats in terminal
tribunal dashboard html  # Export HTML audit report

# Multi-Agent Governance
tribunal agents tree     # Show agent tree with costs
```

## Rule Format

Rules live in `.tribunal/rules.yaml`:

```yaml
rules:
  tdd-python:
    trigger: PreToolUse
    match:
      tool: "FileEdit|FileWrite"
      path: "*.py"
    action: block
    condition: no-matching-test
    message: "Write a failing test first."

  no-secrets:
    trigger: PreToolUse
    match:
      tool: "FileEdit|FileWrite"
    action: block
    condition: contains-secret
    message: "Possible secret detected. Use environment variables."

  type-safety:
    trigger: PostToolUse
    match:
      tool: FileEdit
      path: "**/*.ts"
    run: "npx tsc --noEmit --pretty"
    action: block
    message: "TypeScript errors found"
```

### Built-in Conditions

| Condition | Description |
|-----------|-------------|
| `no-matching-test` | No `test_<module>.py` exists for the edited `.py` file |
| `no-matching-test-ts` | No `<module>.test.ts` exists for the edited `.ts` file |
| `contains-secret` | Content matches common secret patterns (API keys, tokens, etc.) |
| `cost-exceeded` | Session cost exceeds budget threshold |
| `type-check` | Runs `tsc --noEmit` on TypeScript files |
| `lint-check` | Runs eslint (JS/TS) or ruff (Python) on changed files |
| `mypy-check` | Runs mypy on Python files |
| `run-command` | Runs a custom shell command via `rule.run` |

### Actions

- `block` — Prevent the tool call (exit code 2)
- `warn` — Log a warning but allow it (exit code 0)
- `audit` — Silent logging only (exit code 0)

## How It Works

Tribunal plugs into Claude Code's [hook system](https://docs.anthropic.com/en/docs/claude-code/hooks):

1. **`tribunal init`** writes hook config to `.claude/claudeconfig.json`
2. Claude Code calls `tribunal-gate` on every tool use and lifecycle event
3. The gate reads the hook event (JSON on stdin), routes lifecycle hooks, evaluates rules, and responds
4. Results are logged to `.tribunal/audit.jsonl` (auto-rotated at 10 MB)

The gate is **fail-closed by default** — if anything goes wrong parsing the event or evaluating rules, the tool call is blocked (exit code 2). Set `TRIBUNAL_FAIL_MODE=open` to override.

## Hook Lifecycle

Tribunal handles 13 lifecycle event types beyond rule evaluation:

| Event | Handler |
|-------|---------|
| `SessionEnd` | Flush analytics, finalize cost, write session summary |
| `PostToolUseFailure` | Track tool failure rates, detect flaky patterns |
| `FileChanged` | Monitor external file changes in real time |
| `CwdChanged` | Detect project context switches, reload rules |
| `ConfigChange` | Alert on unauthorized settings modifications |
| `PermissionRequest` | Log what was requested and why |
| `PermissionDenied` | Track denied actions for compliance |
| `PreCompact` | Save critical state before context compaction |
| `PostCompact` | Re-inject rules after compaction |
| `SubagentStart` / `SubagentStop` | Track sub-agent lifecycle |
| `TaskCreated` / `TaskCompleted` | Task-level audit |

All hooks are registered automatically by `tribunal init`.

## Multi-Agent Governance

Enforce policies across Claude Code coordinator mode — main agent + sub-agents:

```yaml
# .tribunal/config.yaml
multi_agent:
  max_concurrent_agents: 3
  per_agent_budget: 1.00       # $1 per sub-agent
  shared_session_budget: 5.00  # $5 total across all agents
```

```bash
tribunal agents tree    # Show active/completed agents with costs
```

Per-agent cost budgets, max concurrency limits, and shared session budgets are enforced on every tool call.

## MCP Server

Tribunal exposes 6 MCP tools when running as a server:

```bash
tribunal mcp-serve  # Start JSON-RPC 2.0 server on stdin/stdout
```

Tools: `tribunal_evaluate_rule`, `tribunal_list_rules`, `tribunal_get_audit`, `tribunal_check_cost`, `tribunal_run_review`, `tribunal_get_config`

## Review Agents

Run 4 parallel review agents on your changed files:

```bash
tribunal review             # All agents
tribunal review --agents tdd,security  # Specific agents
```

| Agent | Focus |
|-------|-------|
| `tdd` | Test coverage and TDD compliance |
| `security` | Vulnerability detection |
| `quality` | Code quality and maintainability |
| `spec` | Spec conformance |

## Configuration Cascade

Tribunal resolves config from 4 levels (highest to lowest priority):

1. **Managed** — Enterprise `/etc/tribunal/config.yaml`
2. **User** — `~/.tribunal/config.yaml`
3. **Project** — `.tribunal/config.yaml`
4. **Environment** — `TRIBUNAL_*` env vars

## Cost Management

```bash
tribunal cost budget 5.00        # $5 per session
tribunal cost budget 20 --daily  # $20 per day
tribunal analytics               # Trends and anomalies
```

When 80% of budget is used, Tribunal warns. When exceeded, it blocks.

## Skills

**Bundled skills:** `tdd-cycle`, `spec-review`, `security-audit`, `cost-report`, `quality-gate`

```bash
tribunal skills install tdd-cycle    # Install to .tribunal/skills/
tribunal skills create my-workflow   # Create custom skill scaffold
```

## Memory Injection

Inject Tribunal rules into Claude Code's memory for contextual surfacing:

```bash
tribunal memory inject   # Rules become memory entries
tribunal memory summary "Fixed the auth bug"  # Session log
```

## Air-Gapped Deployment

Package all rules, skills, and config into a single file for offline environments:

```bash
tribunal bundle export               # Creates .tribunal/bundle.json
tribunal bundle import bundle.json   # Import into new project
```

## Permission Policies

```bash
tribunal permissions apply strict  # Apply strict deny/allow rules
```

Presets: `strict` (no curl/wget/sudo/force-push), `standard` (balanced), `minimal` (basic safety).

## Architecture

```
.tribunal/
├── rules.yaml          # Rule definitions
├── config.yaml         # Project configuration
├── permissions.yaml    # Permission policies
├── audit.jsonl         # Audit log (gitignored)
├── state.json          # Cost tracking state (gitignored)
├── skills/             # Custom skills
└── bundle.json         # Air-gapped bundle (export)

.claude/
├── claudeconfig.json   # Hook wiring
└── memory/             # Tribunal memory entries
    ├── tribunal-rule-*.md
    └── tribunal-session-*.md
```

## License

MIT
