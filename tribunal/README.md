# Tribunal

**Quality gates for AI-generated code.** v2.0.1

Tribunal scans code for secrets, enforces TDD, lints Python / TypeScript / Go, and outputs SARIF — in one command. Works everywhere: CI pipelines, pre-commit hooks, local dev. Agent-agnostic.

> 5 checkers · SARIF 2.1.0 · GitHub Action · pre-commit hook

## Quick Start

```bash
pip install tribunal
tribunal ci .
```

That's it. Tribunal walks every source file, runs applicable checkers, and exits non-zero if anything fails.

## What It Does

| Checker | What it catches |
|---------|----------------|
| **Secrets** | AWS keys, GitHub tokens, Anthropic/OpenAI keys, private keys, JWTs, database URLs, generic API keys (14 patterns) |
| **Python** | Ruff lint violations, Pyright/mypy type errors |
| **TypeScript** | ESLint issues, `tsc --noEmit` type errors |
| **Go** | `go vet` issues, golangci-lint findings |
| **TDD** | Source files with no corresponding test file (Python, TypeScript, Go) |

Secrets scanning runs on every file. Language checkers run only on matching extensions.

## Output Formats

```bash
tribunal ci .                    # Human-readable text (default)
tribunal ci . --format sarif     # SARIF 2.1.0 for GitHub Code Scanning
tribunal ci . --format json      # Machine-readable JSON
tribunal ci . --output report.sarif  # Write to file
```

## CLI Commands

```bash
tribunal ci .               # Run all checkers on current directory
tribunal ci src/ tests/      # Check specific paths
tribunal ci . --checkers secrets,python  # Run only specific checkers
tribunal ci . --format sarif --output results.sarif  # SARIF output

tribunal init                # Set up project config
tribunal status              # Show active rules and config
tribunal rules               # List configured rules
tribunal audit               # View audit log
tribunal config              # Show resolved config
tribunal pack list           # Show available rule packs
tribunal doctor              # Health check
```

## GitHub Action

```yaml
# .github/workflows/tribunal.yml
name: Tribunal CI
on: [push, pull_request]

jobs:
  tribunal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: thebotclub/tribunal.dev/tribunal@v2.0.1
```

The action installs Tribunal, runs `tribunal ci .` with SARIF output, and uploads results to GitHub Code Scanning automatically.

## pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/thebotclub/tribunal.dev
    rev: v2.0.1
    hooks:
      - id: tribunal-ci        # Full check suite
      - id: tribunal-secrets   # Secrets only (fast)
```

## Secrets Scanning

14 built-in patterns covering:
- AWS access keys and secret keys
- GitHub personal access tokens (classic and fine-grained)
- Anthropic and OpenAI API keys
- Slack tokens and webhooks
- Private keys (RSA, EC, etc.)
- Database connection URLs with passwords
- JWTs, Bearer tokens
- Generic hex secrets and API keys

### `.secretsignore`

Suppress false positives with a `.secretsignore` file in your project root:

```
# Patterns (one per line, matched against file path)
docs/examples/*
test_fixtures/mock_keys.py
```

### Placeholder Detection

Tribunal automatically skips placeholder values like `your-api-key-here`, `CHANGE_ME`, `xxxx`, and `TODO` patterns — only real secrets trigger findings.

## TDD Enforcement

For every source file, Tribunal checks whether a corresponding test file exists:

| Source | Expected test |
|--------|--------------|
| `src/auth.py` | `tests/test_auth.py` or `test_auth.py` (sibling) |
| `src/api.ts` | `src/api.test.ts` or `src/api.spec.ts` |
| `internal/server.go` | `internal/server_test.go` |

Files that are reasonably excluded (test files themselves, `__init__.py`, `index.ts`, `main.go`) are skipped.

## Rule Packs

Pre-built rule sets for common standards:

```bash
tribunal pack list           # Show available packs
tribunal pack install soc2   # Install SOC 2 rules
```

Available: `soc2`, `startup`, `enterprise`, `security`.

## Configuration

Tribunal reads config from `.tribunal/config.yaml`:

```yaml
rules:
  tdd-python:
    match:
      path: "*.py"
    action: block
    condition: no-matching-test
    message: "Write a failing test first."

  no-secrets:
    action: block
    condition: contains-secret
    message: "Possible secret detected."
```

## Programmatic API

```python
from tribunal.checkers import run_checkers, collect_files
from tribunal.sarif import findings_to_sarif, sarif_to_json

files = collect_files("/path/to/project")
results = run_checkers(files, project_root="/path/to/project")

# Check pass/fail
passed = all(r.passed for r in results)

# Generate SARIF
sarif = findings_to_sarif(results, "/path/to/project")
print(sarif_to_json(sarif))
```

REST endpoints: `/api/projects`, `/api/summary`, `/api/projects/{id}/audit|cost|agents`.

## VS Code Extension

Visual governance in the editor sidebar:

- **Rules Tree** — See all rules with action icons
- **Audit Tree** — Browse recent events
- **Cost Tree** — Track budget usage
- **Agents Tree** — Monitor sub-agents
- **Status Bar** — Rule count and block count at a glance

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
├── claudeconfig.json   # Hook wiring for Claude Code
└── memory/             # Tribunal memory entries
    ├── tribunal-rule-*.md
    └── tribunal-session-*.md
```

## License

MIT
