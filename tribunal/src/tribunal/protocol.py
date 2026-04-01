"""Hook protocol handler for Claude Code's hook system.

Implements the stdin/stdout JSON protocol that Claude Code uses to communicate
with external hook commands. Handles PreToolUse, PostToolUse, SessionStart, etc.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HookEvent:
    """Parsed hook event from Claude Code's stdin JSON."""

    hook_event_name: str
    session_id: str
    cwd: str
    transcript_path: str = ""
    permission_mode: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None
    # PreToolUse / PostToolUse fields
    tool_name: str | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str | None = None
    # PostToolUse
    tool_response: dict[str, Any] = field(default_factory=dict)
    # PostToolUseFailure
    error: str | None = None
    is_interrupt: bool = False
    # SessionStart
    source: str | None = None
    model: str | None = None
    # UserPromptSubmit
    prompt: str | None = None
    # Stop
    last_assistant_message: str | None = None
    # Raw data for anything we didn't parse
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookVerdict:
    """Result of evaluating a hook — tells Claude Code what to do."""

    allow: bool = True
    reason: str = ""
    stderr_message: str = ""
    additional_context: str = ""
    updated_input: dict[str, Any] | None = None

    @property
    def exit_code(self) -> int:
        """0 = allow (quiet), 2 = block (show to model)."""
        return 0 if self.allow else 2


def read_hook_event() -> HookEvent:
    """Read and parse the hook event JSON from stdin."""
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return HookEvent(hook_event_name="Unknown", session_id="", cwd="")

    data = json.loads(raw_input)
    return HookEvent(
        hook_event_name=data.get("hook_event_name", "Unknown"),
        session_id=data.get("session_id", ""),
        cwd=data.get("cwd", ""),
        transcript_path=data.get("transcript_path", ""),
        permission_mode=data.get("permission_mode"),
        agent_id=data.get("agent_id"),
        agent_type=data.get("agent_type"),
        tool_name=data.get("tool_name"),
        tool_input=data.get("tool_input", {}),
        tool_use_id=data.get("tool_use_id"),
        tool_response=data.get("tool_response", {}),
        error=data.get("error"),
        is_interrupt=data.get("is_interrupt", False),
        source=data.get("source"),
        model=data.get("model"),
        prompt=data.get("prompt"),
        last_assistant_message=data.get("last_assistant_message"),
        raw=data,
    )


def write_verdict(verdict: HookVerdict) -> None:
    """Write the hook response to stdout and exit with proper code."""
    if verdict.allow:
        output: dict[str, Any] = {"continue": True}
        if verdict.additional_context:
            output["hookSpecificOutput"] = {
                "additionalContext": verdict.additional_context,
            }
        json.dump(output, sys.stdout)
    else:
        # For blocked operations, write reason to stderr (shown to model)
        sys.stderr.write(verdict.reason + "\n")
        if verdict.stderr_message:
            sys.stderr.write(verdict.stderr_message + "\n")

    sys.exit(verdict.exit_code)
