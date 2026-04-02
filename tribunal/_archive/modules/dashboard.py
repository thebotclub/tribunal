"""Audit dashboard — generate HTML reports from audit logs.

Provides a static HTML report that can be viewed in a browser,
containing audit event stats, timeline, and rule enforcement data.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AuditStats:
    """Aggregated stats from audit log."""

    total_events: int = 0
    allowed: int = 0
    blocked: int = 0
    by_hook: dict[str, int] = field(default_factory=dict)
    by_tool: dict[str, int] = field(default_factory=dict)
    by_rule: dict[str, int] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)


def load_audit_events(cwd: str) -> list[dict[str, Any]]:
    """Load all audit events from the JSONL log."""
    audit_path = Path(cwd) / ".tribunal" / "audit.jsonl"
    if not audit_path.is_file():
        return []

    events = []
    for line in audit_path.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def compute_stats(events: list[dict[str, Any]]) -> AuditStats:
    """Compute aggregate statistics from audit events."""
    stats = AuditStats()
    stats.total_events = len(events)

    hook_counter: Counter[str] = Counter()
    tool_counter: Counter[str] = Counter()
    rule_counter: Counter[str] = Counter()

    for ev in events:
        if ev.get("allowed"):
            stats.allowed += 1
        else:
            stats.blocked += 1

        hook = ev.get("hook", "unknown")
        hook_counter[hook] += 1

        tool = ev.get("tool", "")
        if tool:
            tool_counter[tool] += 1

        rule = ev.get("rule", "")
        if rule:
            rule_counter[rule] += 1

        stats.timeline.append(
            {
                "ts": ev.get("ts", ""),
                "hook": hook,
                "tool": tool,
                "allowed": ev.get("allowed", True),
                "rule": rule,
            }
        )

    stats.by_hook = dict(hook_counter.most_common())
    stats.by_tool = dict(tool_counter.most_common(20))
    stats.by_rule = dict(rule_counter.most_common(20))

    return stats


def format_stats(stats: AuditStats) -> str:
    """Format audit stats for terminal display."""
    lines = ["\n  ⚖  Tribunal Audit Dashboard\n"]

    lines.append(f"  Total events: {stats.total_events}")
    lines.append(f"  Allowed:      {stats.allowed}")
    lines.append(f"  Blocked:      {stats.blocked}")

    if stats.total_events > 0:
        rate = stats.blocked / stats.total_events * 100
        lines.append(f"  Block rate:   {rate:.1f}%")

    if stats.by_hook:
        lines.append("\n  By hook type:")
        for hook, count in stats.by_hook.items():
            lines.append(f"    {hook}: {count}")

    if stats.by_tool:
        lines.append("\n  Top tools:")
        for tool, count in list(stats.by_tool.items())[:10]:
            lines.append(f"    {tool}: {count}")

    if stats.by_rule:
        lines.append("\n  Top rules triggered:")
        for rule, count in list(stats.by_rule.items())[:10]:
            lines.append(f"    {rule}: {count}")

    lines.append("")
    return "\n".join(lines)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tribunal Audit Report</title>
<style>
  :root { --bg: #0d1117; --fg: #c9d1d9; --accent: #58a6ff;
          --green: #3fb950; --red: #f85149; --border: #30363d; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--fg); padding: 2rem; }
  h1 { color: var(--accent); margin-bottom: 0.5rem; }
  .subtitle { color: #8b949e; margin-bottom: 2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1rem; margin-bottom: 2rem; }
  .card { background: #161b22; border: 1px solid var(--border);
          border-radius: 8px; padding: 1.5rem; }
  .card h3 { color: #8b949e; font-size: 0.85rem; text-transform: uppercase; }
  .card .value { font-size: 2rem; font-weight: bold; margin-top: 0.5rem; }
  .allowed { color: var(--green); }
  .blocked { color: var(--red); }
  table { width: 100%%; border-collapse: collapse; margin-top: 1rem; }
  th, td { padding: 0.5rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: #8b949e; font-size: 0.85rem; text-transform: uppercase; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
           font-size: 0.75rem; font-weight: bold; }
  .badge-allow { background: #0d2818; color: var(--green); }
  .badge-block { background: #2d1014; color: var(--red); }
  section { margin-bottom: 2rem; }
</style>
</head>
<body>
<h1>⚖ Tribunal Audit Report</h1>
<p class="subtitle">Generated %(generated)s</p>

<div class="grid">
  <div class="card">
    <h3>Total Events</h3>
    <div class="value">%(total)d</div>
  </div>
  <div class="card">
    <h3>Allowed</h3>
    <div class="value allowed">%(allowed)d</div>
  </div>
  <div class="card">
    <h3>Blocked</h3>
    <div class="value blocked">%(blocked)d</div>
  </div>
  <div class="card">
    <h3>Block Rate</h3>
    <div class="value">%(block_rate)s</div>
  </div>
</div>

<section>
<h2>Hook Types</h2>
<table>
<tr><th>Hook</th><th>Count</th></tr>
%(hook_rows)s
</table>
</section>

<section>
<h2>Top Tools</h2>
<table>
<tr><th>Tool</th><th>Count</th></tr>
%(tool_rows)s
</table>
</section>

<section>
<h2>Rules Triggered</h2>
<table>
<tr><th>Rule</th><th>Count</th></tr>
%(rule_rows)s
</table>
</section>

<section>
<h2>Recent Events</h2>
<table>
<tr><th>Time</th><th>Hook</th><th>Tool</th><th>Status</th><th>Rule</th></tr>
%(event_rows)s
</table>
</section>

</body>
</html>
"""


def _escape(s: str) -> str:
    """Escape HTML special characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html_report(cwd: str) -> str:
    """Generate an HTML audit report. Returns HTML string."""
    events = load_audit_events(cwd)
    stats = compute_stats(events)

    block_rate = (
        f"{stats.blocked / stats.total_events * 100:.1f}%"
        if stats.total_events > 0
        else "N/A"
    )

    hook_rows = "\n".join(
        f"<tr><td>{_escape(h)}</td><td>{c}</td></tr>"
        for h, c in stats.by_hook.items()
    )
    tool_rows = "\n".join(
        f"<tr><td>{_escape(t)}</td><td>{c}</td></tr>"
        for t, c in list(stats.by_tool.items())[:10]
    )
    rule_rows = "\n".join(
        f"<tr><td>{_escape(r)}</td><td>{c}</td></tr>"
        for r, c in list(stats.by_rule.items())[:10]
    )

    # Show last 50 events (most recent first)
    recent = list(reversed(stats.timeline[-50:]))
    event_rows = "\n".join(
        '<tr><td>{ts}</td><td>{hook}</td><td>{tool}</td>'
        '<td><span class="badge {cls}">{status}</span></td>'
        "<td>{rule}</td></tr>".format(
            ts=_escape(ev.get("ts", "")),
            hook=_escape(ev.get("hook", "")),
            tool=_escape(ev.get("tool", "")),
            cls="badge-allow" if ev.get("allowed") else "badge-block",
            status="ALLOW" if ev.get("allowed") else "BLOCK",
            rule=_escape(ev.get("rule", "")),
        )
        for ev in recent
    )

    return _HTML_TEMPLATE % {
        "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "total": stats.total_events,
        "allowed": stats.allowed,
        "blocked": stats.blocked,
        "block_rate": block_rate,
        "hook_rows": hook_rows or "<tr><td colspan='2'>No data</td></tr>",
        "tool_rows": tool_rows or "<tr><td colspan='2'>No data</td></tr>",
        "rule_rows": rule_rows or "<tr><td colspan='2'>No data</td></tr>",
        "event_rows": event_rows or "<tr><td colspan='5'>No events</td></tr>",
    }


def export_html_report(cwd: str, output: str | None = None) -> str:
    """Export HTML audit report to a file. Returns output path."""
    html = generate_html_report(cwd)
    if output is None:
        output = str(Path(cwd) / ".tribunal" / "audit-report.html")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(html)
    return output
