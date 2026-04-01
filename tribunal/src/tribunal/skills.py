"""Skills system — markdown-based workflow definitions.

Claude Code natively discovers .md files with YAML frontmatter in skill
directories. Tribunal ships bundled skills and lets users create custom ones.
Skills are installed to .tribunal/skills/ and referenced in claudeconfig.json.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Skill:
    """A parsed skill definition."""

    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    trigger: str = ""  # when to activate: manual, auto, hook-event
    content: str = ""  # the full markdown body
    path: str = ""  # file path if loaded from disk
    bundled: bool = False  # True if shipped with Tribunal


def parse_skill(text: str, path: str = "") -> Skill:
    """Parse a markdown skill file with YAML frontmatter."""
    # Extract YAML frontmatter between --- markers
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        # No frontmatter — treat entire content as the skill body
        name = Path(path).stem if path else "unknown"
        return Skill(name=name, content=text.strip(), path=path)

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    frontmatter = yaml.safe_load(frontmatter_text) or {}

    name = frontmatter.get("name", Path(path).stem if path else "unknown")
    return Skill(
        name=name,
        description=frontmatter.get("description", ""),
        tags=frontmatter.get("tags", []),
        trigger=frontmatter.get("trigger", "manual"),
        content=body,
        path=path,
    )


def load_skills_dir(skills_dir: str | Path) -> list[Skill]:
    """Load all .md skills from a directory."""
    skills_path = Path(skills_dir)
    if not skills_path.is_dir():
        return []

    skills = []
    for md_file in sorted(skills_path.glob("*.md")):
        text = md_file.read_text()
        skill = parse_skill(text, str(md_file))
        skills.append(skill)

    return skills


def load_project_skills(cwd: str | None = None) -> list[Skill]:
    """Load skills from the project's .tribunal/skills/ directory."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    skills_dir = project_dir / ".tribunal" / "skills"
    return load_skills_dir(skills_dir)


def load_bundled_skills() -> list[Skill]:
    """Load skills bundled with Tribunal."""
    bundled_dir = Path(__file__).parent / "bundled_skills"
    skills = load_skills_dir(bundled_dir)
    for s in skills:
        s.bundled = True
    return skills


def install_skill(skill: Skill, cwd: str | None = None) -> Path:
    """Install a skill to the project's .tribunal/skills/ directory."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    skills_dir = project_dir / ".tribunal" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{skill.name}.md"
    dest = skills_dir / filename

    # Build the skill file
    frontmatter = {
        "name": skill.name,
        "description": skill.description,
    }
    if skill.tags:
        frontmatter["tags"] = skill.tags
    if skill.trigger:
        frontmatter["trigger"] = skill.trigger

    text = "---\n"
    text += yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    text += "---\n\n"
    text += skill.content + "\n"

    dest.write_text(text)
    return dest


def create_skill_scaffold(name: str, cwd: str | None = None) -> Path:
    """Create a new empty skill scaffold."""
    skill = Skill(
        name=name,
        description=f"Custom skill: {name}",
        tags=["custom"],
        trigger="manual",
        content=f"# {name}\n\nDescribe the workflow or instruction here.\n",
    )
    return install_skill(skill, cwd)


def list_all_skills(cwd: str | None = None) -> list[Skill]:
    """List all available skills (bundled + project)."""
    bundled = load_bundled_skills()
    project = load_project_skills(cwd)

    # Project skills override bundled ones with the same name
    by_name: dict[str, Skill] = {}
    for s in bundled:
        by_name[s.name] = s
    for s in project:
        by_name[s.name] = s

    return list(by_name.values())


def format_skill_list(skills: list[Skill]) -> str:
    """Format skills for display."""
    if not skills:
        return "  No skills installed. Run: tribunal skills install <name>"

    lines = [f"\n  ⚖  Tribunal Skills ({len(skills)} total)\n"]
    for s in skills:
        source = "📦" if s.bundled else "📝"
        tags = f" [{', '.join(s.tags)}]" if s.tags else ""
        lines.append(f"  {source} {s.name}{tags}")
        if s.description:
            lines.append(f"     {s.description}")
    lines.append("")
    return "\n".join(lines)
