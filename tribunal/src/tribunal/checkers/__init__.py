"""Tribunal checkers — language-aware quality gates for AI-generated code.

Each checker analyzes files and returns structured findings.
Checkers are registered by file extension and run via run_checkers().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Finding:
    """A single issue found by a checker."""

    checker: str  # e.g. "secrets", "python", "tdd"
    file: str  # relative file path
    line: int  # 1-based line number (0 if file-level)
    severity: str  # "error", "warning", "info"
    message: str  # human-readable description
    rule_id: str  # machine-readable ID, e.g. "secrets/aws-key"


@dataclass
class CheckResult:
    """Aggregated result from a single checker on a single file."""

    checker: str
    file: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)


# Type for checker functions: (file_path, project_root) -> CheckResult
CheckerFunc = Callable[[Path, Path], CheckResult]

# Registry: file extension -> list of checker functions
_REGISTRY: dict[str, list[CheckerFunc]] = {}

# Global checkers run on all files regardless of extension
_GLOBAL_CHECKERS: list[CheckerFunc] = []


def register(extensions: list[str]) -> Callable[[CheckerFunc], CheckerFunc]:
    """Decorator to register a checker for given file extensions."""

    def decorator(func: CheckerFunc) -> CheckerFunc:
        for ext in extensions:
            _REGISTRY.setdefault(ext, []).append(func)
        return func

    return decorator


def register_global(func: CheckerFunc) -> CheckerFunc:
    """Decorator to register a checker that runs on all files."""
    _GLOBAL_CHECKERS.append(func)
    return func


def run_checkers(
    files: list[Path],
    project_root: Path,
    *,
    checkers: list[str] | None = None,
) -> list[CheckResult]:
    """Run all applicable checkers on a list of files.

    Args:
        files: Files to check.
        project_root: Project root directory.
        checkers: Optional list of checker names to run. None = all.

    Returns:
        List of CheckResult objects.
    """
    # Force registration of all checker modules
    from . import go as _go, python as _python, secrets as _secrets, tdd as _tdd, typescript as _typescript  # noqa: F401

    results: list[CheckResult] = []

    for file_path in files:
        if not file_path.is_file():
            continue

        ext = file_path.suffix
        applicable: list[CheckerFunc] = list(_GLOBAL_CHECKERS)
        applicable.extend(_REGISTRY.get(ext, []))

        for checker_fn in applicable:
            checker_name = getattr(checker_fn, "_checker_name", checker_fn.__name__)
            if checkers and checker_name not in checkers:
                continue
            result = checker_fn(file_path, project_root)
            results.append(result)

    return results


def collect_files(
    project_root: Path,
    *,
    paths: list[Path] | None = None,
) -> list[Path]:
    """Collect files to check.

    If paths are given, return those. Otherwise walk project_root,
    skipping common non-source directories.
    """
    if paths:
        resolved = []
        for p in paths:
            full = p if p.is_absolute() else project_root / p
            if full.is_file():
                resolved.append(full)
            elif full.is_dir():
                resolved.extend(_walk_dir(full))
        return resolved

    return _walk_dir(project_root)


_SKIP_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "egg-info",
    "_archive",
}

_SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".mts",
    ".go",
}


def _walk_dir(directory: Path) -> list[Path]:
    """Walk a directory tree, returning source files."""
    files: list[Path] = []
    for item in sorted(directory.rglob("*")):
        if any(part in _SKIP_DIRS for part in item.parts):
            continue
        if item.is_file() and item.suffix in _SOURCE_EXTENSIONS:
            files.append(item)
    return files
