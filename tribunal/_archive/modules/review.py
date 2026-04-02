"""Review agents — parallel code review using Claude Code's coordinator mode.

Defines 4 review agents that can be dispatched in parallel:
1. TDD Agent — checks test coverage and TDD compliance
2. Security Agent — scans for vulnerabilities
3. Quality Agent — runs linters, type checkers, formatting
4. Spec Agent — verifies implementation matches spec
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReviewFinding:
    """A single finding from a review agent."""

    agent: str
    severity: str  # error, warning, info
    file: str = ""
    line: int = 0
    message: str = ""
    rule: str = ""


@dataclass
class ReviewReport:
    """Aggregated report from all review agents."""

    findings: list[ReviewFinding] = field(default_factory=list)
    passed: bool = True
    summary: str = ""

    def add(self, finding: ReviewFinding) -> None:
        self.findings.append(finding)
        if finding.severity == "error":
            self.passed = False

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "findings": [
                {
                    "agent": f.agent,
                    "severity": f.severity,
                    "file": f.file,
                    "line": f.line,
                    "message": f.message,
                    "rule": f.rule,
                }
                for f in self.findings
            ],
            "summary": self.summary,
        }

    def format(self) -> str:
        lines = ["\n  ⚖  Tribunal Review Report\n"]

        if self.passed:
            lines.append("  ✅ All checks passed!\n")
        else:
            lines.append(f"  ❌ {self.error_count} error(s), {self.warning_count} warning(s)\n")

        # Group by agent
        by_agent: dict[str, list[ReviewFinding]] = {}
        for f in self.findings:
            by_agent.setdefault(f.agent, []).append(f)

        for agent, findings in by_agent.items():
            lines.append(f"  [{agent}]")
            for f in findings:
                icon = "❌" if f.severity == "error" else "⚠️" if f.severity == "warning" else "ℹ️"
                loc = f"  {f.file}:{f.line}" if f.file else ""
                lines.append(f"    {icon} {f.message}{loc}")
            lines.append("")

        return "\n".join(lines)


# ── Individual Review Agents ──────────────────────────────────────────────────


def _review_tdd(cwd: str, changed_files: list[str]) -> list[ReviewFinding]:
    """Check TDD compliance for changed files."""
    findings = []

    for filepath in changed_files:
        if not filepath.endswith(".py"):
            continue
        basename = os.path.basename(filepath)
        if basename.startswith("test_") or basename.endswith("_test.py"):
            continue
        if basename in ("__init__.py", "conftest.py", "setup.py"):
            continue
        if "/tests/" in filepath or "/test/" in filepath:
            continue

        module = basename.removesuffix(".py")
        test_candidates = [
            os.path.join(cwd, "tests", f"test_{module}.py"),
            os.path.join(cwd, "test", f"test_{module}.py"),
            os.path.join(cwd, f"test_{module}.py"),
        ]
        file_dir = os.path.dirname(os.path.join(cwd, filepath))
        test_candidates.append(os.path.join(file_dir, f"test_{module}.py"))
        test_candidates.append(os.path.join(file_dir, "tests", f"test_{module}.py"))

        has_test = any(os.path.exists(t) for t in test_candidates)
        if not has_test:
            findings.append(ReviewFinding(
                agent="tdd",
                severity="error",
                file=filepath,
                message=f"No test file for {basename}. Expected tests/test_{module}.py",
                rule="tdd-enforcement",
            ))

    # Check for TS/TSX similarly
    for filepath in changed_files:
        if not (filepath.endswith(".ts") or filepath.endswith(".tsx")):
            continue
        basename = os.path.basename(filepath)
        if ".test." in basename or ".spec." in basename:
            continue
        if "/__tests__/" in filepath:
            continue

        module = basename.rsplit(".", 1)[0]
        ext = basename.rsplit(".", 1)[1]
        file_dir = os.path.dirname(os.path.join(cwd, filepath))
        test_candidates = [
            os.path.join(file_dir, f"{module}.test.{ext}"),
            os.path.join(file_dir, f"{module}.spec.{ext}"),
            os.path.join(file_dir, "__tests__", f"{module}.{ext}"),
        ]
        has_test = any(os.path.exists(t) for t in test_candidates)
        if not has_test:
            findings.append(ReviewFinding(
                agent="tdd",
                severity="warning",
                file=filepath,
                message=f"No test file for {basename}. Expected {module}.test.{ext}",
                rule="tdd-enforcement",
            ))

    return findings


def _review_security(cwd: str, changed_files: list[str]) -> list[ReviewFinding]:
    """Scan changed files for security issues."""
    import re

    findings = []
    secret_patterns = [
        (r'(?:api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}', "Hardcoded API key"),
        (r'(?:secret|password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{8,}', "Hardcoded password/secret"),
        (r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----', "Private key in source"),
        (r'sk-[A-Za-z0-9]{20,}', "OpenAI API key"),
        (r'ghp_[A-Za-z0-9]{36}', "GitHub token"),
        (r'xox[bpras]-[A-Za-z0-9\-]{10,}', "Slack token"),
    ]

    dangerous_patterns = [
        (r'\beval\s*\(', "eval() call — potential code injection"),
        (r'\bexec\s*\(', "exec() call — potential code injection"),
        (r'subprocess\..*shell\s*=\s*True', "Shell=True in subprocess — command injection risk"),
        (r'os\.system\s*\(', "os.system() — command injection risk"),
    ]

    for filepath in changed_files:
        full_path = os.path.join(cwd, filepath)
        if not os.path.isfile(full_path):
            continue
        # Skip binary and large files
        try:
            content = Path(full_path).read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        for pattern, label in secret_patterns:
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(ReviewFinding(
                        agent="security",
                        severity="error",
                        file=filepath,
                        line=i,
                        message=label,
                        rule="no-secrets",
                    ))

        for pattern, label in dangerous_patterns:
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(pattern, line):
                    findings.append(ReviewFinding(
                        agent="security",
                        severity="warning",
                        file=filepath,
                        line=i,
                        message=label,
                        rule="unsafe-code",
                    ))

    return findings


def _review_quality(cwd: str, changed_files: list[str]) -> list[ReviewFinding]:
    """Run quality checks on changed files."""
    findings = []

    # Check Python files with ruff if available
    py_files = [f for f in changed_files if f.endswith(".py")]
    if py_files:
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json"] + py_files,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                for issue in json.loads(result.stdout):
                    findings.append(ReviewFinding(
                        agent="quality",
                        severity="warning",
                        file=issue.get("filename", ""),
                        line=issue.get("location", {}).get("row", 0),
                        message=issue.get("message", ""),
                        rule=issue.get("code", ""),
                    ))
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

    # Check TS/JS files with eslint if available
    ts_files = [f for f in changed_files if f.endswith((".ts", ".tsx", ".js", ".jsx"))]
    if ts_files:
        try:
            result = subprocess.run(
                ["npx", "eslint", "--format=json", "--no-warn-ignored"] + ts_files,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                for file_result in json.loads(result.stdout):
                    for msg in file_result.get("messages", []):
                        findings.append(ReviewFinding(
                            agent="quality",
                            severity="error" if msg.get("severity", 0) == 2 else "warning",
                            file=file_result.get("filePath", ""),
                            line=msg.get("line", 0),
                            message=msg.get("message", ""),
                            rule=msg.get("ruleId", ""),
                        ))
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

    return findings


def _review_spec(cwd: str, changed_files: list[str]) -> list[ReviewFinding]:
    """Check for spec compliance — verify implementation matches spec."""
    findings = []

    # Check if spec file exists
    spec_paths = [
        os.path.join(cwd, "SPEC.md"),
        os.path.join(cwd, "spec.md"),
        os.path.join(cwd, ".tribunal", "spec.md"),
    ]

    has_spec = any(os.path.exists(p) for p in spec_paths)

    if not has_spec and len(changed_files) > 5:
        findings.append(ReviewFinding(
            agent="spec",
            severity="info",
            message="No spec file found. Consider creating SPEC.md for larger changes.",
            rule="spec-recommended",
        ))

    # Check for TODO/FIXME/HACK in changed files
    for filepath in changed_files:
        full_path = os.path.join(cwd, filepath)
        if not os.path.isfile(full_path):
            continue
        try:
            lines = Path(full_path).read_text(errors="ignore").split("\n")
        except (OSError, UnicodeDecodeError):
            continue

        for i, line in enumerate(lines, 1):
            line_upper = line.upper()
            if "TODO" in line_upper or "FIXME" in line_upper or "HACK" in line_upper:
                findings.append(ReviewFinding(
                    agent="spec",
                    severity="info",
                    file=filepath,
                    line=i,
                    message=f"Unresolved marker: {line.strip()[:80]}",
                    rule="unresolved-marker",
                ))

    return findings


# ── Coordinator ───────────────────────────────────────────────────────────────


AGENTS = {
    "tdd": _review_tdd,
    "security": _review_security,
    "quality": _review_quality,
    "spec": _review_spec,
}


def get_changed_files(cwd: str) -> list[str]:
    """Get list of changed files via git diff."""
    try:
        # Staged + unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        files = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Also include staged changes
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.stdout.strip():
            files.extend(result2.stdout.strip().split("\n"))

        return list(set(f for f in files if f))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def run_review(cwd: str | None = None,
               agents: list[str] | None = None,
               files: list[str] | None = None) -> ReviewReport:
    """Run review agents and produce an aggregated report."""
    project_dir = cwd or str(Path.cwd())

    if files is None:
        files = get_changed_files(project_dir)

    if not files:
        report = ReviewReport()
        report.summary = "No changed files to review."
        return report

    agent_names = agents or list(AGENTS.keys())
    report = ReviewReport()

    for name in agent_names:
        handler = AGENTS.get(name)
        if handler:
            findings = handler(project_dir, files)
            for f in findings:
                report.add(f)

    # Build summary
    if report.passed:
        report.summary = f"All {len(agent_names)} agents passed. {len(files)} file(s) reviewed."
    else:
        report.summary = (
            f"{report.error_count} errors, {report.warning_count} warnings "
            f"across {len(files)} file(s) from {len(agent_names)} agents."
        )

    return report
