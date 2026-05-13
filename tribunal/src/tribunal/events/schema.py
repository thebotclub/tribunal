"""Schema loader, event builder, and validator for Tribunal events.

The schema is shipped as a static JSON file under ``tribunal/spec/`` so it
can be served unchanged at ``https://tribunal.dev/spec/event-schema-v1.json``
and consumed by third-party adapters.

This module:

1. Loads and caches the schema as a Python dict.
2. Exposes ``new_event(...)`` — a small helper that fills the required
   fields and returns a dict ready to be serialised.
3. Exposes ``validate_event(event)`` — wraps the optional ``jsonschema``
   dependency. If the dependency is missing we fall back to a much
   smaller hand-rolled check so the CLI still runs.

Notes on the optional dependency: ``jsonschema`` is a runtime dep in
``pyproject.toml`` from v3.0.0a1 onward, but the v2.x line did not require
it. We tolerate the missing-import case so that pinning the v3 alpha
against an older lockfile does not break the gate.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

#: The schema version this module knows how to produce. Bumped only on
#: breaking changes (a new file is added under ``tribunal/spec/`` in that
#: case).
SCHEMA_VERSION = "1"


class SchemaError(ValueError):
    """Raised when an event fails schema validation."""


def _spec_path() -> Path:
    """Return the path to the bundled event-schema-v1.json.

    The spec lives in two places depending on the install layout:

    1. ``<repo>/tribunal/spec/event-schema-v1.json`` in a source checkout.
    2. ``<site-packages>/tribunal/spec/event-schema-v1.json`` after
       ``pip install`` (we ``force-include`` it in pyproject.toml).
    """
    here = Path(__file__).resolve()
    candidates = [
        # source checkout: tribunal/src/tribunal/events/schema.py
        #   parents[3] = tribunal/  →  tribunal/spec/event-schema-v1.json
        here.parents[3] / "spec" / "event-schema-v1.json",
        # installed wheel: site-packages/tribunal/events/schema.py
        #   parents[1] = site-packages/tribunal/  →  tribunal/spec/...
        here.parents[1] / "spec" / "event-schema-v1.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Fallback: env var override for unusual install layouts.
    override = os.environ.get("TRIBUNAL_EVENT_SCHEMA_PATH")
    if override and Path(override).exists():
        return Path(override)
    raise FileNotFoundError(
        "Could not locate event-schema-v1.json. "
        f"Looked at: {[str(c) for c in candidates]}. "
        "Set TRIBUNAL_EVENT_SCHEMA_PATH to override."
    )


@lru_cache(maxsize=1)
def load_schema() -> Dict[str, Any]:
    """Load and cache the unified-event JSON Schema."""
    with _spec_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _supported_event_types_tuple() -> tuple[str, ...]:
    return tuple(load_schema()["properties"]["event_type"]["enum"])


def supported_event_types() -> Iterable[str]:
    """Iterable of every event_type the schema declares."""
    return _supported_event_types_tuple()


#: Module-level convenience alias.
SUPPORTED_EVENT_TYPES = _supported_event_types_tuple


def new_event(
    *,
    agent: str,
    agent_version: str,
    session_id: str,
    user_id: str,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    machine_id: str | None = None,
    repo_path: str | None = None,
    repo_remote: str | None = None,
    branch: str | None = None,
    cost: Mapping[str, Any] | None = None,
    policy_decision: str | None = None,
    policy_rule: str | None = None,
    policy_message: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    tags: Mapping[str, str] | None = None,
    event_id: str | None = None,
    ts: str | None = None,
) -> Dict[str, Any]:
    """Build a schema-conformant event dict.

    Required fields get sensible defaults: a fresh UUID for ``event_id`` and
    an ISO-8601 UTC timestamp for ``ts`` if not provided.

    The result is NOT validated automatically — call ``validate_event``
    yourself when you want to assert conformance. Adapters typically
    validate in dev and skip validation in hot paths.
    """
    if event_type not in supported_event_types():
        raise SchemaError(
            f"unknown event_type {event_type!r}; "
            f"valid types: {sorted(supported_event_types())}"
        )

    event: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "ts": ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "agent": agent,
        "agent_version": agent_version,
        "session_id": session_id,
        "user_id": user_id,
        "event_type": event_type,
        "payload": dict(payload) if payload is not None else {},
    }
    # Optional fields — included only when set, to keep the on-the-wire
    # representation tight.
    if machine_id is not None:
        event["machine_id"] = machine_id
    if repo_path is not None:
        event["repo_path"] = repo_path
    if repo_remote is not None:
        event["repo_remote"] = repo_remote
    if branch is not None:
        event["branch"] = branch
    if cost is not None:
        event["cost"] = dict(cost)
    if policy_decision is not None:
        event["policy_decision"] = policy_decision
    if policy_rule is not None:
        event["policy_rule"] = policy_rule
    if policy_message is not None:
        event["policy_message"] = policy_message
    if trace_id is not None:
        event["trace_id"] = trace_id
    if span_id is not None:
        event["span_id"] = span_id
    if tags is not None:
        event["tags"] = dict(tags)
    return event


_REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "schema_version",
    "event_id",
    "ts",
    "agent",
    "agent_version",
    "session_id",
    "user_id",
    "event_type",
)


def validate_event(event: Mapping[str, Any]) -> None:
    """Validate ``event`` against the unified schema.

    Raises :class:`SchemaError` on the first failure. When the optional
    ``jsonschema`` package is installed, we use full Draft-2020-12
    validation. Otherwise we fall back to a minimal contract check
    (required fields + enums) that is still useful for adapters.
    """
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        _validate_event_minimal(event)
        return

    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(event), key=lambda e: e.path)
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise SchemaError(f"event invalid at {path}: {first.message}")


def _validate_event_minimal(event: Mapping[str, Any]) -> None:
    """Fallback validator used when jsonschema is unavailable.

    This is intentionally narrow: it catches the mistakes adapter authors
    actually make (missing required field, unknown ``event_type``,
    unknown ``agent``). Full structural validation only runs with
    jsonschema installed.
    """
    if not isinstance(event, Mapping):
        raise SchemaError(f"event must be a mapping, got {type(event).__name__}")

    for field in _REQUIRED_TOP_LEVEL:
        if field not in event:
            raise SchemaError(f"missing required field: {field}")

    schema = load_schema()
    agent_enum = schema["properties"]["agent"]["enum"]
    if event["agent"] not in agent_enum:
        raise SchemaError(f"unknown agent {event['agent']!r}; valid: {agent_enum}")
    if event["agent"] == "other" and not event.get("agent_name"):
        raise SchemaError("agent='other' requires agent_name to be set")

    if event["event_type"] not in supported_event_types():
        raise SchemaError(
            f"unknown event_type {event['event_type']!r}; "
            f"valid: {sorted(supported_event_types())}"
        )

    if event["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {event['schema_version']!r}; "
            f"this build only emits/accepts {SCHEMA_VERSION!r}"
        )
