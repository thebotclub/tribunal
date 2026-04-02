"""Secret detection checker — finds hardcoded credentials in source files.

Scans file content against known secret patterns (AWS keys, API tokens,
private keys, database URLs, etc.). Supports .secretsignore for
project-specific exclusions.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import CheckResult, Finding, register_global

# ── Patterns ──────────────────────────────────────────────────────────────────

SECRET_PATTERNS: list[tuple[str, str]] = [
    # AWS
    (r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}", "secrets/aws-access-key"),
    # GitHub
    (r"gh[ps]_[A-Za-z0-9_]{36,}", "secrets/github-token"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "secrets/github-pat"),
    # Anthropic
    (r"sk-ant-api03-[A-Za-z0-9\-_]{90,}", "secrets/anthropic-key"),
    # OpenAI
    (r"sk-[A-Za-z0-9]{40,}", "secrets/openai-key"),
    # Slack
    (r"xox[bpors]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}", "secrets/slack-token"),
    # Private keys
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "secrets/private-key"),
    # Database URLs with credentials
    (
        r"(?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^\s:]+:[^\s@]+@[^\s]+",
        "secrets/database-url",
    ),
    # JWT
    (r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "secrets/jwt"),
    # Bearer tokens
    (r'["\']Bearer\s+[A-Za-z0-9\-_.~+/]{20,}["\']', "secrets/bearer-token"),
    # Generic API key assignments
    (
        r'(?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key)\s*[=:]\s*["\'][A-Za-z0-9+/=\-_]{16,}["\']',
        "secrets/generic-api-key",
    ),
    # Generic high-entropy hex strings (40+ chars, assigned to suspicious variable)
    (
        r'(?:password|passwd|secret|token|credential)\s*[=:]\s*["\'][A-Fa-f0-9]{40,}["\']',
        "secrets/generic-hex-secret",
    ),
]

_COMPILED_PATTERNS = [(re.compile(pat), rule_id) for pat, rule_id in SECRET_PATTERNS]

# ── Skip lists ────────────────────────────────────────────────────────────────

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2",
    ".lock", ".sum",
    ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".min.js", ".min.css",
    ".map",
    ".pdf", ".doc", ".docx",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "go.sum",
}

# ── Placeholder detection ─────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(
    r"your[-_]?(api[-_]?key|token|secret|password)"
    r"|<[A-Z_]+>"
    r"|xxx+"
    r"|^placeholder$"
    r"|\bchangeme\b"
    r"|^REPLACE[-_]?ME$"
    r"|^test[-_]?key"
    r"|^dummy[-_]"
    r"|\.\.\.",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Check if a matched value looks like a placeholder, not a real secret."""
    return bool(_PLACEHOLDER_RE.search(value))


# ── .secretsignore ────────────────────────────────────────────────────────────


def _load_secretsignore(project_root: Path) -> list[re.Pattern[str]]:
    """Load .secretsignore patterns from project root."""
    ignore_file = project_root / ".secretsignore"
    if not ignore_file.is_file():
        return []

    patterns: list[re.Pattern[str]] = []
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line))
        except re.error:
            continue
    return patterns


def _is_ignored(text: str, patterns: list[re.Pattern[str]]) -> bool:
    """Check if text matches any secretsignore pattern."""
    return any(p.search(text) for p in patterns)


# ── Checker ───────────────────────────────────────────────────────────────────


@register_global
def check_secrets(file_path: Path, project_root: Path) -> CheckResult:
    """Scan a file for hardcoded secrets and credentials."""
    rel = str(file_path.relative_to(project_root)) if file_path.is_relative_to(project_root) else str(file_path)
    result = CheckResult(checker="secrets", file=rel)

    # Skip binary/non-source files
    if file_path.suffix in SKIP_EXTENSIONS:
        return result
    if file_path.name in SKIP_FILENAMES:
        return result

    try:
        content = file_path.read_text(errors="replace")
    except OSError:
        return result

    ignore_patterns = _load_secretsignore(project_root)

    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern, rule_id in _COMPILED_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue

            matched_text = match.group(0)

            # Skip placeholders
            if _is_placeholder(matched_text):
                continue

            # Skip secretsignore matches
            if _is_ignored(line, ignore_patterns):
                continue

            result.findings.append(
                Finding(
                    checker="secrets",
                    file=rel,
                    line=line_num,
                    severity="error",
                    message=f"Possible secret detected: {rule_id.split('/')[-1]}",
                    rule_id=rule_id,
                )
            )
            break  # One finding per line is enough

    return result


check_secrets._checker_name = "secrets"  # type: ignore[attr-defined]
