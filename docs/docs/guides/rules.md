# Rules Reference

Rules are defined in `.tribunal/rules.yaml` and evaluated on every Claude Code hook event.

## Rule Structure

```yaml
rules:
  rule-name:
    trigger: PreToolUse       # Hook event: PreToolUse, PostToolUse, etc.
    action: block             # block, warn, or rewrite
    match:
      tool: "Bash"            # Glob pattern for tool name
      path: "*.env"           # Glob pattern for file path
    condition: contains-secret # Built-in condition (optional)
    message: "Blocked!"       # Message shown when triggered
    enabled: true             # Toggle rule on/off
    require_tool: false       # If true, missing tool blocks instead of skips
```

## Actions

| Action | Behavior |
|--------|----------|
| `block` | Prevent the tool call entirely |
| `warn` | Allow but add a warning to context |
| `rewrite` | Modify tool input before execution |

## Match Patterns

- `tool`: Glob pattern matched against tool name. Use `|` for alternatives: `"Bash|Execute"`.
- `path`: Glob pattern matched against file paths in tool input.

## Built-in Conditions

| Condition | Description |
|-----------|-------------|
| `no-matching-test` | Block Python edits without a test file |
| `no-matching-test-ts` | Block TypeScript edits without a test file |
| `contains-secret` | Block content with API keys/tokens/secrets |
| `cost-exceeded` | Block when budget is exceeded |
| `type-check` | Block if type checking fails |
| `lint-check` | Block if linting fails |
| `mypy-check` | Block if mypy finds errors |
| `run-command` | Run an external command to decide |

## Examples

### Block dangerous commands

```yaml
rules:
  no-rm-rf:
    trigger: PreToolUse
    action: block
    match:
      tool: Bash
    message: "Bash commands are reviewed"
```

### Require tests for Python files

```yaml
rules:
  tdd-python:
    trigger: PreToolUse
    action: block
    match:
      tool: FileEdit
      path: "*.py"
    condition: no-matching-test
    message: "Write tests first"
```

### Block secrets in code

```yaml
rules:
  no-secrets:
    trigger: PreToolUse
    action: block
    match:
      tool: FileEdit
    condition: contains-secret
    message: "Never commit secrets"
```
