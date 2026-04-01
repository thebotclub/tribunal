---
name: quality-gate
description: Run all quality gates (type check, lint, tests) and report status.
tags:
  - quality
  - ci
  - validation
trigger: manual
---

# Quality Gate

Run all quality checks before completing work on a task.

## Checks

Run these in order. Fix issues before moving to the next check:

### 1. Type Safety
```bash
# TypeScript
npx tsc --noEmit

# Python
mypy src/
```

### 2. Linting
```bash
# JavaScript/TypeScript
npx eslint .

# Python
ruff check .
```

### 3. Tests
```bash
# JavaScript/TypeScript
npm test

# Python
pytest
```

### 4. Security
```bash
# Check dependencies
npm audit
# or
pip audit
```

## Quality Rules

Configure in `.tribunal/rules.yaml`:

```yaml
rules:
  type-safety:
    trigger: PostToolUse
    match: { tool: FileEdit, path: "**/*.ts" }
    condition: type-check
    action: warn
    message: "TypeScript errors detected."

  lint-clean:
    trigger: PostToolUse
    match: { tool: FileEdit }
    condition: lint-check
    action: warn
    message: "Lint errors detected."
```
