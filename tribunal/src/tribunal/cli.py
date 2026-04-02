"""Tribunal CLI — quality gates for AI-generated code.

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
import os
import shutil
import sys
from pathlib import Path

import yaml

from . import __version__


# ── Config Templates ──────────────────────────────────────────────────────────

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


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> int:
    """Set up Tribunal hooks in the current project."""
    project_dir = Path.cwd()

    # 1. Create .tribunal/ directory and rules.yaml
    tribunal_dir = project_dir / ".tribunal"
    tribunal_dir.mkdir(exist_ok=True)

    rules_path = tribunal_dir / "rules.yaml"
    if rules_path.exists() and not args.force:
        print(f"  ✓ Rules already exist at {rules_path.relative_to(project_dir)}")
    else:
        with open(rules_path, "w") as f:
            yaml.dump(_DEFAULT_RULES, f, default_flow_style=False, sort_keys=False)
        print(f"  ✓ Created {rules_path.relative_to(project_dir)}")

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
                "tribunal-gate" in str(h.get("run", []))
                for h in existing_hooks
            )
            if not has_tribunal:
                existing["hooks"][event] = existing_hooks + hooks
        with open(config_path, "w") as f:
            json.dump(existing, f, indent=2)
        print(f"  ✓ Updated {config_path.relative_to(project_dir)} (merged hooks)")
    else:
        with open(config_path, "w") as f:
            json.dump(_CLAUDE_CONFIG, f, indent=2)
        print(f"  ✓ Created {config_path.relative_to(project_dir)}")

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
            print("  ✓ Added tribunal paths to .gitignore")
    else:
        with open(gitignore, "w") as f:
            f.write("# tribunal audit log (local only)\n")
            f.write(ignore_line + "\n")
            f.write(ignore_state + "\n")
        print("  ✓ Created .gitignore with tribunal exclusions")

    # 5. Check if tribunal-gate is on PATH
    if not shutil.which("tribunal-gate"):
        print()
        print("  ⚠  tribunal-gate not found on PATH.")
        print("     Make sure tribunal is installed: pip install tribunal")
        print()

    print()
    print("  ⚖  Tribunal initialized.")
    print()
    print("  Your AI coding sessions now enforce:")
    print("    • TDD — tests required before production code")
    print("    • Secret scanning — no hardcoded credentials")
    print("    • Audit trail — all tool calls logged")
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

    print(f"\n  ⚖  Tribunal v{__version__}\n")

    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        hooks = config.get("hooks", {})
        hook_count = sum(len(v) for v in hooks.values())
        has_tribunal = "tribunal-gate" in json.dumps(hooks)
        if has_tribunal:
            print(f"  ✓ Hooks active — {hook_count} hook(s) in .claude/claudeconfig.json")
        else:
            print("  ⚠ Hooks exist but tribunal-gate not configured")
    else:
        print("  ✗ No .claude/claudeconfig.json — run: tribunal init")

    if rules_path.exists():
        with open(rules_path) as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", {})
        enabled = sum(1 for r in rules.values() if isinstance(r, dict) and r.get("enabled", True))
        print(f"  ✓ {enabled} rule(s) active in .tribunal/rules.yaml")
        for name, rdef in rules.items():
            if isinstance(rdef, dict) and rdef.get("enabled", True):
                action = rdef.get("action", "block")
                icon = "⛔" if action == "block" else "⚠️" if action == "warn" else "📝"
                print(f"    {icon} {name}: {rdef.get('message', '')[:60]}")
    else:
        print("  ✗ No .tribunal/rules.yaml — run: tribunal init")

    if audit_path.exists():
        lines = audit_path.read_text().strip().split("\n")
        total = len(lines)
        blocked = sum(1 for line in lines if '"allowed":false' in line)
        print(f"  📋 {total} audit entries ({blocked} blocked)")
    else:
        print("  📋 No audit log yet")

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
    print(f"\n  ⚖  Tribunal Rules ({len(rules)} total)\n")

    for name, rdef in rules.items():
        if not isinstance(rdef, dict):
            continue
        enabled = rdef.get("enabled", True)
        action = rdef.get("action", "block")
        trigger = rdef.get("trigger", "?")
        match = rdef.get("match", {})
        condition = rdef.get("condition", "")
        message = rdef.get("message", "")

        status = "✓" if enabled else "✗"
        action_icon = "⛔" if action == "block" else "⚠️" if action == "warn" else "📝"

        print(f"  {status} {name}")
        print(f"    {action_icon} {action} on {trigger}")
        if match:
            print(f"    match: {json.dumps(match)}")
        if condition:
            print(f"    condition: {condition}")
        if message:
            print(f"    → {message[:80]}")
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
            print("  ✓ Audit log rotated.")
        else:
            print("  ✓ Audit log below rotation threshold — no action needed.")
        return 0

    if not audit_path.exists():
        print("No audit log yet. Start a session with tribunal hooks active.")
        return 0

    lines = audit_path.read_text().strip().split("\n")
    count = args.count if hasattr(args, "count") else 20

    recent = lines[-count:]
    print(f"\n  📋 Audit Log (last {len(recent)} of {len(lines)} entries)\n")

    for line in recent:
        try:
            entry = json.loads(line)
            ts = entry.get("ts", "?")
            hook = entry.get("hook", "?")
            tool = entry.get("tool", "?")
            allowed = entry.get("allowed", True)
            path = entry.get("path", "")
            cmd = entry.get("command", "")

            icon = "✓" if allowed else "⛔"
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
            print(f"\n  ⚠  Config validation found {len(errors)} issue(s):\n")
            for e in errors:
                print(f"    ✗ {e}")
            print()
            return 1
        else:
            print("  ✓ Configuration is valid.")
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
            print(f"  {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run health checks on Tribunal installation and project setup."""
    project_dir = Path.cwd()
    issues = 0
    warnings = 0

    print(f"\n  ⚖  Tribunal Doctor v{__version__}\n")

    # 1. Check tribunal-gate on PATH
    if shutil.which("tribunal-gate"):
        print("  ✓ tribunal-gate is on PATH")
    else:
        print("  ✗ tribunal-gate not found on PATH")
        issues += 1

    # 2. Check .tribunal/ directory
    tribunal_dir = project_dir / ".tribunal"
    if tribunal_dir.is_dir():
        print("  ✓ .tribunal/ directory exists")
    else:
        print("  ✗ .tribunal/ directory missing — run: tribunal init")
        issues += 1

    # 3. Check rules.yaml
    rules_path = tribunal_dir / "rules.yaml"
    if rules_path.is_file():
        try:
            data = yaml.safe_load(rules_path.read_text()) or {}
            rules = data.get("rules", {})
            print(f"  ✓ rules.yaml — {len(rules)} rule(s)")

            for name, rdef in rules.items():
                if not isinstance(rdef, dict):
                    continue
                condition = rdef.get("condition", "")
                if condition == "type-check":
                    if not shutil.which("mypy"):
                        print(f"  ⚠ Rule '{name}' needs mypy but it's not installed")
                        warnings += 1
                if condition == "lint-check":
                    if not shutil.which("ruff") and not shutil.which("flake8"):
                        print(f"  ⚠ Rule '{name}' needs ruff/flake8 but neither is installed")
                        warnings += 1
                run_cmd = rdef.get("run", "")
                if run_cmd:
                    cmd_name = run_cmd.split()[0] if run_cmd else ""
                    if cmd_name and not shutil.which(cmd_name):
                        print(f"  ⚠ Rule '{name}' runs '{cmd_name}' but it's not installed")
                        warnings += 1
        except yaml.YAMLError as e:
            print(f"  ✗ rules.yaml is invalid YAML: {e}")
            issues += 1
    else:
        print("  ✗ rules.yaml missing — run: tribunal init")
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
                print(f"  ✓ claudeconfig.json — {hook_count} hook(s) with tribunal-gate")
            else:
                print("  ⚠ claudeconfig.json exists but tribunal-gate not configured")
                warnings += 1
        except (json.JSONDecodeError, OSError):
            print("  ✗ claudeconfig.json is invalid")
            issues += 1
    else:
        print("  ✗ .claude/claudeconfig.json missing — run: tribunal init")
        issues += 1

    # 5. Check .tribunal/config.yaml if present
    cfg_path = tribunal_dir / "config.yaml"
    if cfg_path.is_file():
        from .config import validate_config
        try:
            data = yaml.safe_load(cfg_path.read_text()) or {}
            errors = validate_config(data)
            if errors:
                print(f"  ⚠ config.yaml has {len(errors)} validation issue(s)")
                warnings += len(errors)
            else:
                print("  ✓ config.yaml is valid")
        except yaml.YAMLError:
            print("  ✗ config.yaml is invalid YAML")
            issues += 1

    # 6. Check audit log
    audit_path = tribunal_dir / "audit.jsonl"
    if audit_path.is_file():
        size = audit_path.stat().st_size
        print(f"  ✓ audit.jsonl exists ({size:,} bytes)")
        if size > 10_000_000:
            print("  ⚠ Audit log exceeds 10MB — consider: tribunal audit rotate")
            warnings += 1
    else:
        print("  ○ No audit log yet (will be created on first session)")

    # Summary
    print()
    if issues == 0 and warnings == 0:
        print("  ✓ All checks passed.")
    else:
        if issues:
            print(f"  ✗ {issues} issue(s) found")
        if warnings:
            print(f"  ⚠ {warnings} warning(s)")
    print()
    return 1 if issues > 0 else 0


# ── Main ──────────────────────────────────────────────────────────────────────


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
    init_p.add_argument("--force", action="store_true", help="Overwrite existing config")

    # status
    sub.add_parser("status", help="Show current Tribunal status")

    # rules
    sub.add_parser("rules", help="List active rules")

    # audit
    audit_p = sub.add_parser("audit", help="Show recent audit log")
    audit_p.add_argument("-n", "--count", type=int, default=20, help="Number of entries")
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
    pack_inst_p.add_argument("name", help="Pack name: soc2, startup, enterprise, security")
    pack_inst_p.add_argument("--replace", action="store_true", help="Replace rules instead of merging")

    # doctor
    sub.add_parser("doctor", help="Run health checks on Tribunal setup")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "rules": cmd_rules,
        "audit": cmd_audit,
        "config": cmd_config,
        "pack": cmd_pack,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(0)
