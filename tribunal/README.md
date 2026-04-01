# Tribunal

**Enterprise-grade discipline for Claude Code.**

Tribunal enforces TDD, quality gates, and team standards on Claude Code sessions via the hook protocol.

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
| **Audit trail** | Logs every tool call to `.tribunal/audit.jsonl` |
| **Custom rules** | Define your own in `.tribunal/rules.yaml` |

## Commands

```bash
tribunal init            # Set up hooks in current project
tribunal status          # Show active rules and audit summary
tribunal rules           # List all rules and their config
tribunal audit           # View recent audit log entries
tribunal audit -n 50     # Show last 50 entries
tribunal cost            # Show cost report
tribunal cost budget 5   # Set $5 per-session budget
tribunal cost budget 20 --daily  # Set $20 daily budget
tribunal cost reset      # Reset session counters
tribunal skills list     # List available skills
tribunal skills install tdd-cycle  # Install a bundled skill
tribunal skills create my-flow     # Create a custom skill
tribunal permissions show          # List permission presets
tribunal permissions apply strict  # Apply strict permissions
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

### Custom Shell Commands

Run any command as a gate — block on non-zero exit:

```yaml
rules:
  type-safety:
    trigger: PostToolUse
    match:
      tool: FileEdit
      path: "**/*.ts"
    run: "npx tsc --noEmit --pretty"
    action: block
    message: "TypeScript errors found"
```

### Actions

- `block` — Prevent the tool call (exit code 2)
- `warn` — Log a warning but allow it (exit code 0)
- `audit` — Silent logging only (exit code 0)

## How It Works

Tribunal plugs into Claude Code's [hook system](https://docs.anthropic.com/en/docs/claude-code/hooks):

1. **`tribunal init`** writes hook config to `.claude/claudeconfig.json`
2. Claude Code calls `tribunal-gate` on every tool use
3. The gate reads the hook event (JSON on stdin), evaluates rules, and responds
4. Results are logged to `.tribunal/audit.jsonl`

## Cost Management

Set budgets to prevent runaway spending:

```bash
tribunal cost budget 5.00        # $5 per session
tribunal cost budget 20 --daily  # $20 per day
tribunal cost report             # View current costs
```

When 80% of budget is used, Tribunal warns. When exceeded, it blocks.

## Skills

Tribunal ships bundled skills and supports custom ones. Skills are markdown files with YAML frontmatter that Claude Code discovers automatically.

**Bundled skills:** `tdd-cycle`, `spec-review`, `security-audit`, `cost-report`, `quality-gate`

```bash
tribunal skills install tdd-cycle    # Install to .tribunal/skills/
tribunal skills create my-workflow   # Create custom skill scaffold
```

## Permission Policies

Apply security presets for Claude Code's deny/allow system:

```bash
tribunal permissions show        # List presets
tribunal permissions apply strict  # Apply strict policy
```

Presets: `strict` (no curl/wget/sudo/force-push), `standard` (balanced), `minimal` (basic safety).

## License

MIT
