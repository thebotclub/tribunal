"""Tribunal CLI -- quality gates for AI-generated code.

Commands:
  tribunal init         Set up hooks in the current project
  tribunal status       Show current rules and audit summary
  tribunal rules        List active rules
  tribunal audit        Show recent audit log entries
  tribunal config       Show resolved configuration
  tribunal pack         Rule pack management
  tribunal doctor       Run health checks on Tribunal setup
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from . import __version__


# -- Config Templates ----------------------------------------------------------

_CLAUDE_CONFIG = {
    "hooks": {
        "PreToolUse": [
            {
                "if": {"matcher": "FileEdit|FileWrite|Bash"},
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "PostToolUse": [
            {
                "if": {"matcher": "FileEdit|FileWrite|Bash"},
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "SessionStart": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "SessionEnd": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "PostToolUseFailure": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "FileChanged": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "CwdChanged": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "SubagentStart": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
        "SubagentStop": [
            {
                "run": [{"command": "tribunal-gate"}],
            }
        ],
    }
}

_DEFAULT_RULES = {
    "rules": {
        "tdd-python": {
            "trigger": "PreToolUse",
            "match": {"tool": "FileEdit|FileWrite", "path": "*.py"},
            "action": "block",
            "condition": "no-matching-test",
            "message": "Write a failing test first. Create tests/test_<module>.py before editing production code.",
        },
        "tdd-typescript": {
            "trigger": "PreToolUse",
            "match": {"tool": "FileEdit|FileWrite", "path": "*.ts"},
            "action": "block",
            "condition": "no-matching-test-ts",
            "message": "Write a failing test first. Create <module>.test.ts before editing production code.",
        },
        "no-secrets": {
            "trigger": "PreToolUse",
            "match": {"tool": "FileEdit|FileWrite"},
            "action": "block",
            "condition": "contains-secret",
            "message": "Possible secret/credential detected. Use environment variables instead.",
        },
    }
}


# -- Commands ------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Set up Tribunal hooks in the current project."""
    project_dir = Path.cwd()

    # 1. Create .tribunal/ directory and rules.yaml
    tribunal_dir = project_dir / ".tribunal"
    tribunal_dir.mkdir(exist_ok=True)

    rules_path = tribunal_dir / "rules.yaml"
    if rules_path.exists() and not args.force:
        print(f"  [ok] Rules already exist at {rules_path.relative_to(project_dir)}")
    else:
        with open(rules_path, "w") as f:
            yaml.dump(_DEFAULT_RULES, f, default_flow_style=False, sort_keys=False)
        print(f"  [ok] Created {rules_path.relative_to(project_dir)}")

    # 2. Create/update .claude/claudeconfig.json
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    config_path = claude_dir / "claudeconfig.json"
    if config_path.exists():
        with open(config_path) as f:
            existing = json.load(f)
        existing.setdefault("hooks", {})
        for event, hooks in _CLAUDE_CONFIG["hooks"].items():
            existing_hooks = existing["hooks"].get(event, [])
            has_tribunal = any(
                "tribunal-gate" in str(h.get("run", [])) for h in existing_hooks
            )
            if not has_tribunal:
                existing["hooks"][event] = existing_hooks + hooks
        with open(config_path, "w") as f:
            json.dump(existing, f, indent=2)
        print(f"  [ok] Updated {config_path.relative_to(project_dir)} (merged hooks)")
    else:
        with open(config_path, "w") as f:
            json.dump(_CLAUDE_CONFIG, f, indent=2)
        print(f"  [ok] Created {config_path.relative_to(project_dir)}")

    # 3. Create .tribunal/.gitkeep for version control
    gitkeep = tribunal_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    # 4. Add audit log to .gitignore
    gitignore = project_dir / ".gitignore"
    ignore_line = ".tribunal/audit.jsonl"
    ignore_state = ".tribunal/state.json"
    if gitignore.exists():
        content = gitignore.read_text()
        additions = []
        if ignore_line not in content:
            additions.append(ignore_line)
        if ignore_state not in content:
            additions.append(ignore_state)
        if additions:
            with open(gitignore, "a") as f:
                f.write("\n# tribunal audit log (local only)\n")
                for line in additions:
                    f.write(line + "\n")
            print("  [ok] Added tribunal paths to .gitignore")
    else:
        with open(gitignore, "w") as f:
            f.write("# tribunal audit log (local only)\n")
            f.write(ignore_line + "\n")
            f.write(ignore_state + "\n")
        print("  [ok] Created .gitignore with tribunal exclusions")

    # 5. Check if tribunal-gate is on PATH
    if not shutil.which("tribunal-gate"):
        print()
        print("  [!]  tribunal-gate not found on PATH.")
        print("     Make sure tribunal is installed: pip install tribunal")
        print()

    print()
    print("  [T]  Tribunal initialized.")
    print()
    print("  Your AI coding sessions now enforce:")
    print("    * TDD -- tests required before production code")
    print("    * Secret scanning -- no hardcoded credentials")
    print("    * Audit trail -- all tool calls logged")
    print()
    print("  Customize rules in .tribunal/rules.yaml")
    print("  View audit log with: tribunal audit")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show current Tribunal status."""
    project_dir = Path.cwd()
    rules_path = project_dir / ".tribunal" / "rules.yaml"
    config_path = project_dir / ".claude" / "claudeconfig.json"
    audit_path = project_dir / ".tribunal" / "audit.jsonl"

    print(f"\n  [T]  Tribunal v{__version__}\n")

    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        hooks = config.get("hooks", {})
        hook_count = sum(len(v) for v in hooks.values())
        has_tribunal = "tribunal-gate" in json.dumps(hooks)
        if has_tribunal:
            print(
                f"  [ok] Hooks active -- {hook_count} hook(s) in .claude/claudeconfig.json"
            )
        else:
            print("  [!] Hooks exist but tribunal-gate not configured")
    else:
        print("  [x] No .claude/claudeconfig.json -- run: tribunal init")

    if rules_path.exists():
        with open(rules_path) as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", {})
        enabled = sum(
            1 for r in rules.values() if isinstance(r, dict) and r.get("enabled", True)
        )
        print(f"  [ok] {enabled} rule(s) active in .tribunal/rules.yaml")
        for name, rdef in rules.items():
            if isinstance(rdef, dict) and rdef.get("enabled", True):
                action = rdef.get("action", "block")
                icon = (
                    "[blocked]"
                    if action == "block"
                    else "[!]"
                    if action == "warn"
                    else "[note]"
                )
                print(f"    {icon} {name}: {rdef.get('message', '')[:60]}")
    else:
        print("  [x] No .tribunal/rules.yaml -- run: tribunal init")

    if audit_path.exists():
        lines = audit_path.read_text().strip().split("\n")
        total = len(lines)
        blocked = sum(1 for line in lines if '"allowed":false' in line)
        print(f"  [list] {total} audit entries ({blocked} blocked)")
    else:
        print("  [list] No audit log yet")

    print()
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    """List active rules."""
    project_dir = Path.cwd()
    rules_path = project_dir / ".tribunal" / "rules.yaml"

    if not rules_path.exists():
        print("No rules found. Run: tribunal init")
        return 1

    with open(rules_path) as f:
        data = yaml.safe_load(f) or {}

    rules = data.get("rules", {})
    print(f"\n  [T]  Tribunal Rules ({len(rules)} total)\n")

    for name, rdef in rules.items():
        if not isinstance(rdef, dict):
            continue
        enabled = rdef.get("enabled", True)
        action = rdef.get("action", "block")
        trigger = rdef.get("trigger", "?")
        match = rdef.get("match", {})
        condition = rdef.get("condition", "")
        message = rdef.get("message", "")

        status = "[ok]" if enabled else "[x]"
        action_icon = (
            "[blocked]"
            if action == "block"
            else "[!]"
            if action == "warn"
            else "[note]"
        )

        print(f"  {status} {name}")
        print(f"    {action_icon} {action} on {trigger}")
        if match:
            print(f"    match: {json.dumps(match)}")
        if condition:
            print(f"    condition: {condition}")
        if message:
            print(f"    -> {message[:80]}")
        print()

    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Show recent audit log entries."""
    project_dir = Path.cwd()
    audit_path = project_dir / ".tribunal" / "audit.jsonl"

    sub = getattr(args, "audit_command", None)

    if sub == "rotate":
        from .audit import rotate_audit_log

        if not audit_path.exists():
            print("  No audit log to rotate.")
            return 0
        rotated = rotate_audit_log(audit_path)
        if rotated:
            print("  [ok] Audit log rotated.")
        else:
            print("  [ok] Audit log below rotation threshold -- no action needed.")
        return 0

    if not audit_path.exists():
        print("No audit log yet. Start a session with tribunal hooks active.")
        return 0

    lines = audit_path.read_text().strip().split("\n")
    count = args.count if hasattr(args, "count") else 20

    recent = lines[-count:]
    print(f"\n  [list] Audit Log (last {len(recent)} of {len(lines)} entries)\n")

    for line in recent:
        try:
            entry = json.loads(line)
            ts = entry.get("ts", "?")
            hook = entry.get("hook", "?")
            tool = entry.get("tool", "?")
            allowed = entry.get("allowed", True)
            path = entry.get("path", "")
            cmd = entry.get("command", "")

            icon = "[ok]" if allowed else "[blocked]"
            detail = path or cmd[:50] or ""

            print(f"  {icon} {ts} {hook:15s} {tool:12s} {detail}")
        except json.JSONDecodeError:
            continue

    print()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show or validate Tribunal configuration."""
    from .config import format_config, resolve_config, validate_config

    sub = getattr(args, "config_command", None)

    if sub == "validate":
        config_path = Path.cwd() / ".tribunal" / "config.yaml"
        if not config_path.is_file():
            print("  No .tribunal/config.yaml to validate.")
            return 0
        data = yaml.safe_load(config_path.read_text()) or {}
        errors = validate_config(data)
        if errors:
            print(f"\n  [!]  Config validation found {len(errors)} issue(s):\n")
            for e in errors:
                print(f"    [x] {e}")
            print()
            return 1
        else:
            print("  [ok] Configuration is valid.")
            return 0

    config = resolve_config(str(Path.cwd()))
    print(format_config(config))
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    """Rule pack management."""
    from .packs import format_packs, install_pack

    sub = getattr(args, "pack_command", None)

    if sub == "list" or sub is None:
        print(format_packs())
        return 0
    elif sub == "install":
        name = args.name
        merge = not getattr(args, "replace", False)
        ok, messages = install_pack(name, str(Path.cwd()), merge=merge)
        for msg in messages:
            print(f"  {'[ok]' if ok else '[x]'} {msg}")
        return 0 if ok else 1
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    """Run quality checks on files and output results.

    This is the main CI/CD entrypoint. Runs all checkers (secrets, TDD,
    linting) and outputs results in SARIF, JSON, or text format.
    """
    from .scan import collect_files, run_checkers
    from .sarif import findings_to_sarif, sarif_to_json

    project_root = (
        Path(args.project) if hasattr(args, "project") and args.project else Path.cwd()
    )
    project_root = project_root.resolve()

    # Determine files to check
    paths = (
        [Path(p) for p in args.files] if hasattr(args, "files") and args.files else None
    )
    files = collect_files(project_root, paths=paths)

    if not files:
        print("  No files to check.", file=sys.stderr)
        return 0

    # Filter checkers if specified
    checker_names = (
        args.checkers.split(",")
        if hasattr(args, "checkers") and args.checkers
        else None
    )

    results = run_checkers(files, project_root, checkers=checker_names)

    # Count findings
    all_findings = [f for r in results for f in r.findings]
    errors = [f for f in all_findings if f.severity == "error"]
    warnings = [f for f in all_findings if f.severity == "warning"]

    # Output format
    fmt = getattr(args, "format", "text")

    if fmt == "sarif":
        sarif = findings_to_sarif(results, project_root)
        output = sarif_to_json(sarif)
        if hasattr(args, "output") and args.output:
            Path(args.output).write_text(output)
            print(f"  SARIF written to {args.output}", file=sys.stderr)
        else:
            print(output)
    elif fmt == "json":
        data = {
            "files_checked": len(files),
            "total_findings": len(all_findings),
            "errors": len(errors),
            "warnings": len(warnings),
            "findings": [
                {
                    "checker": f.checker,
                    "file": f.file,
                    "line": f.line,
                    "severity": f.severity,
                    "message": f.message,
                    "rule_id": f.rule_id,
                }
                for f in all_findings
            ],
        }
        output = json.dumps(data, indent=2)
        if hasattr(args, "output") and args.output:
            Path(args.output).write_text(output)
            print(f"  JSON written to {args.output}", file=sys.stderr)
        else:
            print(output)
    else:
        # Text format
        print(f"\n  [T]  Tribunal CI -- {len(files)} file(s) checked\n")
        if all_findings:
            for finding in all_findings:
                icon = (
                    "[blocked]"
                    if finding.severity == "error"
                    else "[!]"
                    if finding.severity == "warning"
                    else "(i)"
                )
                loc = f":{finding.line}" if finding.line > 0 else ""
                print(f"  {icon} {finding.file}{loc}")
                print(f"    {finding.message}")
                print(f"    [{finding.rule_id}]")
                print()
        if errors:
            print(f"  [x] {len(errors)} error(s), {len(warnings)} warning(s)")
        elif warnings:
            print(f"  [!] {len(warnings)} warning(s), 0 errors")
        else:
            print("  [ok] All checks passed.")
        print()

    # Exit code: 1 if errors, 0 otherwise
    return 1 if errors else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run health checks on Tribunal installation and project setup."""
    project_dir = Path.cwd()
    issues = 0
    warnings = 0

    print(f"\n  [T]  Tribunal Doctor v{__version__}\n")

    # 1. Check tribunal-gate on PATH
    if shutil.which("tribunal-gate"):
        print("  [ok] tribunal-gate is on PATH")
    else:
        print("  [x] tribunal-gate not found on PATH")
        issues += 1

    # 2. Check .tribunal/ directory
    tribunal_dir = project_dir / ".tribunal"
    if tribunal_dir.is_dir():
        print("  [ok] .tribunal/ directory exists")
    else:
        print("  [x] .tribunal/ directory missing -- run: tribunal init")
        issues += 1

    # 3. Check rules.yaml
    rules_path = tribunal_dir / "rules.yaml"
    if rules_path.is_file():
        try:
            data = yaml.safe_load(rules_path.read_text()) or {}
            rules = data.get("rules", {})
            print(f"  [ok] rules.yaml -- {len(rules)} rule(s)")

            for name, rdef in rules.items():
                if not isinstance(rdef, dict):
                    continue
                condition = rdef.get("condition", "")
                if condition == "type-check":
                    if not shutil.which("mypy"):
                        print(f"  [!] Rule '{name}' needs mypy but it's not installed")
                        warnings += 1
                if condition == "lint-check":
                    if not shutil.which("ruff") and not shutil.which("flake8"):
                        print(
                            f"  [!] Rule '{name}' needs ruff/flake8 but neither is installed"
                        )
                        warnings += 1
                run_cmd = rdef.get("run", "")
                if run_cmd:
                    cmd_name = run_cmd.split()[0] if run_cmd else ""
                    if cmd_name and not shutil.which(cmd_name):
                        print(
                            f"  [!] Rule '{name}' runs '{cmd_name}' but it's not installed"
                        )
                        warnings += 1
        except yaml.YAMLError as e:
            print(f"  [x] rules.yaml is invalid YAML: {e}")
            issues += 1
    else:
        print("  [x] rules.yaml missing -- run: tribunal init")
        issues += 1

    # 4. Check claudeconfig.json
    config_path = project_dir / ".claude" / "claudeconfig.json"
    if config_path.is_file():
        try:
            with open(config_path) as f:
                config = json.load(f)
            hooks = config.get("hooks", {})
            has_tribunal = "tribunal-gate" in json.dumps(hooks)
            if has_tribunal:
                hook_count = sum(len(v) for v in hooks.values())
                print(
                    f"  [ok] claudeconfig.json -- {hook_count} hook(s) with tribunal-gate"
                )
            else:
                print("  [!] claudeconfig.json exists but tribunal-gate not configured")
                warnings += 1
        except (json.JSONDecodeError, OSError):
            print("  [x] claudeconfig.json is invalid")
            issues += 1
    else:
        print("  [x] .claude/claudeconfig.json missing -- run: tribunal init")
        issues += 1

    # 5. Check .tribunal/config.yaml if present
    cfg_path = tribunal_dir / "config.yaml"
    if cfg_path.is_file():
        from .config import validate_config

        try:
            data = yaml.safe_load(cfg_path.read_text()) or {}
            errors = validate_config(data)
            if errors:
                print(f"  [!] config.yaml has {len(errors)} validation issue(s)")
                warnings += len(errors)
            else:
                print("  [ok] config.yaml is valid")
        except yaml.YAMLError:
            print("  [x] config.yaml is invalid YAML")
            issues += 1

    # 6. Check audit log
    audit_path = tribunal_dir / "audit.jsonl"
    if audit_path.is_file():
        size = audit_path.stat().st_size
        print(f"  [ok] audit.jsonl exists ({size:,} bytes)")
        if size > 10_000_000:
            print("  [!] Audit log exceeds 10MB -- consider: tribunal audit rotate")
            warnings += 1
    else:
        print("  ( ) No audit log yet (will be created on first session)")

    # Summary
    print()
    if issues == 0 and warnings == 0:
        print("  [ok] All checks passed.")
    else:
        if issues:
            print(f"  [x] {issues} issue(s) found")
        if warnings:
            print(f"  [!] {warnings} warning(s)")
    print()
    return 1 if issues > 0 else 0


# -- Main ----------------------------------------------------------------------


# -- v3 command handlers -------------------------------------------------------------


def _parse_window(spec: str) -> int:
    """Convert '24h' / '7d' / '30d' into milliseconds."""
    spec = spec.strip().lower()
    if spec.endswith("h"):
        return int(spec[:-1]) * 3600 * 1000
    if spec.endswith("d"):
        return int(spec[:-1]) * 86400 * 1000
    if spec.endswith("m"):
        return int(spec[:-1]) * 60 * 1000
    return int(spec) * 1000


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from .daemon import create_app
    except ImportError as e:
        print(f"[!]  daemon dependencies missing: {e}", file=sys.stderr)
        print("   Install with: pipx install 'tribunal[daemon]'", file=sys.stderr)
        return 2

    app = create_app(
        enable_policy=not args.no_policy,
        enable_injection_scan=not args.no_injection_scan,
    )
    print(f"[^] Tribunal daemon * http://{args.host}:{args.port}")
    if args.cloud:
        print("  Cloud mode: events will be batched to TRIBUNAL_INGEST_URL")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    try:
        from .events.store import EventStore
    except ImportError:
        print(
            "[!]  event store not available -- run 'tribunal init' first",
            file=sys.stderr,
        )
        return 2
    window_ms = _parse_window(args.last)
    import time as _time

    since = int(_time.time() * 1000) - window_ms
    store = EventStore()
    rows = store.cost_breakdown(since_ms=since, group_by=args.by)
    if not rows:
        print(f"No events with cost data in the last {args.last}.")
        return 0
    print(f"Cost breakdown by {args.by} * last {args.last}")
    print("-" * 60)
    total = 0.0
    for key, usd, events in rows:
        print(f"  {key:<32}  ${usd:>8.4f}   ({events} events)")
        total += usd
    print("-" * 60)
    print(f"  {'TOTAL':<32}  ${total:>8.4f}")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    from .policy.evaluator import load_shipped_packs, load_pack

    sub = getattr(args, "policy_command", None) or "list"

    if sub == "list":
        packs = load_shipped_packs()
        if not packs:
            print("No shipped packs found.")
            return 0
        state_dir = Path.home() / ".tribunal"
        ef = state_dir / "enabled-packs.txt"
        enabled = set(ef.read_text().splitlines()) if ef.exists() else set()
        for p in packs:
            mark = "[ok]" if p.name in enabled else " "
            print(f"  [{mark}] {p.name:<24}  v{p.version}  ({len(p.rules)} rules)")
        return 0

    if sub == "enable" or sub == "disable":
        state_dir = Path.home() / ".tribunal"
        state_dir.mkdir(parents=True, exist_ok=True)
        f = state_dir / "enabled-packs.txt"
        enabled = set(f.read_text().splitlines()) if f.exists() else set()
        if sub == "enable":
            enabled.add(args.name)
            print(f"[ok] enabled pack: {args.name}")
        else:
            enabled.discard(args.name)
            print(f"[ok] disabled pack: {args.name}")
        f.write_text("\n".join(sorted(enabled)) + "\n")
        return 0

    if sub == "lint":
        try:
            pack = load_pack(Path(args.path))
        except Exception as e:
            print(f"[x] invalid: {e}", file=sys.stderr)
            return 1
        print(f"[ok] valid pack: {pack.name} v{pack.version} ({len(pack.rules)} rules)")
        return 0

    if sub == "reload":
        # Best-effort: post to running daemon.
        try:
            import urllib.request

            req = urllib.request.Request(
                "http://127.0.0.1:8088/v1/policy/reload", method="POST"
            )
            urllib.request.urlopen(req, timeout=2).read()
            print("[ok] daemon reloaded packs")
        except Exception as e:
            print(f"[!]  could not reach daemon: {e}", file=sys.stderr)
            return 1
        return 0

    print("Usage: tribunal policy {list,enable,disable,lint,reload}")
    return 2


def cmd_scan(args: argparse.Namespace) -> int:
    from .policy.injection import scan as inj_scan

    if args.path:
        text = Path(args.path).read_text(errors="replace")
    else:
        text = sys.stdin.read()
    finding = inj_scan(text)
    if args.json:
        print(json.dumps(finding.__dict__, indent=2, default=str))
        return 0 if not finding.suspected else 1
    if not finding.suspected:
        print("[ok] no injection patterns detected")
        return 0
    print(f"  [{finding.severity:<6}] {finding.rule_id:<28} {finding.message}")
    if finding.snippet:
        print(f"     snippet: {finding.snippet}")
    return 1


def cmd_adapter(args: argparse.Namespace) -> int:
    agent = args.agent
    home = Path.home()
    print(
        f"{'Uninstalling' if args.uninstall else 'Installing'} adapter for {agent}..."
    )

    if agent == "claude-code":
        target = home / ".claude" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.uninstall:
            print(f"  Remove the Tribunal hook from {target} manually.")
            return 0
        cfg = json.loads(target.read_text()) if target.exists() else {}
        cfg.setdefault("hooks", {})
        cfg["hooks"]["PreToolUse"] = [
            {
                "if": {"matcher": ".*"},
                "run": [{"command": "tribunal-adapter claude-code pre"}],
            }
        ]
        cfg["hooks"]["PostToolUse"] = [
            {
                "if": {"matcher": ".*"},
                "run": [{"command": "tribunal-adapter claude-code post"}],
            }
        ]
        target.write_text(json.dumps(cfg, indent=2))
        print(f"  wrote {target}")
        return 0

    if agent == "cursor":
        target = home / ".cursor" / "extensions" / "tribunal" / "hook.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"command": "tribunal-adapter cursor"}, indent=2))
        print(f"  wrote {target}")
        return 0

    if agent == "copilot-cli":
        target = home / ".copilot" / "hooks" / "tribunal.sh"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            '#!/usr/bin/env bash\nexec tribunal-adapter copilot-cli "$@"\n'
        )
        target.chmod(0o755)
        print(f"  wrote {target}")
        return 0

    if agent == "codex-cli":
        target = home / ".codex" / "hooks" / "tribunal.sh"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/usr/bin/env bash\nexec tribunal-adapter codex-cli "$@"\n')
        target.chmod(0o755)
        print(f"  wrote {target}")
        return 0

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tribunal",
        description="Quality gates for AI-generated code.",
    )
    parser.add_argument(
        "--version", action="version", version=f"tribunal {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    # init
    init_p = sub.add_parser("init", help="Set up Tribunal in the current project")
    init_p.add_argument(
        "--force", action="store_true", help="Overwrite existing config"
    )

    # status
    sub.add_parser("status", help="Show current Tribunal status")

    # rules
    sub.add_parser("rules", help="List active rules")

    # audit
    audit_p = sub.add_parser("audit", help="Show recent audit log")
    audit_p.add_argument(
        "-n", "--count", type=int, default=20, help="Number of entries"
    )
    audit_sub = audit_p.add_subparsers(dest="audit_command")
    audit_sub.add_parser("rotate", help="Rotate the audit log file")

    # config
    config_p = sub.add_parser("config", help="Show resolved configuration")
    config_sub = config_p.add_subparsers(dest="config_command")
    config_sub.add_parser("show", help="Show resolved config")
    config_sub.add_parser("validate", help="Validate .tribunal/config.yaml")

    # pack (rule packs)
    pack_p = sub.add_parser("pack", help="Rule pack management")
    pack_sub = pack_p.add_subparsers(dest="pack_command")
    pack_sub.add_parser("list", help="List available rule packs")
    pack_inst_p = pack_sub.add_parser("install", help="Install a rule pack")
    pack_inst_p.add_argument(
        "name", help="Pack name: soc2, startup, enterprise, security"
    )
    pack_inst_p.add_argument(
        "--replace", action="store_true", help="Replace rules instead of merging"
    )

    # ci
    ci_p = sub.add_parser("ci", help="Run quality checks (CI/CD entrypoint)")
    ci_p.add_argument(
        "files", nargs="*", help="Files or directories to check (default: project root)"
    )
    ci_p.add_argument(
        "-f",
        "--format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format",
    )
    ci_p.add_argument("-o", "--output", help="Write output to file instead of stdout")
    ci_p.add_argument(
        "--checkers",
        help="Comma-separated list of checkers: secrets,tdd,python,typescript,go",
    )
    ci_p.add_argument("--project", help="Project root directory (default: cwd)")

    # doctor
    sub.add_parser("doctor", help="Run health checks on Tribunal setup")

    # -- v3 commands ------------------------------------------------------

    # serve -- run the local FastAPI daemon
    serve_p = sub.add_parser("serve", help="Run the Tribunal daemon (localhost:8088)")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8088)
    serve_p.add_argument(
        "--cloud",
        action="store_true",
        help="Ship events to TRIBUNAL_INGEST_URL using TRIBUNAL_INGEST_TOKEN",
    )
    serve_p.add_argument("--no-policy", action="store_true")
    serve_p.add_argument("--no-injection-scan", action="store_true")

    # cost -- show spend breakdown from the local event store
    cost_p = sub.add_parser("cost", help="Show cost breakdown from the local event log")
    cost_p.add_argument(
        "--last", default="7d", help="Time window, e.g. 24h, 7d, 30d (default: 7d)"
    )
    cost_p.add_argument(
        "--by", choices=["agent", "user", "model", "session"], default="agent"
    )

    # policy -- pack management (separate from the v1 'pack' command)
    policy_p = sub.add_parser("policy", help="Manage policy packs (v3)")
    policy_sub = policy_p.add_subparsers(dest="policy_command")
    policy_sub.add_parser("list", help="List shipped + custom policy packs")
    pe = policy_sub.add_parser("enable", help="Enable a shipped pack")
    pe.add_argument("name")
    pd = policy_sub.add_parser("disable", help="Disable a pack")
    pd.add_argument("name")
    pl = policy_sub.add_parser("lint", help="Validate a YAML policy file")
    pl.add_argument("path")
    policy_sub.add_parser("reload", help="Tell the running daemon to reload packs")

    # scan -- ad hoc prompt-injection scan on a file or stdin
    scan_p = sub.add_parser(
        "scan", help="Run the prompt-injection scanner on a file or stdin"
    )
    scan_p.add_argument("path", nargs="?", help="File to scan (default: stdin)")
    scan_p.add_argument("--json", action="store_true")

    # adapter -- install agent hooks
    adapter_p = sub.add_parser("adapter", help="Install an agent adapter hook")
    adapter_p.add_argument(
        "agent",
        choices=["claude-code", "cursor", "copilot-cli", "codex-cli"],
    )
    adapter_p.add_argument("--uninstall", action="store_true")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "rules": cmd_rules,
        "audit": cmd_audit,
        "config": cmd_config,
        "pack": cmd_pack,
        "ci": cmd_ci,
        "doctor": cmd_doctor,
        "serve": cmd_serve,
        "cost": cmd_cost,
        "policy": cmd_policy,
        "scan": cmd_scan,
        "adapter": cmd_adapter,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(0)
