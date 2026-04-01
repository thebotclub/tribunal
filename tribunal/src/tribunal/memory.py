"""Memory injection — write Tribunal rules and learnings into Claude Code's memory.

Claude Code's memory system uses markdown files with YAML frontmatter stored in
.claude/memory/. Tribunal can inject rules, warnings, patterns, and session
learnings so they surface contextually in future sessions.

Memory types: pattern, warning, gotcha, reference, session-log
Limit: 200 files, 25KB per entry
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MemoryEntry:
    """A single memory entry for Claude Code's memory system."""

    title: str = ""
    content: str = ""
    memory_type: str = "pattern"  # pattern, warning, gotcha, reference, session-log
    tags: list[str] = field(default_factory=list)
    source: str = "tribunal"

    def to_markdown(self) -> str:
        """Render as Claude Code memory markdown with YAML frontmatter."""
        frontmatter = {
            "type": self.memory_type,
            "source": self.source,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if self.tags:
            frontmatter["tags"] = self.tags

        lines = ["---"]
        lines.append(yaml.dump(frontmatter, default_flow_style=False).strip())
        lines.append("---")
        lines.append("")
        if self.title:
            lines.append(f"# {self.title}")
            lines.append("")
        lines.append(self.content)
        lines.append("")
        return "\n".join(lines)


def _memory_dir(cwd: str) -> Path:
    """Get the Claude Code memory directory for the project."""
    return Path(cwd) / ".claude" / "memory"


def inject_memory(cwd: str, entry: MemoryEntry, filename: str | None = None) -> Path:
    """Write a memory entry to Claude Code's memory directory.

    Returns the path of the written memory file.
    """
    mem_dir = _memory_dir(cwd)
    mem_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        # Generate filename from title
        safe_title = entry.title.lower().replace(" ", "-")
        safe_title = "".join(c for c in safe_title if c.isalnum() or c == "-")
        filename = f"tribunal-{safe_title}.md"

    path = mem_dir / filename
    path.write_text(entry.to_markdown())
    return path


def inject_rules_as_memory(cwd: str) -> list[Path]:
    """Inject current Tribunal rules as memory entries.

    This makes rules visible to Claude Code's memory relevance system,
    so they surface contextually without hook overhead.
    """
    rules_path = Path(cwd) / ".tribunal" / "rules.yaml"
    if not rules_path.is_file():
        return []

    try:
        data = yaml.safe_load(rules_path.read_text()) or {}
    except yaml.YAMLError:
        return []

    rules = data.get("rules", {})
    if not rules:
        return []

    paths = []
    for name, rule in rules.items():
        message = rule.get("message", f"Rule: {name}")
        trigger = rule.get("trigger", "")
        action = rule.get("action", "")

        content_lines = [
            f"**Tribunal Rule: {name}**",
            "",
            f"- Trigger: {trigger}",
            f"- Action: {action}",
            f"- {message}",
        ]

        if match := rule.get("match"):
            content_lines.append(f"- Match: {match}")

        if condition := rule.get("condition"):
            content_lines.append(f"- Condition: {condition}")

        memory_type = "warning" if action == "block" else "pattern"

        entry = MemoryEntry(
            title=f"Tribunal Rule — {name}",
            content="\n".join(content_lines),
            memory_type=memory_type,
            tags=["tribunal", "rules", trigger.lower()] if trigger else ["tribunal", "rules"],
        )
        path = inject_memory(cwd, entry, f"tribunal-rule-{name}.md")
        paths.append(path)

    return paths


def inject_session_summary(cwd: str, summary: str, session_id: str = "") -> Path:
    """Inject a session summary as a memory entry.

    Useful for persisting learnings from a Tribunal-gated session.
    """
    title = f"Session Summary"
    if session_id:
        title += f" ({session_id[:8]})"

    entry = MemoryEntry(
        title=title,
        content=summary,
        memory_type="session-log",
        tags=["tribunal", "session"],
    )

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    filename = f"tribunal-session-{ts}.md"
    return inject_memory(cwd, entry, filename)


def clear_tribunal_memories(cwd: str) -> int:
    """Remove all Tribunal-injected memories. Returns count removed."""
    mem_dir = _memory_dir(cwd)
    if not mem_dir.is_dir():
        return 0

    count = 0
    for f in mem_dir.iterdir():
        if f.name.startswith("tribunal-") and f.suffix == ".md":
            f.unlink()
            count += 1
    return count


def list_tribunal_memories(cwd: str) -> list[dict[str, str]]:
    """List all Tribunal-injected memory files."""
    mem_dir = _memory_dir(cwd)
    if not mem_dir.is_dir():
        return []

    entries = []
    for f in sorted(mem_dir.iterdir()):
        if f.name.startswith("tribunal-") and f.suffix == ".md":
            # Parse frontmatter
            text = f.read_text()
            memory_type = "unknown"
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    try:
                        fm = yaml.safe_load(parts[1]) or {}
                        memory_type = fm.get("type", "unknown")
                    except yaml.YAMLError:
                        pass

            entries.append({
                "file": f.name,
                "type": memory_type,
                "size": len(text),
            })
    return entries


def format_memory_status(cwd: str) -> str:
    """Format memory injection status for display."""
    entries = list_tribunal_memories(cwd)
    lines = ["\n  ⚖  Tribunal Memory Status\n"]

    mem_dir = _memory_dir(cwd)
    lines.append(f"  Memory dir: {mem_dir}")

    if not entries:
        lines.append("  No Tribunal memories injected.")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"  {len(entries)} memory file(s):\n")
    for e in entries:
        lines.append(f"    {e['file']}  [{e['type']}]  {e['size']}B")

    lines.append("")
    return "\n".join(lines)
