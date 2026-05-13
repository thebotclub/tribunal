"""Tribunal policy engine — evaluate unified events against YAML rules.

Status (v3-pivot/week-1): scaffolding only. The real engine lands in
Week 5 of the v3 execution plan (see ``docs/v3-execution-plan.md`` §4 W5).

The engine here will sit next to (and eventually replace) the legacy
``tribunal.rules`` module. The legacy module stays in place during the
3.0.x line for backward compatibility with v2 hook rules.

Planned modules:

- ``evaluator``: load YAML policy packs, evaluate one event against them,
  return a decision (allow / ask / deny / warn).
- ``packs/``: ships at least three first-party packs:

  - ``secrets-readonly.yaml``    — deny writes to ``**/secret*``, ``**/.env*``
  - ``no-prod-writes.yaml``      — deny writes when repo or branch matches prod patterns
  - ``soc2-baseline.yaml``       — log everything, retain 365d, block destructive bash
"""

from __future__ import annotations

__all__: list[str] = []
