"""Tribunal CLI — main entry point.

Commands:
  tribunal init         Set up hooks in the current project
  tribunal status       Show current rules and audit summary
  tribunal rules        List active rules
  tribunal audit        Show recent audit log entries
  tribunal cost         Cost tracking and budget management
  tribunal skills       Manage Tribunal skills
  tribunal permissions  Manage permission policies
  tribunal review       Run review agents on changed files
  tribunal report       Generate CI/CD-friendly report
  tribunal config       Show resolved configuration
  tribunal plugin       Plugin manifest management
  tribunal mcp-serve    Start MCP server
  tribunal sync         Import/export rule bundles
  tribunal managed      Show managed policy status
  tribunal model        Model routing configuration
  tribunal marketplace  Rule marketplace management
  tribunal memory       Memory injection management
  tribunal analytics    Cost analytics and trends
  tribunal bundle       Air-gapped bundle management
  tribunal dashboard    Audit dashboard report
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
        # Merge hooks into existing config
        existing.setdefault("hooks", {})
        for event, hooks in _CLAUDE_CONFIG["hooks"].items():
            existing_hooks = existing["hooks"].get(event, [])
            # Check if tribunal-gate is already configured
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
            print(f"  ✓ Added tribunal paths to .gitignore")
    else:
        with open(gitignore, "w") as f:
            f.write("# tribunal audit log (local only)\n")
            f.write(ignore_line + "\n")
            f.write(ignore_state + "\n")
        print(f"  ✓ Created .gitignore with tribunal exclusions")

    # 5. Check if tribunal-gate is on PATH
    if not shutil.which("tribunal-gate"):
        print()
        print("  ⚠  tribunal-gate not found on PATH.")
        print("     Make sure tribunal is installed: pip install tribunal")
        print()

    print()
    print("  ⚖  Tribunal initialized.")
    print()
    print("  Your Claude Code sessions now enforce:")
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

    # Check hooks
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        hooks = config.get("hooks", {})
        hook_count = sum(len(v) for v in hooks.values())
        has_tribunal = "tribunal-gate" in json.dumps(hooks)
        if has_tribunal:
            print(f"  ✓ Hooks active — {hook_count} hook(s) in .claude/claudeconfig.json")
        else:
            print(f"  ⚠ Hooks exist but tribunal-gate not configured")
    else:
        print("  ✗ No .claude/claudeconfig.json — run: tribunal init")

    # Check rules
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

    # Audit summary
    if audit_path.exists():
        lines = audit_path.read_text().strip().split("\n")
        total = len(lines)
        blocked = sum(1 for l in lines if '"allowed":false' in l)
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

    if not audit_path.exists():
        print("No audit log yet. Start a Claude Code session with tribunal hooks active.")
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


# ── Cost Commands ─────────────────────────────────────────────────────────────


def cmd_cost(args: argparse.Namespace) -> int:
    """Cost management commands."""
    from .cost import format_cost_report, set_budget

    sub = getattr(args, "cost_command", None)

    if sub == "report":
        print(format_cost_report(str(Path.cwd())))
        return 0
    elif sub == "budget":
        amount = args.amount
        if amount <= 0:
            print("Budget amount must be positive.")
            return 1
        daily = getattr(args, "daily", False)
        if daily:
            set_budget(str(Path.cwd()), daily_usd=amount)
            print(f"  ✓ Daily budget set to ${amount:.2f}")
        else:
            set_budget(str(Path.cwd()), session_usd=amount)
            print(f"  ✓ Session budget set to ${amount:.2f}")
        return 0
    elif sub == "reset":
        from .cost import save_state, load_state
        state = load_state(str(Path.cwd()))
        state.pop("session_cost_usd", None)
        state.pop("input_tokens", None)
        state.pop("output_tokens", None)
        save_state(str(Path.cwd()), state)
        print("  ✓ Session cost counters reset.")
        return 0
    else:
        # Default: show report
        print(format_cost_report(str(Path.cwd())))
        return 0


# ── Skills Commands ───────────────────────────────────────────────────────────


def cmd_skills(args: argparse.Namespace) -> int:
    """Skills management commands."""
    from .skills import (
        create_skill_scaffold,
        format_skill_list,
        install_skill,
        list_all_skills,
        load_bundled_skills,
    )

    sub = getattr(args, "skills_command", None)

    if sub == "list":
        skills = list_all_skills(str(Path.cwd()))
        print(format_skill_list(skills))
        return 0
    elif sub == "install":
        name = args.name
        # Check if it's a bundled skill
        bundled = {s.name: s for s in load_bundled_skills()}
        if name in bundled:
            dest = install_skill(bundled[name], str(Path.cwd()))
            print(f"  ✓ Installed bundled skill '{name}' to {dest}")
        else:
            print(f"  Unknown skill '{name}'. Available bundled skills:")
            for s in bundled.values():
                print(f"    📦 {s.name}: {s.description}")
            return 1
        return 0
    elif sub == "create":
        name = args.name
        dest = create_skill_scaffold(name, str(Path.cwd()))
        print(f"  ✓ Created skill scaffold at {dest}")
        print(f"     Edit this file to define your custom skill.")
        return 0
    else:
        # Default: list
        skills = list_all_skills(str(Path.cwd()))
        print(format_skill_list(skills))
        return 0


# ── Permissions Commands ──────────────────────────────────────────────────────


def cmd_permissions(args: argparse.Namespace) -> int:
    """Permission policy commands."""
    from .permissions import apply_policy, format_policy, get_preset, list_presets

    sub = getattr(args, "perm_command", None)

    if sub == "apply":
        preset_name = args.preset
        policy = get_preset(preset_name)
        if not policy:
            print(f"  Unknown preset '{preset_name}'. Available: {', '.join(list_presets())}")
            return 1
        apply_policy(str(Path.cwd()), policy)
        print(f"  ✓ Applied '{preset_name}' permission policy to .claude/claudeconfig.json")
        print()
        print(format_policy(policy))
        return 0
    elif sub == "show":
        presets = list_presets()
        print(f"\n  ⚖  Permission Presets ({len(presets)} available)\n")
        for name in presets:
            policy = get_preset(name)
            if policy:
                deny_count = len(policy.deny)
                allow_count = len(policy.allow)
                print(f"  📋 {name}: {deny_count} deny, {allow_count} allow rules")
        print(f"\n  Apply with: tribunal permissions apply <preset>\n")
        return 0
    else:
        # Default: show presets
        return cmd_permissions(argparse.Namespace(perm_command="show"))


# ── Review Commands ───────────────────────────────────────────────────────────


def cmd_review(args: argparse.Namespace) -> int:
    """Run review agents on changed files."""
    from .review import run_review

    agents = args.agents.split(",") if hasattr(args, "agents") and args.agents else None
    files = args.files if hasattr(args, "files") and args.files else None

    report = run_review(cwd=str(Path.cwd()), agents=agents, files=files)
    print(report.format())

    if hasattr(args, "json_output") and args.json_output:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.passed else 1


# ── Report Command ────────────────────────────────────────────────────────────


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a CI/CD-friendly report (JSON or text)."""
    from .review import run_review
    from .cost import get_cost_snapshot, get_budget

    cwd = str(Path.cwd())
    report = run_review(cwd=cwd)
    snapshot = get_cost_snapshot(cwd)
    budget = get_budget(cwd)

    output_format = getattr(args, "format", "text")

    if output_format == "json":
        result = {
            "review": report.to_dict(),
            "cost": {
                "session_usd": snapshot.session_cost_usd,
                "daily_usd": snapshot.daily_cost_usd,
                "budget_session_usd": budget.session_usd,
                "budget_daily_usd": budget.daily_usd,
            },
            "passed": report.passed,
        }
        print(json.dumps(result, indent=2))
    else:
        print(report.format())
        if snapshot.session_cost_usd > 0:
            print(f"  💰 Session cost: ${snapshot.session_cost_usd:.4f}")
            if budget.session_usd > 0:
                pct = snapshot.session_cost_usd / budget.session_usd * 100
                print(f"     Budget: ${budget.session_usd:.2f} ({pct:.0f}% used)")
        print()

    return 0 if report.passed else 1


# ── Config Command ────────────────────────────────────────────────────────────


def cmd_config(args: argparse.Namespace) -> int:
    """Show resolved Tribunal configuration."""
    from .config import format_config, resolve_config

    config = resolve_config(str(Path.cwd()))
    print(format_config(config))
    return 0


# ── Plugin Command ────────────────────────────────────────────────────────────


def cmd_plugin(args: argparse.Namespace) -> int:
    """Plugin manifest management."""
    from .plugin import generate_manifest, install_plugin_manifest

    sub = getattr(args, "plugin_command", None)

    if sub == "install":
        dest = install_plugin_manifest(str(Path.cwd()))
        print(f"  ✓ Plugin manifest written to {dest}")
        return 0
    elif sub == "show":
        print(generate_manifest())
        return 0
    else:
        print(generate_manifest())
        return 0


# ── Sync Command ──────────────────────────────────────────────────────────────


def cmd_sync(args: argparse.Namespace) -> int:
    """Import or export rule bundles."""
    from .sync import export_to_file, import_from_file

    sub = getattr(args, "sync_command", None)

    if sub == "export":
        dest = getattr(args, "output", None) or ".tribunal/bundle.yaml"
        name = getattr(args, "name", "") or ""
        path = export_to_file(dest, str(Path.cwd()), name=name)
        print(f"  ✓ Rules exported to {path}")
        return 0
    elif sub == "import":
        source = getattr(args, "file", None)
        if not source:
            print("  ✗ Specify a file to import.")
            return 1
        merge = not getattr(args, "replace", False)
        ok, messages = import_from_file(source, str(Path.cwd()), merge=merge)
        for msg in messages:
            print(f"  {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1
    else:
        print("  Usage: tribunal sync export|import")
        return 0


# ── Managed Command ───────────────────────────────────────────────────────────


def cmd_managed(args: argparse.Namespace) -> int:
    """Show managed policy status."""
    from .managed import format_managed_status, load_managed_policy

    policy = load_managed_policy()
    print(format_managed_status(policy))
    return 0


# ── Model Command ─────────────────────────────────────────────────────────────


def cmd_model(args: argparse.Namespace) -> int:
    """Model routing configuration."""
    from .routing import format_model_config, load_model_config

    sub = getattr(args, "model_command", None)

    if sub == "resolve":
        tool = getattr(args, "tool", "") or ""
        config = load_model_config(str(Path.cwd()))
        model = config.resolve_model(tool_name=tool)
        print(f"  Model: {model}")
        return 0
    else:
        config = load_model_config(str(Path.cwd()))
        print(format_model_config(config))
        return 0


# ── Marketplace Command ──────────────────────────────────────────────────────


def cmd_marketplace(args: argparse.Namespace) -> int:
    """Rule marketplace management."""
    from .marketplace import (
        format_marketplace,
        install_from_marketplace,
        list_marketplace,
        register_bundle,
        unregister_bundle,
    )

    sub = getattr(args, "market_command", None)

    if sub == "list":
        entries = list_marketplace()
        print(format_marketplace(entries))
        return 0
    elif sub == "register":
        bundle_file = getattr(args, "file", None)
        if not bundle_file:
            print("  ✗ Specify a bundle file to register.")
            return 1
        ok, msg = register_bundle(bundle_file)
        print(f"  {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1
    elif sub == "install":
        name = getattr(args, "name", None)
        if not name:
            print("  ✗ Specify a bundle name to install.")
            return 1
        ok, messages = install_from_marketplace(name, str(Path.cwd()))
        for msg in messages:
            print(f"  {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1
    elif sub == "remove":
        name = getattr(args, "name", None)
        if not name:
            print("  ✗ Specify a bundle name to remove.")
            return 1
        ok, msg = unregister_bundle(name)
        print(f"  {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1
    else:
        entries = list_marketplace()
        print(format_marketplace(entries))
        return 0


# ── Memory Command ────────────────────────────────────────────────────────────


def cmd_memory(args: argparse.Namespace) -> int:
    """Memory injection management."""
    from .memory import (
        clear_tribunal_memories,
        format_memory_status,
        inject_rules_as_memory,
        inject_session_summary,
    )

    sub = getattr(args, "mem_command", None)

    if sub == "inject":
        cwd = str(Path.cwd())
        entries = inject_rules_as_memory(cwd)
        print(f"  ✓ Injected {len(entries)} rules as memory entries")
        return 0
    elif sub == "summary":
        text = getattr(args, "text", "") or ""
        path = inject_session_summary(str(Path.cwd()), text or "Session completed")
        print(f"  ✓ Session summary written to {path.name}")
        return 0
    elif sub == "list":
        print(format_memory_status(str(Path.cwd())))
        return 0
    elif sub == "clear":
        removed = clear_tribunal_memories(str(Path.cwd()))
        print(f"  ✓ Removed {removed} tribunal memory entries")
        return 0
    else:
        print(format_memory_status(str(Path.cwd())))
        return 0


# ── Analytics Command ─────────────────────────────────────────────────────────


def cmd_analytics(args: argparse.Namespace) -> int:
    """Cost analytics and trends."""
    from .analytics import analyze_costs, format_analytics

    analytics = analyze_costs(str(Path.cwd()))

    if getattr(args, "json_output", False):
        print(json.dumps(analytics.to_dict(), indent=2))
    else:
        print(format_analytics(analytics))

    return 0


# ── Bundle Command ────────────────────────────────────────────────────────────


def cmd_bundle(args: argparse.Namespace) -> int:
    """Air-gapped bundle management."""
    from .airgap import export_bundle, import_bundle, validate_bundle

    sub = getattr(args, "bundle_command", None)

    if sub == "export":
        output = getattr(args, "output", None)
        path = export_bundle(str(Path.cwd()), output=output)
        print(f"  ✓ Bundle exported to {path}")
        return 0
    elif sub == "import":
        source = getattr(args, "file", None)
        if not source:
            print("  ✗ Specify a bundle file to import.")
            return 1
        ok, errors = validate_bundle(source)
        if not ok:
            for e in errors:
                print(f"  ✗ {e}")
            return 1
        counts = import_bundle(source, str(Path.cwd()))
        for kind, n in counts.items():
            if n > 0:
                print(f"  ✓ Imported {n} {kind}")
        return 0
    elif sub == "validate":
        source = getattr(args, "file", None)
        if not source:
            print("  ✗ Specify a bundle file to validate.")
            return 1
        ok, errors = validate_bundle(source)
        if ok:
            print("  ✓ Bundle is valid")
        else:
            for e in errors:
                print(f"  ✗ {e}")
        return 0 if ok else 1
    else:
        print("  Usage: tribunal bundle export|import|validate")
        return 0


# ── Dashboard Command ─────────────────────────────────────────────────────────


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Audit dashboard report."""
    from .dashboard import export_html_report, format_stats, compute_stats, load_audit_events

    sub = getattr(args, "dash_command", None)

    if sub == "html":
        output = getattr(args, "output", None)
        path = export_html_report(str(Path.cwd()), output=output)
        print(f"  ✓ Dashboard exported to {path}")
        return 0
    else:
        events = load_audit_events(str(Path.cwd()))
        stats = compute_stats(events)
        print(format_stats(stats))
        return 0


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tribunal",
        description="Enterprise-grade discipline for Claude Code.",
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

    # cost
    cost_p = sub.add_parser("cost", help="Cost tracking and budget management")
    cost_sub = cost_p.add_subparsers(dest="cost_command")
    cost_sub.add_parser("report", help="Show cost report")
    budget_p = cost_sub.add_parser("budget", help="Set cost budget")
    budget_p.add_argument("amount", type=float, help="Budget amount in USD")
    budget_p.add_argument("--daily", action="store_true", help="Set as daily budget instead of per-session")
    cost_sub.add_parser("reset", help="Reset session cost counters")

    # skills
    skills_p = sub.add_parser("skills", help="Manage Tribunal skills")
    skills_sub = skills_p.add_subparsers(dest="skills_command")
    skills_sub.add_parser("list", help="List available skills")
    install_p = skills_sub.add_parser("install", help="Install a bundled skill")
    install_p.add_argument("name", help="Skill name to install")
    create_p = skills_sub.add_parser("create", help="Create a new custom skill")
    create_p.add_argument("name", help="Name for the new skill")

    # permissions
    perm_p = sub.add_parser("permissions", help="Manage permission policies")
    perm_sub = perm_p.add_subparsers(dest="perm_command")
    perm_sub.add_parser("show", help="Show available permission presets")
    apply_p = perm_sub.add_parser("apply", help="Apply a permission preset")
    apply_p.add_argument("preset", help="Preset name: strict, standard, or minimal")

    # review
    review_p = sub.add_parser("review", help="Run review agents on changed files")
    review_p.add_argument("--agents", help="Comma-separated list of agents to run")
    review_p.add_argument("--json", dest="json_output", action="store_true", help="Output JSON")
    review_p.add_argument("files", nargs="*", default=None, help="Files to review")

    # report (CI/CD)
    report_p = sub.add_parser("report", help="Generate CI/CD report")
    report_p.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # config
    sub.add_parser("config", help="Show resolved configuration")

    # plugin
    plugin_p = sub.add_parser("plugin", help="Plugin manifest management")
    plugin_sub = plugin_p.add_subparsers(dest="plugin_command")
    plugin_sub.add_parser("show", help="Show plugin manifest")
    plugin_sub.add_parser("install", help="Write plugin manifest to .tribunal/")

    # mcp-serve
    sub.add_parser("mcp-serve", help="Start MCP server (stdin/stdout)")

    # sync (import/export)
    sync_p = sub.add_parser("sync", help="Import/export rule bundles")
    sync_sub = sync_p.add_subparsers(dest="sync_command")
    export_p = sync_sub.add_parser("export", help="Export rules to a YAML bundle")
    export_p.add_argument("--output", "-o", default=".tribunal/bundle.yaml", help="Output file")
    export_p.add_argument("--name", default="", help="Bundle name")
    import_p = sync_sub.add_parser("import", help="Import rules from a YAML bundle")
    import_p.add_argument("file", help="YAML bundle file to import")
    import_p.add_argument("--replace", action="store_true", help="Replace rules instead of merging")

    # managed
    sub.add_parser("managed", help="Show managed policy status")

    # model routing
    model_p = sub.add_parser("model", help="Model routing configuration")
    model_sub = model_p.add_subparsers(dest="model_command")
    model_sub.add_parser("show", help="Show model routing config")
    resolve_p = model_sub.add_parser("resolve", help="Resolve model for a tool")
    resolve_p.add_argument("tool", help="Tool name to resolve model for")

    # marketplace
    market_p = sub.add_parser("marketplace", help="Rule marketplace")
    market_sub = market_p.add_subparsers(dest="market_command")
    market_sub.add_parser("list", help="List marketplace bundles")
    reg_p = market_sub.add_parser("register", help="Register a bundle in marketplace")
    reg_p.add_argument("file", help="Bundle YAML file to register")
    inst_p = market_sub.add_parser("install", help="Install a bundle from marketplace")
    inst_p.add_argument("name", help="Bundle name to install")
    rem_p = market_sub.add_parser("remove", help="Remove a bundle from marketplace")
    rem_p.add_argument("name", help="Bundle name to remove")

    # memory
    mem_p = sub.add_parser("memory", help="Memory injection management")
    mem_sub = mem_p.add_subparsers(dest="mem_command")
    mem_sub.add_parser("inject", help="Inject rules into Claude memory")
    summary_p = mem_sub.add_parser("summary", help="Write session summary to memory")
    summary_p.add_argument("text", nargs="?", default="", help="Summary text")
    mem_sub.add_parser("list", help="List tribunal memory entries")
    mem_sub.add_parser("clear", help="Clear tribunal memory entries")

    # analytics
    analytics_p = sub.add_parser("analytics", help="Cost analytics and trends")
    analytics_p.add_argument("--json", dest="json_output", action="store_true", help="Output JSON")

    # bundle (air-gapped)
    bundle_p = sub.add_parser("bundle", help="Air-gapped bundle management")
    bundle_sub = bundle_p.add_subparsers(dest="bundle_command")
    bex_p = bundle_sub.add_parser("export", help="Export air-gapped bundle")
    bex_p.add_argument("--output", "-o", default=None, help="Output file")
    bim_p = bundle_sub.add_parser("import", help="Import air-gapped bundle")
    bim_p.add_argument("file", help="Bundle JSON file to import")
    bval_p = bundle_sub.add_parser("validate", help="Validate a bundle file")
    bval_p.add_argument("file", help="Bundle JSON file to validate")

    # dashboard
    dash_p = sub.add_parser("dashboard", help="Audit dashboard")
    dash_sub = dash_p.add_subparsers(dest="dash_command")
    dash_sub.add_parser("show", help="Show audit stats in terminal")
    html_p = dash_sub.add_parser("html", help="Export HTML audit report")
    html_p.add_argument("--output", "-o", default=None, help="Output file")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "rules": cmd_rules,
        "audit": cmd_audit,
        "cost": cmd_cost,
        "skills": cmd_skills,
        "permissions": cmd_permissions,
        "review": cmd_review,
        "report": cmd_report,
        "config": cmd_config,
        "plugin": cmd_plugin,
        "sync": cmd_sync,
        "managed": cmd_managed,
        "model": cmd_model,
        "marketplace": cmd_marketplace,
        "memory": cmd_memory,
        "analytics": cmd_analytics,
        "bundle": cmd_bundle,
        "dashboard": cmd_dashboard,
    }

    if args.command == "mcp-serve":
        from .mcp_server import main as mcp_main
        mcp_main()
        return

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(0)
