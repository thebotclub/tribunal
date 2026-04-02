"""TDD enforcement checker — verifies test files exist for source files.

Checks that each source file has a corresponding test file:
  - Python: src.py → test_src.py or src_test.py
  - TypeScript: src.ts → src.test.ts or src.spec.ts
  - Go: src.go → src_test.go

Also builds a reverse dependency graph for Python to find affected tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

from . import CheckResult, Finding, register

_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", "dist", "build"}


# ── Test file detection ───────────────────────────────────────────────────────


def _has_python_test(file_path: Path, project_root: Path) -> bool:
    """Check if a Python source file has a corresponding test file."""
    stem = file_path.stem

    # Skip if already a test file or special file
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    if stem.startswith("_") or stem == "__init__":
        return True

    # Search common test locations
    candidates = [
        file_path.parent / f"test_{stem}.py",
        file_path.parent / f"{stem}_test.py",
        project_root / "tests" / f"test_{stem}.py",
        project_root / "tests" / f"{stem}_test.py",
        project_root / "test" / f"test_{stem}.py",
    ]

    return any(c.is_file() for c in candidates)


def _has_typescript_test(file_path: Path) -> bool:
    """Check if a TypeScript/JS file has a corresponding test file."""
    name = file_path.name

    # Already a test file
    if any(name.endswith(s) for s in (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx", ".test.js", ".spec.js")):
        return True

    # Skip config/special files
    if name in {"index.ts", "index.tsx", "index.js", "main.ts", "main.js"}:
        return True

    directory = file_path.parent
    if file_path.suffix in (".tsx", ".ts"):
        base = file_path.stem
        for ext in (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"):
            if (directory / f"{base}{ext}").is_file():
                return True

    if file_path.suffix in (".js", ".jsx", ".mjs"):
        base = file_path.stem
        for ext in (".test.js", ".spec.js"):
            if (directory / f"{base}{ext}").is_file():
                return True

    return False


def _has_go_test(file_path: Path) -> bool:
    """Check if a Go file has a corresponding test file."""
    if file_path.name.endswith("_test.go"):
        return True
    test_file = file_path.parent / f"{file_path.stem}_test.go"
    return test_file.is_file()


# ── Python dependency graph ───────────────────────────────────────────────────


def find_affected_tests(
    changed_file: Path,
    project_root: Path,
    *,
    max_depth: int = 10,
) -> list[Path]:
    """Find test files affected by a change to the given source file.

    Builds a reverse dependency graph from Python imports, then does a
    BFS to find reachable test files.
    """
    if not changed_file.exists() or changed_file.suffix != ".py":
        return []

    py_files = [
        f
        for f in project_root.rglob("*.py")
        if not any(part in _SKIP_DIRS for part in f.parts)
    ]

    # Build reverse graph: module_stem -> set of dependent stems
    graph: dict[str, set[str]] = {}
    test_index: dict[str, list[Path]] = {}

    for pf in py_files:
        stem = pf.stem
        if stem.startswith("test_") or stem.endswith("_test"):
            test_index.setdefault(stem, []).append(pf)

        imports = _parse_imports(pf)
        for imp in imports:
            dep_stem = imp.split(".")[-1] if "." in imp else imp
            dep_stem = dep_stem.lstrip(".")
            if dep_stem:
                graph.setdefault(dep_stem, set()).add(stem)

    # BFS from changed file
    changed_stem = changed_file.stem
    visited: set[str] = set()
    queue = [changed_stem]
    found_tests: list[Path] = []

    depth = 0
    while queue and depth < max_depth:
        next_queue: list[str] = []
        for stem in queue:
            if stem in visited:
                continue
            visited.add(stem)
            for dep in graph.get(stem, set()):
                if dep not in visited:
                    next_queue.append(dep)
                    found_tests.extend(test_index.get(dep, []))
        queue = next_queue
        depth += 1

    # Also check conventional test file
    found_tests.extend(test_index.get(f"test_{changed_stem}", []))

    # Deduplicate
    seen: set[str] = set()
    unique: list[Path] = []
    for t in found_tests:
        key = str(t)
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique


def _parse_imports(file_path: Path) -> set[str]:
    """Extract top-level module names imported by a Python file."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, OSError):
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                prefix = "." * (node.level or 0)
                imports.add(f"{prefix}{node.module}")
    return imports


# ── Checker registration ──────────────────────────────────────────────────────


@register([".py"])
def check_tdd_python(file_path: Path, project_root: Path) -> CheckResult:
    """Check that Python source files have corresponding test files."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="tdd", file=rel)

    # Skip test files themselves
    stem = file_path.stem
    if stem.startswith("test_") or stem.endswith("_test"):
        return result
    if stem.startswith("_") or stem == "__init__":
        return result

    if not _has_python_test(file_path, project_root):
        result.findings.append(
            Finding(
                checker="tdd",
                file=rel,
                line=0,
                severity="warning",
                message=f"No test file found for {file_path.name}. Expected test_{stem}.py",
                rule_id="tdd/missing-test-python",
            )
        )

    return result


check_tdd_python._checker_name = "tdd"  # type: ignore[attr-defined]


@register([".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts"])
def check_tdd_typescript(file_path: Path, project_root: Path) -> CheckResult:
    """Check that TypeScript/JS source files have corresponding test files."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="tdd", file=rel)

    name = file_path.name
    if any(name.endswith(s) for s in (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx", ".test.js", ".spec.js")):
        return result
    if name in {"index.ts", "index.tsx", "index.js", "main.ts", "main.js"}:
        return result

    if not _has_typescript_test(file_path):
        base = file_path.stem
        result.findings.append(
            Finding(
                checker="tdd",
                file=rel,
                line=0,
                severity="warning",
                message=f"No test file found for {name}. Expected {base}.test.ts",
                rule_id="tdd/missing-test-typescript",
            )
        )

    return result


check_tdd_typescript._checker_name = "tdd"  # type: ignore[attr-defined]


@register([".go"])
def check_tdd_go(file_path: Path, project_root: Path) -> CheckResult:
    """Check that Go source files have corresponding test files."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="tdd", file=rel)

    if file_path.name.endswith("_test.go"):
        return result

    if not _has_go_test(file_path):
        stem = file_path.stem
        result.findings.append(
            Finding(
                checker="tdd",
                file=rel,
                line=0,
                severity="warning",
                message=f"No test file found for {file_path.name}. Expected {stem}_test.go",
                rule_id="tdd/missing-test-go",
            )
        )

    return result


check_tdd_go._checker_name = "tdd"  # type: ignore[attr-defined]
