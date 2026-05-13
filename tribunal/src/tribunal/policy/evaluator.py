"""Policy engine — evaluate unified events against YAML rule packs.

A policy pack is a YAML document::

    name: secrets-readonly
    version: 1
    description: Deny writes to anything that looks like a secret.
    rules:
      - id: secrets/no-env-write
        when:
          event_type: file.write
          path_match: ['**/.env', '**/.env.*', '**/secrets/**']
        action: deny
        message: Writing secrets through an AI agent is blocked by policy.

Match grammar
-------------

Each rule has a ``when`` block of *predicates* that all must match for
the rule to fire (logical AND). Supported predicates:

  - ``event_type``        — exact event_type, or list of types
  - ``agent``             — exact agent id, or list
  - ``tool_name``         — for tool.* events; exact match or list
  - ``path_match``        — fnmatch globs against payload.path or
                            tool_input.file_path
  - ``command_match``     — regex against payload.command (bash)
  - ``payload_regex``     — {field: pattern} regex map
  - ``cost_gte``          — float, matches cost.usd >= value

Action types
------------

  - ``allow`` — explicit pass; useful for overriding broader denies
  - ``warn``  — log + show in UI but don't block
  - ``ask``   — surface to the user (interactive agent)
  - ``deny``  — hard block

When multiple rules match the same event, ``deny`` wins, then ``ask``,
then ``warn``, then ``allow``.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

# We accept either real PyYAML or a tiny built-in fallback when PyYAML is
# absent (pyyaml IS a runtime dep but the engine should not crash on
# air-gapped installs where YAML loading is monkeypatched).
try:
    import yaml as _yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


# ── Public data ──────────────────────────────────────────────────────────────


ACTION_PRIORITY = {"deny": 4, "ask": 3, "warn": 2, "allow": 1}
VALID_ACTIONS = frozenset(ACTION_PRIORITY)


@dataclass
class Rule:
    id: str
    when: dict[str, Any]
    action: str
    message: str = ""
    pack: str = ""

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"unknown action {self.action!r}; valid: {sorted(VALID_ACTIONS)}")


@dataclass
class PolicyPack:
    name: str
    version: int
    description: str
    rules: list[Rule] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # one of VALID_ACTIONS
    rule_id: str = ""
    pack: str = ""
    message: str = ""

    @property
    def is_block(self) -> bool:
        return self.action == "deny"

    @property
    def should_log(self) -> bool:
        return self.action != "allow"


# ── Pack loading ─────────────────────────────────────────────────────────────


def load_pack(source: Path | str | Mapping[str, Any]) -> PolicyPack:
    """Load a pack from a YAML path, raw YAML string, or pre-parsed dict."""
    if isinstance(source, Mapping):
        data = dict(source)
    elif isinstance(source, Path):
        if _yaml is None:
            raise RuntimeError("pyyaml is required to load policy packs from disk")
        data = _yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    else:
        if _yaml is None:
            raise RuntimeError("pyyaml is required to parse YAML strings")
        data = _yaml.safe_load(source) or {}

    name = str(data.get("name") or "unnamed")
    rules = [
        Rule(
            id=str(r["id"]),
            when=dict(r.get("when") or {}),
            action=str(r.get("action", "allow")),
            message=str(r.get("message", "")),
            pack=name,
        )
        for r in data.get("rules", [])
    ]
    return PolicyPack(
        name=name,
        version=int(data.get("version", 1)),
        description=str(data.get("description", "")),
        rules=rules,
    )


def load_shipped_packs() -> list[PolicyPack]:
    """Load every pack bundled inside ``tribunal/policy/packs/*.yaml``."""
    packs: list[PolicyPack] = []
    try:
        root = resources.files("tribunal.policy.packs")
    except (ModuleNotFoundError, AttributeError):  # pragma: no cover
        return packs
    for entry in root.iterdir():  # type: ignore[union-attr]
        name = getattr(entry, "name", "")
        if not name.endswith(".yaml"):
            continue
        text = entry.read_text(encoding="utf-8")
        packs.append(load_pack(text))
    return packs


# ── Evaluation ───────────────────────────────────────────────────────────────


def evaluate(event: Mapping[str, Any], packs: Sequence[PolicyPack]) -> Decision:
    """Evaluate an event against every rule in every pack. Most-severe wins."""
    best: Optional[tuple[int, Rule]] = None
    for pack in packs:
        for rule in pack.rules:
            if _matches(event, rule.when):
                priority = ACTION_PRIORITY[rule.action]
                if best is None or priority > best[0]:
                    best = (priority, rule)
    if best is None:
        return Decision(action="allow")
    _, rule = best
    return Decision(
        action=rule.action,
        rule_id=rule.id,
        pack=rule.pack,
        message=rule.message,
    )


# ── Predicates ───────────────────────────────────────────────────────────────


def _matches(event: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    for key, expected in when.items():
        if not _check_predicate(event, key, expected):
            return False
    return True


def _check_predicate(event: Mapping[str, Any], key: str, expected: Any) -> bool:
    if key == "event_type":
        return _in(event.get("event_type"), expected)
    if key == "agent":
        return _in(event.get("agent"), expected)
    if key == "tool_name":
        return _in(_dig(event, "payload.tool_name"), expected)
    if key == "path_match":
        path = _dig(event, "payload.path") or _dig(event, "payload.tool_input.file_path") or ""
        return _glob_any(path, expected)
    if key == "command_match":
        cmd = _dig(event, "payload.command") or _dig(event, "payload.tool_input.command") or ""
        return _regex_any(cmd, expected)
    if key == "payload_regex":
        if not isinstance(expected, Mapping):
            return False
        for field_name, pattern in expected.items():
            value = _dig(event, f"payload.{field_name}") or ""
            if not re.search(str(pattern), str(value)):
                return False
        return True
    if key == "cost_gte":
        try:
            return float(_dig(event, "cost.usd") or 0) >= float(expected)
        except (TypeError, ValueError):
            return False
    # Unknown predicate: be conservative and treat as no-match so rules
    # written for a newer engine don't fire on this build.
    return False


def _dig(d: Mapping[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            return None
    return cur


def _in(value: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return value in expected
    return value == expected


def _glob_any(value: str, patterns: Any) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(fnmatch.fnmatch(value, p) for p in patterns)


def _regex_any(value: str, patterns: Any) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(re.search(p, value) for p in patterns)


__all__ = [
    "ACTION_PRIORITY",
    "VALID_ACTIONS",
    "Rule",
    "PolicyPack",
    "Decision",
    "load_pack",
    "load_shipped_packs",
    "evaluate",
]
