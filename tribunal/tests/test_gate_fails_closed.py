"""Regression tests: tribunal-gate MUST fail closed on errors.

This is the single most important credibility test in the v3 pivot. A
governance tool that silently allows operations on error (fail-open) is
worse than no governance tool at all — it produces a fake audit trail.

The contract these tests lock in:

1. By default, ANY unexpected error in the gate exits with code 2 (BLOCK).
2. The fail mode is configurable via TRIBUNAL_FAIL_MODE:
     - unset / "closed" / anything-not-"open"  → exit 2 (block)
     - "open"                                  → exit 0 (allow)
3. The error is always surfaced to stderr (never silently swallowed).
4. Errors are recorded to the audit trail so operators can see them.

If you find yourself loosening these assertions, STOP and discuss on the
v3-pivot PR first. Fail-open is a launch blocker.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest


# ── Exit-code helper contract ────────────────────────────────────────────────


class TestFailExitCode:
    """The fail-mode resolver must default closed."""

    def test_default_is_closed(self):
        from tribunal.gate import _fail_exit_code

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TRIBUNAL_FAIL_MODE", None)
            assert _fail_exit_code() == 2, "default fail mode MUST be closed"

    def test_explicit_closed(self):
        from tribunal.gate import _fail_exit_code

        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "closed"}):
            assert _fail_exit_code() == 2

    def test_open_mode_allows(self):
        from tribunal.gate import _fail_exit_code

        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "open"}):
            assert _fail_exit_code() == 0

    def test_case_insensitive(self):
        from tribunal.gate import _fail_exit_code

        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "OPEN"}):
            assert _fail_exit_code() == 0
        with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "Closed"}):
            assert _fail_exit_code() == 2

    def test_unknown_value_treated_as_closed(self):
        """An unknown value MUST NOT silently mean 'open'."""
        from tribunal.gate import _fail_exit_code

        for val in ["yes", "true", "1", "permissive", "allow", "no", ""]:
            with patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": val}):
                assert _fail_exit_code() == 2, (
                    f"TRIBUNAL_FAIL_MODE={val!r} must NOT be interpreted as open"
                )


# ── End-to-end main() behaviour ──────────────────────────────────────────────


class TestGateMainFailsClosed:
    """gate.main() must exit 2 on every error path by default."""

    def test_malformed_json_blocks(self):
        from tribunal.gate import main

        with (
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = "{ this is not json"
            main()
        assert exc.value.code == 2

    def test_truncated_json_blocks(self):
        from tribunal.gate import main

        with (
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = '{"hook_event_name": "PreToolUse"'
            main()
        assert exc.value.code == 2

    def test_binary_garbage_blocks(self):
        from tribunal.gate import main

        with (
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = "\x00\x01\x02\xff garbage"
            main()
        assert exc.value.code == 2

    def test_rule_engine_exception_blocks(self):
        """If rule evaluation itself blows up, we still fail closed."""
        from tribunal.gate import main

        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "cwd": "/tmp",
                "tool_name": "FileEdit",
                "tool_input": {"path": "a.py"},
            }
        )
        with (
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            patch(
                "tribunal.gate.RuleEngine.from_project",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = payload
            main()
        assert exc.value.code == 2

    def test_rule_engine_exception_records_audit_event(self, tmp_path):
        """Errors must produce an audit trail entry, not be silently swallowed."""
        from tribunal.gate import main

        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "cwd": str(tmp_path),
                "tool_name": "FileEdit",
                "tool_input": {"path": "a.py"},
            }
        )
        with (
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            patch(
                "tribunal.gate.RuleEngine.from_project",
                side_effect=RuntimeError("simulated rule engine failure"),
            ),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = payload
            main()
        assert exc.value.code == 2

        audit_path = tmp_path / ".tribunal" / "audit.jsonl"
        assert audit_path.exists(), "an audit entry must be written on error"
        lines = [
            json.loads(line) for line in audit_path.read_text().splitlines() if line
        ]
        # The last entry should describe the tribunal-error
        assert any(
            "tribunal-error" in (entry.get("rule") or "")
            or "tribunal-error" in json.dumps(entry)
            for entry in lines
        ), f"no tribunal-error entry found in audit log: {lines}"

    def test_open_mode_allows_on_error(self):
        """Explicit opt-in to fail-open behaves as documented."""
        from tribunal.gate import main

        with (
            patch.dict(os.environ, {"TRIBUNAL_FAIL_MODE": "open"}),
            patch("sys.stdin") as mock_stdin,
            patch("sys.stderr"),
            pytest.raises(SystemExit) as exc,
        ):
            mock_stdin.read.return_value = "{not json"
            main()
        assert exc.value.code == 0


# ── Documentation contract ───────────────────────────────────────────────────


class TestGateModuleContract:
    """Lock in the docstring claim so future refactors can't quietly drop it."""

    def test_module_docstring_documents_fail_closed_default(self):
        import tribunal.gate as gate

        doc = (gate.__doc__ or "").lower()
        assert "fail-closed" in doc or "fail closed" in doc, (
            "gate.py module docstring MUST document the fail-closed default"
        )
        assert "tribunal_fail_mode" in doc, (
            "gate.py module docstring MUST document the TRIBUNAL_FAIL_MODE env var"
        )
