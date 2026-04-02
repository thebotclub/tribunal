# Gate Protocol Reference

`tribunal-gate` is the hook binary that Claude Code calls on every tool event.

## How It Works

1. Claude Code sends a JSON event to `tribunal-gate` via stdin
2. Gate evaluates all matching rules
3. Returns exit code 0 (allow) or 2 (block) with optional JSON output

## Event Format

```json
{
  "hook_event_name": "PreToolUse",
  "session_id": "abc-123",
  "tool_name": "Bash",
  "tool_input": {"command": "echo hello"}
}
```

## Response Format

```json
{
  "allow": false,
  "reason": "Blocked by rule: no-rm-rf"
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Allow — operation proceeds |
| 2 | Block — operation is prevented |

## Hook Registration

In `.claude/claudeconfig.json`:

```json
{
  "hooks": {
    "PreToolUse": [{"command": "tribunal-gate"}],
    "PostToolUse": [{"command": "tribunal-gate"}]
  }
}
```
