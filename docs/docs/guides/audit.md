# Audit Logging

Every tool call and rule evaluation is logged to `.tribunal/audit.jsonl`.

## View the Log

```bash
tribunal audit show
tribunal audit stats
```

## Rotate Logs

```bash
tribunal audit rotate
```

Rotation keeps the last 5 log files and starts a fresh one.

## Export HTML Report

```bash
tribunal dashboard --html report.html
```

## SDK

```python
sdk = TribunalSDK("/path/to/project")
entries = sdk.audit_entries(limit=50)
stats = sdk.audit_stats()
sdk.rotate_audit()
```
