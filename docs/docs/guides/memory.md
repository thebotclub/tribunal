# Memory Management

Tribunal can inject governance rules into Claude Code's CLAUDE.md memory files.

## Inject Rules

```bash
tribunal memory inject
```

## View Memory Stats

```bash
tribunal memory stats
```

## Clear Tribunal Memory

```bash
tribunal memory clear
```

## SDK

```python
sdk = TribunalSDK("/path/to/project")
stats = sdk.memory_stats()
count = sdk.inject_rules_as_memory()
```
