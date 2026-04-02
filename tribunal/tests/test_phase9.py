"""Tests for Phase 9 — VS Code extension support + team dashboard API."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tribunal.dashboard_api import DashboardStore


class TestDashboardStore:
    def test_empty_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            assert store.list_projects() == []
            assert store.get_summary()["project_count"] == 0

    def test_store_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            store.store_report("my-project", {
                "project_name": "My Project",
                "cost": {"session_cost_usd": 1.23, "input_tokens": 5000},
                "audit_entries": [
                    {"ts": "2025-01-01T00:00:00Z", "hook": "PreToolUse", "tool": "Bash", "allowed": True},
                    {"ts": "2025-01-01T00:01:00Z", "hook": "PreToolUse", "tool": "FileEdit", "allowed": False},
                ],
                "agents": {"active_agents": {}, "completed_agents": []},
            })
            projects = store.list_projects()
            assert len(projects) == 1
            assert projects[0]["name"] == "My Project"

    def test_get_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            store.store_report("proj-1", {
                "audit_entries": [
                    {"ts": "2025-01-01", "tool": "Bash", "allowed": True},
                    {"ts": "2025-01-02", "tool": "FileEdit", "allowed": False},
                ],
            })
            audit = store.get_audit("proj-1")
            assert len(audit) == 2
            assert audit[1]["allowed"] is False

    def test_get_cost(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            store.store_report("proj-1", {
                "cost": {"session_cost_usd": 0.5},
            })
            store.store_report("proj-1", {
                "cost": {"session_cost_usd": 1.2},
            })
            cost = store.get_cost("proj-1")
            assert len(cost) == 2
            assert cost[-1]["session_cost_usd"] == 1.2

    def test_get_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            store.store_report("proj-1", {
                "agents": {"active": ["a1"], "completed": ["a2"]},
            })
            agents = store.get_agents("proj-1")
            assert agents["active"] == ["a1"]

    def test_get_agents_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            assert store.get_agents("nonexistent") == {}

    def test_get_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            store.store_report("proj-a", {
                "project_name": "Project A",
                "cost": {"session_cost_usd": 1.0},
                "audit_entries": [
                    {"allowed": True},
                    {"allowed": False},
                ],
            })
            store.store_report("proj-b", {
                "project_name": "Project B",
                "cost": {"session_cost_usd": 2.0},
                "audit_entries": [
                    {"allowed": True},
                ],
            })
            summary = store.get_summary()
            assert summary["project_count"] == 2
            assert summary["total_cost_usd"] == 3.0
            assert summary["total_audit_entries"] == 3
            assert summary["total_blocked"] == 1

    def test_multiple_reports_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            for i in range(5):
                store.store_report("proj-1", {
                    "audit_entries": [{"ts": f"2025-01-0{i+1}", "allowed": True}],
                })
            audit = store.get_audit("proj-1")
            assert len(audit) == 5

    def test_sanitized_project_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DashboardStore(tmpdir)
            # Dangerous characters stripped
            store.store_report("../evil", {"project_name": "Evil"})
            projects = store.list_projects()
            assert len(projects) == 1
            assert ".." not in projects[0]["id"]
