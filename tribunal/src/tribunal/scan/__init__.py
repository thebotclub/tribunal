"""Tribunal scan — the v2 quality-gate checkers, demoted to a subcommand.

In v3, the headline product is governance (audit + policy + spend). The
v2 scanners (secrets, TDD, ruff, eslint, tsc, go vet) keep working and
ship under ``tribunal scan`` — same code, just relocated.

Week-1 status: package exists; the actual move from ``tribunal.checkers``
happens Week 2 of the v3 execution plan. Until then, ``tribunal.checkers``
remains the canonical import path.
"""

from __future__ import annotations

__all__: list[str] = []
