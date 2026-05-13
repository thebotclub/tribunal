"""Tribunal unified event types — schema validation and local/cloud storage.

This package owns the canonical event format. The JSON Schema lives at
``tribunal/spec/event-schema-v1.json``. Everything in this package treats
that file as source of truth.

Modules:

- ``schema``: load the JSON Schema, build event dicts, validate them.
- ``store`` (lands Week 7): SQLite local queue + R2 upload helpers.
- ``stream`` (lands Week 7): batched cloud upload with offline persistence.
"""

from __future__ import annotations

from tribunal.events.schema import (
    SCHEMA_VERSION,
    SUPPORTED_EVENT_TYPES,
    SchemaError,
    load_schema,
    new_event,
    validate_event,
)

__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_EVENT_TYPES",
    "SchemaError",
    "load_schema",
    "new_event",
    "validate_event",
]
