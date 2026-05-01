# Quick Start

## 1. Initialize

```bash
tribunal init
```

## 2. Inspect Your Rules

```bash
tribunal rules
```

## 3. Run Quality Checks

```bash
tribunal ci .
```

Use `--format sarif` for GitHub Code Scanning or `--format json` for custom automation.

## 4. Check the Audit Log

```bash
tribunal audit
```

## 5. Add Hook Enforcement

```bash
tribunal init
```

When used with Claude Code hooks, every configured tool event is evaluated against your rules before execution.

## 6. Run a Health Check

```bash
tribunal doctor
```

## 7. Add CI or pre-commit

See the repository README for GitHub Action and pre-commit examples.
