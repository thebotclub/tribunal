"""Python file checker — runs ruff and basedpyright/mypy for quality gates.

Detects lint errors and type errors in Python source files.
Skips test files (test_*.py, *_test.py) by default.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import CheckResult, Finding, register


def _is_test_file(path: Path) -> bool:
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


@register([".py"])
def check_python(file_path: Path, project_root: Path) -> CheckResult:
    """Check Python file with ruff and type checker."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="python", file=rel)

    if _is_test_file(file_path):
        return result

    ruff_bin = shutil.which("ruff")
    mypy_bin = shutil.which("mypy")
    pyright_bin = shutil.which("basedpyright") or shutil.which("pyright")

    if not (ruff_bin or mypy_bin or pyright_bin):
        return result

    if ruff_bin:
        _run_ruff(ruff_bin, file_path, rel, result)

    if pyright_bin:
        _run_pyright(pyright_bin, file_path, rel, result)
    elif mypy_bin:
        _run_mypy(mypy_bin, file_path, rel, result)

    return result


check_python._checker_name = "python"  # type: ignore[attr-defined]


def _run_ruff(ruff_bin: str, file_path: Path, rel: str, result: CheckResult) -> None:
    """Run ruff check and collect findings."""
    try:
        proc = subprocess.run(
            [ruff_bin, "check", "--output-format=json", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.stdout.strip():
            data = json.loads(proc.stdout)
            for item in data:
                line = item.get("location", {}).get("row", 0)
                code = item.get("code", "unknown")
                msg = item.get("message", "")
                result.findings.append(
                    Finding(
                        checker="python",
                        file=rel,
                        line=line,
                        severity="error",
                        message=f"ruff {code}: {msg}",
                        rule_id=f"python/ruff-{code}",
                    )
                )
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass


def _run_pyright(pyright_bin: str, file_path: Path, rel: str, result: CheckResult) -> None:
    """Run basedpyright/pyright and collect findings."""
    try:
        proc = subprocess.run(
            [pyright_bin, "--outputjson", str(file_path.resolve())],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if proc.stdout.strip():
            data = json.loads(proc.stdout)
            for diag in data.get("generalDiagnostics", []):
                if diag.get("severity", "") != "error":
                    continue
                line = diag.get("range", {}).get("start", {}).get("line", 0)
                msg = diag.get("message", "").split("\n")[0]
                rule = diag.get("rule", "type-error")
                result.findings.append(
                    Finding(
                        checker="python",
                        file=rel,
                        line=line,
                        severity="error",
                        message=f"pyright: {msg}",
                        rule_id=f"python/pyright-{rule}",
                    )
                )
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass


def _run_mypy(mypy_bin: str, file_path: Path, rel: str, result: CheckResult) -> None:
    """Run mypy and collect findings."""
    try:
        proc = subprocess.run(
            [mypy_bin, "--no-color-output", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        error_re = re.compile(r":(\d+):\s*(error|warning):\s*(.+?)(?:\s*\[(.+?)\])?$")
        for line in (proc.stdout + proc.stderr).splitlines():
            m = error_re.search(line)
            if m:
                line_num = int(m.group(1))
                severity = m.group(2)
                msg = m.group(3)
                code = m.group(4) or "unknown"
                result.findings.append(
                    Finding(
                        checker="python",
                        file=rel,
                        line=line_num,
                        severity=severity,
                        message=f"mypy: {msg}",
                        rule_id=f"python/mypy-{code}",
                    )
                )
    except (subprocess.TimeoutExpired, OSError):
        pass
