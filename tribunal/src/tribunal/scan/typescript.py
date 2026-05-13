"""TypeScript/JavaScript checker — runs eslint and tsc for quality gates.

Detects lint errors via eslint and type errors via tsc.
Skips test files (*.test.ts, *.spec.ts, etc.) by default.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import CheckResult, Finding, register

_TS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts"]


def _is_test_file(path: Path) -> bool:
    name = path.name
    return any(
        name.endswith(suffix)
        for suffix in (
            ".test.ts",
            ".spec.ts",
            ".test.tsx",
            ".spec.tsx",
            ".test.js",
            ".spec.js",
        )
    )


def _find_project_root(file_path: Path) -> Path | None:
    """Find nearest directory with package.json."""
    current = file_path.parent
    for _ in range(20):
        if (current / "package.json").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _find_tool(tool_name: str, project_root: Path | None) -> str | None:
    """Find tool binary, preferring local node_modules."""
    if project_root:
        local_bin = project_root / "node_modules" / ".bin" / tool_name
        if local_bin.exists():
            return str(local_bin)
    return shutil.which(tool_name)


@register(_TS_EXTENSIONS)
def check_typescript(file_path: Path, project_root: Path) -> CheckResult:
    """Check TypeScript/JavaScript file with eslint and tsc."""
    rel = (
        str(file_path.relative_to(project_root))
        if file_path.is_relative_to(project_root)
        else str(file_path)
    )
    result = CheckResult(checker="typescript", file=rel)

    if _is_test_file(file_path):
        return result

    ts_project_root = _find_project_root(file_path)

    eslint_bin = _find_tool("eslint", ts_project_root)
    tsc_bin = (
        _find_tool("tsc", ts_project_root)
        if file_path.suffix in {".ts", ".tsx", ".mts"}
        else None
    )

    if not (eslint_bin or tsc_bin):
        return result

    if eslint_bin:
        _run_eslint(eslint_bin, file_path, ts_project_root, rel, result)

    if tsc_bin:
        _run_tsc(tsc_bin, file_path, ts_project_root, rel, result)

    return result


check_typescript._checker_name = "typescript"  # type: ignore[attr-defined]


def _run_eslint(
    eslint_bin: str,
    file_path: Path,
    project_root: Path | None,
    rel: str,
    result: CheckResult,
) -> None:
    """Run eslint and collect findings."""
    try:
        proc = subprocess.run(
            [eslint_bin, "--format", "json", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=project_root,
            timeout=30,
        )
        if proc.stdout.strip():
            data = json.loads(proc.stdout)
            for file_result in data:
                for msg in file_result.get("messages", []):
                    severity = "error" if msg.get("severity", 0) == 2 else "warning"
                    rule_id_val = msg.get("ruleId", "unknown")
                    result.findings.append(
                        Finding(
                            checker="typescript",
                            file=rel,
                            line=msg.get("line", 0),
                            severity=severity,
                            message=f"eslint {rule_id_val}: {msg.get('message', '')}",
                            rule_id=f"typescript/eslint-{rule_id_val}",
                        )
                    )
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass


def _run_tsc(
    tsc_bin: str,
    file_path: Path,
    project_root: Path | None,
    rel: str,
    result: CheckResult,
) -> None:
    """Run tsc --noEmit and collect findings."""
    tsconfig_path = None
    if project_root:
        for name in ("tsconfig.json", "tsconfig.app.json"):
            candidate = project_root / name
            if candidate.exists():
                tsconfig_path = candidate
                break

    cmd = [tsc_bin, "--noEmit"]
    if tsconfig_path:
        cmd.extend(["--project", str(tsconfig_path)])
    else:
        cmd.append(str(file_path))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=project_root,
            timeout=60,
        )
        error_re = re.compile(r"\((\d+),\d+\): error (TS\d+): (.+)")
        for line in (proc.stdout + proc.stderr).splitlines():
            m = error_re.search(line)
            if m:
                result.findings.append(
                    Finding(
                        checker="typescript",
                        file=rel,
                        line=int(m.group(1)),
                        severity="error",
                        message=f"tsc {m.group(2)}: {m.group(3)}",
                        rule_id=f"typescript/tsc-{m.group(2)}",
                    )
                )
    except (subprocess.TimeoutExpired, OSError):
        pass
