"""Tribunal adapters -- translate agent-native events into the unified schema.

Each adapter is a thin translator. Target: 50-150 LOC per adapter. They
import nothing from the rest of tribunal except `tribunal.events.schema`.

Status (v3-pivot/week-1): scaffolding only. Adapters land Weeks 3-6:

    - Week 3: claude_code.py
    - Week 4: cursor.py
    - Week 6: copilot.py, codex.py

See `tribunal/spec/event-schema-v1.json` for the target event shape and
`docs/v3-execution-plan.md` Sec.2.1 for the per-adapter event mapping table.
"""

from __future__ import annotations

__all__ = ["AGENTS"]

#: Agent identifiers recognised by the unified schema. Keep in sync with
#: the ``agent`` enum in ``tribunal/spec/event-schema-v1.json``.
AGENTS = (
    "claude-code",
    "cursor",
    "copilot-cli",
    "codex-cli",
    "other",
)
