"""Go file checker — runs go vet and golangci-lint for quality gates.

Detects issues via go vet and optional golangci-lint.
Skips test files (*_test.go) by default.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import CheckResult, Finding, register


def _is_test_file(path: Path) -> bool:
    return path.name.endswith("_test.go")


@register([".go"])
def check_go(file_path: Path, project_root: Path) -> CheckResult:
    """Check Go file with go vet and golangci-lint."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="go", file=rel)

    if _is_test_file(file_path):
        return result

    go_bin = shutil.which("go")
    if not go_bin:
        return result

    _run_go_vet(go_bin, file_path, rel, result)

    golangci_bin = shutil.which("golangci-lint")
    if golangci_bin:
        _run_golangci_lint(golangci_bin, file_path, rel, result)

    return result


check_go._checker_name = "go"  # type: ignore[attr-defined]


def _run_go_vet(go_bin: str, file_path: Path, rel: str, result: CheckResult) -> None:
    """Run go vet and collect findings."""
    try:
        proc = subprocess.run(
            [go_bin, "vet", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        output = proc.stdout + proc.stderr
        line_re = re.compile(r":(\d+)(?::\d+)?:\s*(.+)")
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = line_re.search(line)
            if m:
                result.findings.append(
                    Finding(
                        checker="go",
                        file=rel,
                        line=int(m.group(1)),
                        severity="error",
                        message=f"go vet: {m.group(2)}",
                        rule_id="go/vet",
                    )
                )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _run_golangci_lint(
    golangci_bin: str, file_path: Path, rel: str, result: CheckResult
) -> None:
    """Run golangci-lint and collect findings."""
    try:
        proc = subprocess.run(
            [golangci_bin, "run", "--fast", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if proc.returncode != 0:
            issue_re = re.compile(r":(\d+)(?::\d+)?:\s*(.+)")
            for line in (proc.stdout + proc.stderr).splitlines():
                line = line.strip()
                if not line:
                    continue
                m = issue_re.search(line)
                if m:
                    result.findings.append(
                        Finding(
                            checker="go",
                            file=rel,
                            line=int(m.group(1)),
                            severity="warning",
                            message=f"golangci-lint: {m.group(2)}",
                            rule_id="go/lint",
                        )
                    )
    except (subprocess.TimeoutExpired, OSError):
        pass
