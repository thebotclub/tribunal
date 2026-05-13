"""Prompt-injection detector — pure heuristics, no model calls.

Real prompt injection defense needs an LLM, but ~80% of the obvious
public cases use the same handful of patterns: "ignore previous
instructions", suspicious markdown comment payloads, hidden Unicode
characters that re-write the prompt, etc. We catch those statically and
emit an ``injection.suspected`` event the policy engine can act on.

False-positive rate is moderate — the design point is "warn the user,
don't block silently". The dashboard surfaces these so a reviewer can
confirm/dismiss.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


# Public-facing dataclass


@dataclass
class InjectionFinding:
    suspected: bool
    rule_id: str = ""
    severity: str = "low"  # low | medium | high
    message: str = ""
    snippet: str = ""


# ── Rule definitions ─────────────────────────────────────────────────────────

# Each rule: (id, severity, message, compiled_regex_or_predicate)
_RULES: list[tuple[str, str, str, re.Pattern[str]]] = [
    (
        "injection/ignore-previous",
        "high",
        "Text asks the model to ignore previous instructions.",
        re.compile(
            r"\b(ignore|forget|disregard)\s+(all\s+)?(previous|prior|earlier|above)\s+"
            r"(instructions?|prompts?|rules?|context)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "injection/system-override",
        "high",
        "Text claims a new system prompt or developer message.",
        re.compile(
            r"(?:^|[\s\.\,\!\:])\s*(new\s+)?(system\s+prompt|developer\s+message|"
            r"act\s+as|you\s+are\s+now\s+|new\s+role)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "injection/exfiltrate",
        "high",
        "Text asks the agent to send data to an external URL.",
        re.compile(
            r"\b(send|post|upload|exfiltrate|leak|email)\b[^\n]{0,80}"
            r"(api[-_ ]?key|secret|token|credentials?|password|env)",
            re.IGNORECASE,
        ),
    ),
    (
        "injection/jailbreak-marker",
        "medium",
        "Text contains a known jailbreak marker.",
        re.compile(
            r"\b(DAN\s+mode|do\s+anything\s+now|jailbreak|developer\s+mode\s+enabled|"
            r"unfiltered\s+mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "injection/hidden-instruction",
        "medium",
        "Text contains HTML / markdown comments with imperative verbs.",
        re.compile(
            r"<!--[^>]*\b(run|execute|call|fetch|post|send|delete|drop)\b[^>]*-->",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "injection/base64-payload",
        "low",
        "Suspicious base64 blob — common exfiltration container.",
        re.compile(r"(?:[A-Za-z0-9+/]{120,}={0,2})"),
    ),
]


_BIDI_CHARS = frozenset(
    {
        "\u202a",  # LRE
        "\u202b",  # RLE
        "\u202c",  # PDF
        "\u202d",  # LRO
        "\u202e",  # RLO
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
    }
)


# ── Public API ──────────────────────────────────────────────────────────────


def scan(text: str) -> InjectionFinding:
    """Return the *highest-severity* finding for ``text``.

    Empty or non-string input returns a no-op finding.
    """
    if not isinstance(text, str) or not text.strip():
        return InjectionFinding(suspected=False)

    # Bidi-override attack
    if any(c in _BIDI_CHARS for c in text):
        idx = next(i for i, c in enumerate(text) if c in _BIDI_CHARS)
        return InjectionFinding(
            suspected=True,
            rule_id="injection/bidi-override",
            severity="high",
            message="Bidirectional-text override character detected (trojan source).",
            snippet=_snippet(text, idx),
        )

    # Invisible / zero-width characters used to smuggle instructions
    zw_chars = sum(
        1 for c in text if c in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff")
    )
    if zw_chars > 4:
        return InjectionFinding(
            suspected=True,
            rule_id="injection/zero-width",
            severity="medium",
            message=f"{zw_chars} zero-width characters detected.",
            snippet=text[:200],
        )

    # Regex rules — first by severity (high before low), first match wins.
    severity_order = {"high": 3, "medium": 2, "low": 1}
    rules_sorted = sorted(_RULES, key=lambda r: -severity_order[r[1]])
    for rule_id, severity, message, pattern in rules_sorted:
        m = pattern.search(text)
        if m:
            return InjectionFinding(
                suspected=True,
                rule_id=rule_id,
                severity=severity,
                message=message,
                snippet=_snippet(text, m.start()),
            )

    return InjectionFinding(suspected=False)


def scan_event(event: Mapping[str, object]) -> InjectionFinding:
    """Run :func:`scan` over the user-controlled bits of a unified event.

    Currently checks:
      - prompt.submitted        → payload.prompt
      - tool.proposed (Bash)    → payload.command
      - tool.executed (Read)    → payload.tool_response (when string)

    The intent is "things the agent saw that could carry injection".
    """
    event_type = event.get("event_type")
    payload = event.get("payload") or {}
    if not isinstance(payload, Mapping):
        return InjectionFinding(suspected=False)

    candidate_texts: list[str] = []
    if event_type == "prompt.submitted":
        candidate_texts.append(str(payload.get("prompt") or ""))
    elif event_type == "tool.proposed":
        candidate_texts.append(str(payload.get("command") or ""))
        tool_input = payload.get("tool_input") or {}
        if isinstance(tool_input, Mapping):
            for v in tool_input.values():
                if isinstance(v, str):
                    candidate_texts.append(v)
    elif event_type == "tool.executed":
        resp = payload.get("tool_response")
        if isinstance(resp, str):
            candidate_texts.append(resp)
        elif isinstance(resp, Mapping):
            for v in resp.values():
                if isinstance(v, str):
                    candidate_texts.append(v)
    elif event_type == "file.read":
        # We don't have the contents, only the path; skip.
        pass

    for text in candidate_texts:
        finding = scan(text)
        if finding.suspected:
            return finding
    return InjectionFinding(suspected=False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _snippet(text: str, idx: int, width: int = 80) -> str:
    start = max(0, idx - width // 2)
    end = min(len(text), idx + width // 2)
    return text[start:end]


__all__ = ["InjectionFinding", "scan", "scan_event"]
