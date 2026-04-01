"""tribunal-gate — Claude Code hook handler entry point.

This is called by Claude Code via the hooks system. It reads a hook event
from stdin, evaluates project rules, logs the result, and exits with the
appropriate code (0=allow, 2=block).
"""

from __future__ import annotations

import sys

from .audit import log_event
from .protocol import HookVerdict, read_hook_event, write_verdict
from .rules import RuleEngine


def main() -> None:
    """Entry point for the tribunal-gate command."""
    try:
        event = read_hook_event()
    except Exception as e:
        # If we can't parse input, allow and log the error
        sys.stderr.write(f"tribunal: failed to parse hook event: {e}\n")
        sys.exit(0)

    # Load rules from the project
    engine = RuleEngine.from_project(event.cwd)

    # Evaluate rules
    verdict = engine.evaluate(event)

    # Audit log
    rule_names = ""
    if not verdict.allow:
        rule_names = verdict.reason
    log_event(event, verdict.allow, rule_names)

    # Respond to Claude Code
    write_verdict(verdict)
