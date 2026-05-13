"""Tests for tribunal.policy.evaluator -- YAML rule packs + event eval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tribunal.policy import evaluator as pol


# -- Constructors ------------------------------------------------------------


def test_rule_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        pol.Rule(id="x", when={}, action="banhammer")


def test_rule_accepts_each_valid_action() -> None:
    for action in pol.VALID_ACTIONS:
        r = pol.Rule(id=f"r-{action}", when={}, action=action)
        assert r.action == action


def test_action_priority_ordering() -> None:
    # deny > ask > warn > allow
    p = pol.ACTION_PRIORITY
    assert p["deny"] > p["ask"] > p["warn"] > p["allow"]


def test_decision_helpers() -> None:
    d = pol.Decision(action="deny", rule_id="x/y", pack="p", message="m")
    assert d.is_block is True
    assert d.should_log is True
    assert pol.Decision(action="allow").is_block is False
    assert pol.Decision(action="allow").should_log is False
    assert pol.Decision(action="warn").should_log is True


# -- load_pack ---------------------------------------------------------------


def test_load_pack_from_mapping() -> None:
    pack = pol.load_pack(
        {
            "name": "test-pack",
            "version": 2,
            "description": "from dict",
            "rules": [
                {"id": "r1", "when": {"event_type": "file.write"}, "action": "deny"},
            ],
        }
    )
    assert pack.name == "test-pack"
    assert pack.version == 2
    assert len(pack.rules) == 1
    assert pack.rules[0].pack == "test-pack"


def test_load_pack_from_yaml_string() -> None:
    yaml_text = """\
name: ystr
version: 1
description: from string
rules:
  - id: r1
    when:
      event_type: bash.executed
    action: warn
    message: caution
"""
    pack = pol.load_pack(yaml_text)
    assert pack.name == "ystr"
    assert pack.rules[0].message == "caution"


def test_load_pack_from_path(tmp_path: Path) -> None:
    p = tmp_path / "pack.yaml"
    p.write_text(
        "name: from-path\nversion: 1\ndescription: ok\nrules:\n"
        "  - id: r1\n    when: {event_type: session.start}\n    action: allow\n",
        encoding="utf-8",
    )
    pack = pol.load_pack(p)
    assert pack.name == "from-path"
    assert pack.rules[0].action == "allow"


def test_load_shipped_packs_finds_three() -> None:
    packs = pol.load_shipped_packs()
    names = {p.name for p in packs}
    assert {"secrets-readonly", "no-prod-writes", "soc2-baseline"}.issubset(names)


# -- evaluate() -- priority semantics -----------------------------------------


def _event(**overrides: Any) -> dict:
    base = {
        "schema_version": "1.0",
        "event_id": "e1",
        "ts": "2026-05-13T00:00:00Z",
        "agent": "claude-code",
        "agent_version": "1.0",
        "session_id": "s1",
        "user_id": "u1",
        "event_type": "file.write",
        "payload": {"path": "/repo/src/foo.py"},
    }
    base.update(overrides)
    return base


def test_evaluate_no_match_returns_allow() -> None:
    pack = pol.load_pack({"name": "p", "version": 1, "description": "", "rules": []})
    d = pol.evaluate(_event(), [pack])
    assert d.action == "allow"
    assert d.rule_id == ""


def test_evaluate_priority_deny_beats_warn() -> None:
    pack = pol.load_pack(
        {
            "name": "p",
            "version": 1,
            "description": "",
            "rules": [
                {"id": "warn1", "when": {"event_type": "file.write"}, "action": "warn"},
                {"id": "deny1", "when": {"event_type": "file.write"}, "action": "deny"},
            ],
        }
    )
    d = pol.evaluate(_event(), [pack])
    assert d.action == "deny"
    assert d.rule_id == "deny1"


def test_evaluate_priority_ask_beats_warn_beats_allow() -> None:
    pack = pol.load_pack(
        {
            "name": "p",
            "version": 1,
            "description": "",
            "rules": [
                {"id": "a", "when": {"event_type": "file.write"}, "action": "allow"},
                {"id": "w", "when": {"event_type": "file.write"}, "action": "warn"},
                {"id": "k", "when": {"event_type": "file.write"}, "action": "ask"},
            ],
        }
    )
    assert pol.evaluate(_event(), [pack]).action == "ask"


def test_evaluate_multiple_packs() -> None:
    pack_a = pol.load_pack(
        {
            "name": "a",
            "version": 1,
            "description": "",
            "rules": [
                {"id": "a1", "when": {"event_type": "file.write"}, "action": "warn"}
            ],
        }
    )
    pack_b = pol.load_pack(
        {
            "name": "b",
            "version": 1,
            "description": "",
            "rules": [
                {"id": "b1", "when": {"event_type": "file.write"}, "action": "deny"}
            ],
        }
    )
    d = pol.evaluate(_event(), [pack_a, pack_b])
    assert d.action == "deny"
    assert d.pack == "b"


# -- Predicates --------------------------------------------------------------


def _pack_with(action: str = "deny", **when: Any) -> pol.PolicyPack:
    return pol.load_pack(
        {
            "name": "test",
            "version": 1,
            "description": "",
            "rules": [{"id": "r1", "when": when, "action": action}],
        }
    )


def test_event_type_list_predicate() -> None:
    pack = _pack_with(action="warn", event_type=["file.write", "file.delete"])
    assert pol.evaluate(_event(event_type="file.write"), [pack]).action == "warn"
    assert pol.evaluate(_event(event_type="file.delete"), [pack]).action == "warn"
    assert pol.evaluate(_event(event_type="session.start"), [pack]).action == "allow"


def test_agent_predicate() -> None:
    pack = _pack_with(action="deny", agent="cursor")
    assert pol.evaluate(_event(agent="cursor"), [pack]).action == "deny"
    assert pol.evaluate(_event(agent="claude-code"), [pack]).action == "allow"


def test_tool_name_predicate() -> None:
    pack = _pack_with(action="ask", event_type="tool.proposed", tool_name="Bash")
    ev = _event(
        event_type="tool.proposed", payload={"tool_name": "Bash", "command": "ls"}
    )
    assert pol.evaluate(ev, [pack]).action == "ask"
    ev2 = _event(event_type="tool.proposed", payload={"tool_name": "Read"})
    assert pol.evaluate(ev2, [pack]).action == "allow"


def test_path_match_predicate_glob() -> None:
    pack = _pack_with(
        action="deny", event_type="file.write", path_match=["**/.env", "**/.env.*"]
    )
    assert pol.evaluate(_event(payload={"path": "/x/.env"}), [pack]).action == "deny"
    assert (
        pol.evaluate(_event(payload={"path": "/x/.env.production"}), [pack]).action
        == "deny"
    )
    assert pol.evaluate(_event(payload={"path": "/x/foo.py"}), [pack]).action == "allow"


def test_path_match_reads_tool_input_file_path() -> None:
    pack = _pack_with(action="deny", path_match="**/secrets/**")
    ev = _event(
        event_type="tool.proposed",
        payload={
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/secrets/k.txt"},
        },
    )
    assert pol.evaluate(ev, [pack]).action == "deny"


def test_command_match_predicate_regex() -> None:
    pack = _pack_with(
        action="deny",
        event_type="bash.executed",
        command_match=[r"\brm\s+-rf\b", r"git\s+push\s+--force"],
    )
    ev = _event(event_type="bash.executed", payload={"command": "rm -rf /tmp/foo"})
    assert pol.evaluate(ev, [pack]).action == "deny"
    ev2 = _event(
        event_type="bash.executed", payload={"command": "git push --force origin main"}
    )
    assert pol.evaluate(ev2, [pack]).action == "deny"
    ev3 = _event(event_type="bash.executed", payload={"command": "ls -la"})
    assert pol.evaluate(ev3, [pack]).action == "allow"


def test_payload_regex_map_all_must_match() -> None:
    pack = _pack_with(
        action="warn",
        event_type="prompt.submitted",
        payload_regex={"prompt": r"deploy", "target": r"prod"},
    )
    ev = _event(
        event_type="prompt.submitted",
        payload={"prompt": "please deploy", "target": "production"},
    )
    assert pol.evaluate(ev, [pack]).action == "warn"
    ev2 = _event(
        event_type="prompt.submitted",
        payload={"prompt": "please deploy", "target": "staging"},
    )
    assert pol.evaluate(ev2, [pack]).action == "allow"


def test_cost_gte_predicate() -> None:
    pack = _pack_with(action="deny", cost_gte=10.0)
    ev = _event(event_type="cost.recorded", cost={"usd": 12.5})
    assert pol.evaluate(ev, [pack]).action == "deny"
    ev2 = _event(event_type="cost.recorded", cost={"usd": 1.0})
    assert pol.evaluate(ev2, [pack]).action == "allow"


def test_unknown_predicate_silently_fails_match() -> None:
    pack = _pack_with(action="deny", event_type="file.write", magic_predicate="nope")
    # Engine should NOT fire the rule when it doesn't understand a predicate.
    assert pol.evaluate(_event(), [pack]).action == "allow"


# -- Shipped packs -- real events ---------------------------------------------


def test_secrets_readonly_blocks_env_write() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(event_type="file.write", payload={"path": "/repo/.env"})
    d = pol.evaluate(ev, packs)
    assert d.action == "deny"
    assert d.pack == "secrets-readonly"


def test_secrets_readonly_blocks_private_key_write() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(event_type="file.write", payload={"path": "/home/u/.ssh/id_rsa"})
    d = pol.evaluate(ev, packs)
    assert d.action == "deny"


def test_no_prod_writes_blocks_force_push() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(
        event_type="tool.proposed",
        payload={"tool_name": "Bash", "command": "git push --force origin main"},
    )
    d = pol.evaluate(ev, packs)
    assert d.action == "deny"
    assert d.pack == "no-prod-writes"


def test_soc2_baseline_warns_on_external_fetch() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(
        event_type="tool.proposed",
        payload={"tool_name": "WebFetch", "tool_input": {"url": "https://x.io"}},
    )
    d = pol.evaluate(ev, packs)
    assert d.action == "warn"
    assert d.pack == "soc2-baseline"


def test_soc2_baseline_denies_sudo() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(
        event_type="tool.proposed",
        payload={"tool_name": "Bash", "command": "sudo rm -rf /var/log"},
    )
    d = pol.evaluate(ev, packs)
    assert d.action == "deny"


def test_soc2_baseline_denies_high_cost_event() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(event_type="cost.recorded", cost={"usd": 75.0})
    d = pol.evaluate(ev, packs)
    assert d.action == "deny"
    assert d.pack == "soc2-baseline"


def test_benign_file_write_passes_all_packs() -> None:
    packs = pol.load_shipped_packs()
    ev = _event(event_type="file.write", payload={"path": "/repo/src/foo.py"})
    d = pol.evaluate(ev, packs)
    assert d.action == "allow"
