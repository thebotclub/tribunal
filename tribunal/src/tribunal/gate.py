"""tribunal-gate — Claude Code hook handler entry point.

This is called by Claude Code via the hooks system. It reads a hook event
from stdin, evaluates project rules, logs the result, and exits with the
appropriate code (0=allow, 2=block).

By default, Tribunal is **fail-closed**: if the gate cannot parse input or
encounters an unexpected error, it blocks the operation (exit 2). This is
the safe default for a governance tool. Set TRIBUNAL_FAIL_MODE=open to
override this for environments where availability is preferred over safety.
"""

from __future__ import annotations

import json
import os
import sys

from .audit import log_event
from .hooks import LIFECYCLE_HANDLERS
from .protocol import HookEvent, HookVerdict, read_hook_event, write_verdict
from .rules import RuleEngine


def _fail_exit_code() -> int:
    """Return the exit code for error conditions based on fail mode policy.

    closed (default) → exit 2 (block)
    open → exit 0 (allow)
    """
    mode = os.environ.get("TRIBUNAL_FAIL_MODE", "closed").lower()
    return 0 if mode == "open" else 2


def main() -> None:
    """Entry point for the tribunal-gate command."""
    try:
        event = read_hook_event()
    except json.JSONDecodeError as e:
        sys.stderr.write(f"tribunal: malformed hook JSON: {e}\n")
        sys.exit(_fail_exit_code())
    except KeyError as e:
        sys.stderr.write(f"tribunal: missing required field in hook event: {e}\n")
        sys.exit(_fail_exit_code())
    except Exception as e:
        sys.stderr.write(f"tribunal: failed to parse hook event: {e}\n")
        sys.exit(_fail_exit_code())

    try:
        # Check for lifecycle event handlers first
        handler = LIFECYCLE_HANDLERS.get(event.hook_event_name)
        if handler:
            verdict = handler(event)
            write_verdict(verdict)

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
    except Exception as e:
        # Log error to audit trail if possible
        try:
            log_event(event, False, f"tribunal-error: {e}")
        except Exception:
            pass
        sys.stderr.write(f"tribunal: rule evaluation error: {e}\n")
        sys.exit(_fail_exit_code())
