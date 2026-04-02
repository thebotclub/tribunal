"""Plugin manifest for Claude Code's plugin system.

Generates a plugin manifest that makes Tribunal discoverable in Claude Code's
settings. The manifest declares hooks, skills paths, and MCP servers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__


@dataclass
class PluginManifest:
    """Tribunal's plugin manifest for Claude Code."""

    name: str = "tribunal"
    description: str = "Enterprise code discipline for Claude Code"
    version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        """Generate the full plugin manifest."""
        return {
            "name": self.name,
            "manifest": {
                "description": self.description,
                "version": self.version,
            },
            "hooksConfig": {
                "PreToolUse": [
                    {
                        "if": {"matcher": "Bash|FileEdit|FileWrite"},
                        "run": [{"command": "tribunal-gate"}],
                    }
                ],
                "PostToolUse": [
                    {
                        "if": {"matcher": "Bash|FileEdit|FileWrite"},
                        "run": [{"command": "tribunal-gate"}],
                    }
                ],
                "SessionStart": [
                    {
                        "run": [{"command": "tribunal-gate"}],
                    }
                ],
            },
            "skillsPaths": [
                "~/.tribunal/skills/",
                ".tribunal/skills/",
            ],
            "mcpServers": {
                "tribunal": {
                    "command": "tribunal",
                    "args": ["mcp-serve"],
                    "env": {},
                }
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def generate_manifest(output_path: str | Path | None = None) -> str:
    """Generate the plugin manifest. Optionally write to file."""
    manifest = PluginManifest()
    text = manifest.to_json()

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")

    return text


def install_plugin_manifest(cwd: str | None = None) -> Path:
    """Install the plugin manifest to the project directory."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    manifest_path = project_dir / ".tribunal" / "plugin.json"
    generate_manifest(manifest_path)
    return manifest_path
