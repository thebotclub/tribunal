"""MCP server — expose Tribunal as tools for Claude Code and other agents.

Implements the Model Context Protocol (MCP) over stdio, exposing Tribunal's
rules, audit log, cost data, and gate evaluation as callable tools.

Protocol: JSON-RPC 2.0 over stdin/stdout
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# ── MCP Protocol Types ────────────────────────────────────────────────────────


def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ── Tool Definitions ──────────────────────────────────────────────────────────


TOOLS = [
    {
        "name": "tribunal_rules_list",
        "description": "List all active Tribunal rules for the current project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Project directory path. Defaults to current directory.",
                }
            },
        },
    },
    {
        "name": "tribunal_audit_recent",
        "description": "Get recent audit log entries showing tool calls and verdicts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Project directory path."},
                "count": {
                    "type": "integer",
                    "description": "Number of recent entries to return (default: 20).",
                },
            },
        },
    },
    {
        "name": "tribunal_cost_report",
        "description": "Get current session cost data and budget status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Project directory path."},
            },
        },
    },
    {
        "name": "tribunal_evaluate",
        "description": "Evaluate a hypothetical tool call against Tribunal rules without executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Project directory path."},
                "tool_name": {
                    "type": "string",
                    "description": "Tool name (e.g. FileEdit, Bash).",
                },
                "tool_input": {
                    "type": "object",
                    "description": "Tool input parameters.",
                },
                "hook_event": {
                    "type": "string",
                    "description": "Hook event type (default: PreToolUse).",
                },
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "tribunal_skills_list",
        "description": "List all available Tribunal skills (bundled and project).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Project directory path."},
            },
        },
    },
    {
        "name": "tribunal_status",
        "description": "Get Tribunal status summary: hooks, rules, audit stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Project directory path."},
            },
        },
    },
]


# ── Tool Handlers ─────────────────────────────────────────────────────────────


def _handle_rules_list(params: dict) -> list[dict]:
    from .rules import RuleEngine

    cwd = params.get("cwd", str(Path.cwd()))
    engine = RuleEngine.from_project(cwd)
    return [
        {
            "name": r.name,
            "trigger": r.trigger,
            "action": r.action,
            "condition": r.condition,
            "message": r.message,
            "enabled": r.enabled,
        }
        for r in engine.rules
    ]


def _handle_audit_recent(params: dict) -> list[dict]:
    cwd = params.get("cwd", str(Path.cwd()))
    count = params.get("count", 20)
    audit_path = Path(cwd) / ".tribunal" / "audit.jsonl"

    if not audit_path.exists():
        return []

    lines = audit_path.read_text().strip().split("\n")
    entries = []
    for line in lines[-count:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _handle_cost_report(params: dict) -> dict:
    from .cost import check_budget, get_budget, get_cost_snapshot

    cwd = params.get("cwd", str(Path.cwd()))
    snapshot = get_cost_snapshot(cwd)
    budget = get_budget(cwd)
    budget_check = check_budget(cwd)

    return {
        "session_cost_usd": snapshot.session_cost_usd,
        "daily_cost_usd": snapshot.daily_cost_usd,
        "model": snapshot.model,
        "input_tokens": snapshot.input_tokens,
        "output_tokens": snapshot.output_tokens,
        "budget": {
            "session_usd": budget.session_usd,
            "daily_usd": budget.daily_usd,
        },
        "budget_status": {
            "exceeded": budget_check.exceeded,
            "warning": budget_check.warning,
            "message": budget_check.message,
        },
    }


def _handle_evaluate(params: dict) -> dict:
    from .protocol import HookEvent
    from .rules import RuleEngine

    cwd = params.get("cwd", str(Path.cwd()))
    event = HookEvent(
        hook_event_name=params.get("hook_event", "PreToolUse"),
        session_id="mcp-eval",
        cwd=cwd,
        tool_name=params.get("tool_name"),
        tool_input=params.get("tool_input", {}),
    )
    engine = RuleEngine.from_project(cwd)
    verdict = engine.evaluate(event)
    return {
        "allowed": verdict.allow,
        "reason": verdict.reason,
        "additional_context": verdict.additional_context,
    }


def _handle_skills_list(params: dict) -> list[dict]:
    from .skills import list_all_skills

    cwd = params.get("cwd", str(Path.cwd()))
    skills = list_all_skills(cwd)
    return [
        {
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "bundled": s.bundled,
        }
        for s in skills
    ]


def _handle_status(params: dict) -> dict:
    from .rules import RuleEngine

    cwd = params.get("cwd", str(Path.cwd()))
    project = Path(cwd)

    # Check hooks
    config_path = project / ".claude" / "claudeconfig.json"
    hooks_active = False
    hook_count = 0
    if config_path.exists():
        config = json.loads(config_path.read_text())
        hooks = config.get("hooks", {})
        hooks_active = "tribunal-gate" in json.dumps(hooks)
        hook_count = sum(len(v) for v in hooks.values())

    # Rules
    engine = RuleEngine.from_project(cwd)
    rules_count = len([r for r in engine.rules if r.enabled])

    # Audit
    audit_path = project / ".tribunal" / "audit.jsonl"
    audit_total = 0
    audit_blocked = 0
    if audit_path.exists():
        lines = audit_path.read_text().strip().split("\n")
        audit_total = len(lines)
        audit_blocked = sum(1 for l in lines if '"allowed":false' in l)

    return {
        "hooks_active": hooks_active,
        "hook_count": hook_count,
        "rules_count": rules_count,
        "audit_total": audit_total,
        "audit_blocked": audit_blocked,
    }


_TOOL_HANDLERS = {
    "tribunal_rules_list": _handle_rules_list,
    "tribunal_audit_recent": _handle_audit_recent,
    "tribunal_cost_report": _handle_cost_report,
    "tribunal_evaluate": _handle_evaluate,
    "tribunal_skills_list": _handle_skills_list,
    "tribunal_status": _handle_status,
}


# ── MCP Server Loop ──────────────────────────────────────────────────────────


def handle_request(request: dict) -> dict:
    """Handle a single JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return _jsonrpc_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "tribunal",
                "version": __import__("tribunal").__version__,
            },
        })

    elif method == "notifications/initialized":
        return {}  # Notification, no response needed

    elif method == "tools/list":
        return _jsonrpc_response(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = _TOOL_HANDLERS.get(tool_name)
        if not handler:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(tool_args)
            return _jsonrpc_response(req_id, {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2)}
                ]
            })
        except Exception as e:
            return _jsonrpc_error(req_id, -32603, str(e))

    elif method == "ping":
        return _jsonrpc_response(req_id, {})

    else:
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


def serve_stdio() -> None:
    """Run the MCP server over stdin/stdout (JSON-RPC 2.0)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response:  # Skip empty responses for notifications
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    """Entry point for tribunal mcp-serve."""
    serve_stdio()
