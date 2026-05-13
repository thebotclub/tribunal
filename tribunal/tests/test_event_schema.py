"""Tests for tribunal.events.schema -- the v3 unified event helpers.

These tests assert the things adapter authors will actually rely on:

1. The schema file ships with the package and parses as valid JSON.
2. ``new_event`` produces something that ``validate_event`` accepts.
3. ``validate_event`` rejects obviously-wrong events in both the
   jsonschema-installed and the fallback paths.

Run with ``pytest tests/test_event_schema.py``.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest

from tribunal.events.schema import (
    SCHEMA_VERSION,
    SchemaError,
    _validate_event_minimal,
    load_schema,
    new_event,
    supported_event_types,
    validate_event,
)


# -- Schema loading -----------------------------------------------------------


class TestSchemaShape:
    def test_loads_valid_json(self):
        schema = load_schema()
        assert isinstance(schema, dict)
        assert schema["$id"] == "https://tribunal.dev/spec/event-schema-v1.json"

    def test_required_fields_match_module_constant(self):
        schema = load_schema()
        required = set(schema["required"])
        # schema_version is added by this module -- must be in required too
        assert "schema_version" in required
        assert "event_id" in required
        assert "event_type" in required

    def test_all_payload_defs_match_event_types(self):
        schema = load_schema()
        types = set(schema["properties"]["event_type"]["enum"])
        payload_defs = set(schema["$defs"]["payloads"].keys())
        # Every event_type SHOULD have a payload definition for adapter authors
        missing = types - payload_defs
        assert not missing, f"event types missing payload defs: {missing}"

    def test_bundled_examples_validate(self):
        schema = load_schema()
        try:
            import jsonschema  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("jsonschema not installed")
        validator = jsonschema.Draft202012Validator(schema)
        for name, example in schema["$defs"]["examples"].items():
            errs = list(validator.iter_errors(example))
            assert not errs, f"example {name} failed: {errs[0].message if errs else ''}"


# -- new_event() --------------------------------------------------------------


class TestNewEvent:
    def _kwargs(self, **overrides):
        base = dict(
            agent="claude-code",
            agent_version="1.0.0",
            session_id="s1",
            user_id="u1",
            event_type="prompt.submitted",
            payload={"prompt_hash": "a" * 64},
        )
        base.update(overrides)
        return base

    def test_minimum_required_fields(self):
        ev = new_event(**self._kwargs())
        assert ev["schema_version"] == SCHEMA_VERSION
        # event_id is a valid uuid
        uuid.UUID(ev["event_id"])
        # ts is RFC3339-ish
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", ev["ts"])
        assert ev["agent"] == "claude-code"

    def test_unknown_event_type_rejected(self):
        with pytest.raises(SchemaError):
            new_event(**self._kwargs(event_type="totally.fake"))

    def test_optional_fields_omitted_when_unset(self):
        ev = new_event(**self._kwargs())
        # Cost, policy_decision, trace_id etc must not appear unless set
        assert "cost" not in ev
        assert "policy_decision" not in ev
        assert "machine_id" not in ev

    def test_optional_fields_included_when_set(self):
        ev = new_event(
            **self._kwargs(
                machine_id="m1",
                cost={"input_tokens": 100, "model": "claude-opus-4-6", "usd": 0.05},
                tags={"team": "platform"},
            )
        )
        assert ev["machine_id"] == "m1"
        assert ev["cost"]["usd"] == 0.05
        assert ev["tags"] == {"team": "platform"}


# -- validate_event() ---------------------------------------------------------


def _good_event() -> dict:
    return new_event(
        agent="cursor",
        agent_version="0.45.2",
        session_id="cursor_42",
        user_id="hashed_user",
        event_type="tool.proposed",
        payload={"tool_name": "Bash", "tool_input": {"command": "ls"}},
    )


class TestValidateEvent:
    def test_good_event_passes(self):
        validate_event(_good_event())  # must not raise

    def test_missing_required_field_fails(self):
        bad = _good_event()
        del bad["agent_version"]
        with pytest.raises(SchemaError):
            validate_event(bad)

    def test_unknown_agent_fails(self):
        bad = _good_event()
        bad["agent"] = "skynet"
        with pytest.raises(SchemaError):
            validate_event(bad)

    def test_other_agent_requires_agent_name(self):
        bad = _good_event()
        bad["agent"] = "other"
        with pytest.raises(SchemaError):
            validate_event(bad)

    def test_wrong_schema_version_fails(self):
        bad = _good_event()
        bad["schema_version"] = "999"
        with pytest.raises(SchemaError):
            validate_event(bad)


class TestValidateEventMinimalFallback:
    """Exercise the dependency-free fallback path directly."""

    def test_good_event_passes(self):
        _validate_event_minimal(_good_event())

    def test_non_mapping_rejected(self):
        with pytest.raises(SchemaError):
            _validate_event_minimal(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_missing_event_id_rejected(self):
        bad = _good_event()
        del bad["event_id"]
        with pytest.raises(SchemaError):
            _validate_event_minimal(bad)


# -- Module export sanity -----------------------------------------------------


class TestExports:
    def test_supported_event_types_contains_known_set(self):
        types = set(supported_event_types())
        # A few representative types we know exist
        assert "session.start" in types
        assert "tool.proposed" in types
        assert "policy.block" in types
        assert "cost.recorded" in types

    def test_schema_serialisable(self):
        # The loaded schema must round-trip through json
        s = load_schema()
        assert json.loads(json.dumps(s))["$id"]
