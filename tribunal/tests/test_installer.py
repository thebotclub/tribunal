"""Tests for tribunal.installer — Claude Code / Cursor settings injection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tribunal.installer import (
    install_claude_code,
    install_cursor,
    uninstall_claude_code,
)


# ── Claude Code installer ───────────────────────────────────────────────────


def test_install_into_empty_directory_creates_settings(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    report = install_claude_code(settings_path=target)
    assert report.installed is True
    assert target.exists()
    data = json.loads(target.read_text())
    # All Tribunal-relevant hooks should be present
    hooks = data["hooks"]
    for ev in ("PreToolUse", "PostToolUse", "SessionStart", "Stop", "UserPromptSubmit"):
        assert ev in hooks
        first = hooks[ev][0]
        assert "tribunal" in first["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    install_claude_code(settings_path=target)
    second = install_claude_code(settings_path=target)
    assert second.already_installed is True
    assert second.installed is False
    assert second.changes == []


def test_install_preserves_user_hooks(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": "my-own-hook"}],
                        }
                    ]
                },
                "model": "claude-3.5-sonnet",
            }
        )
    )
    install_claude_code(settings_path=target)
    data = json.loads(target.read_text())
    # User's hook is still there
    cmds = [
        h["command"] for entry in data["hooks"]["PreToolUse"] for h in entry["hooks"]
    ]
    assert "my-own-hook" in cmds
    assert any("tribunal" in c for c in cmds)
    # Other user settings preserved
    assert data["model"] == "claude-3.5-sonnet"


def test_dry_run_makes_no_changes(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    report = install_claude_code(settings_path=target, dry_run=True)
    assert report.dry_run is True
    assert report.changes
    assert not target.exists()


def test_install_backs_up_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    target.parent.mkdir()
    target.write_text('{"hooks": {}, "foo": "bar"}')
    report = install_claude_code(settings_path=target)
    assert report.backup_path
    assert Path(report.backup_path).exists()
    assert Path(report.backup_path).read_text().startswith('{"hooks":')


def test_install_rejects_invalid_json(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    target.parent.mkdir()
    target.write_text("{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        install_claude_code(settings_path=target)


def test_uninstall_removes_tribunal_hooks_only(tmp_path: Path) -> None:
    target = tmp_path / "claude" / "settings.json"
    install_claude_code(settings_path=target)
    # Add a user hook
    data = json.loads(target.read_text())
    data["hooks"]["PreToolUse"].append(
        {"matcher": "*", "hooks": [{"type": "command", "command": "my-tool"}]}
    )
    target.write_text(json.dumps(data))
    report = uninstall_claude_code(settings_path=target)
    assert report.installed is True
    data = json.loads(target.read_text())
    remaining = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "my-tool" in remaining
    assert not any("tribunal" in c for c in remaining)


# ── Cursor installer ────────────────────────────────────────────────────────


def test_install_cursor_writes_settings(tmp_path: Path) -> None:
    target = tmp_path / "cursor" / "settings.json"
    report = install_cursor(settings_path=target)
    assert report.installed is True
    data = json.loads(target.read_text())
    assert data["tribunal.daemon.url"] == "http://127.0.0.1:8088"
    assert data["tribunal.audit.command"] == "tribunal adapter cursor"


def test_install_cursor_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "cursor" / "settings.json"
    install_cursor(settings_path=target)
    again = install_cursor(settings_path=target)
    assert again.already_installed is True
