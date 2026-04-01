"""Rule marketplace — share and discover community rule bundles.

Provides a local registry of known rule bundles and utilities for
discovering, installing, and publishing rule sets. The marketplace
is file-based (no external service required).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .sync import RuleBundle, import_from_file, validate_bundle


@dataclass
class MarketplaceEntry:
    """An entry in the rule marketplace registry."""

    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""  # file path or URL
    installed: bool = False


def _registry_path() -> Path:
    """Get the marketplace registry path (~/.tribunal/marketplace.json)."""
    return Path.home() / ".tribunal" / "marketplace.json"


def _load_registry() -> list[dict[str, Any]]:
    """Load the marketplace registry."""
    path = _registry_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(entries: list[dict[str, Any]]) -> None:
    """Save the marketplace registry."""
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2) + "\n")


def list_marketplace(tags: list[str] | None = None) -> list[MarketplaceEntry]:
    """List all entries in the marketplace registry."""
    entries = []
    for data in _load_registry():
        entry = MarketplaceEntry(
            name=data.get("name", ""),
            version=data.get("version", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            source=data.get("source", ""),
            installed=data.get("installed", False),
        )
        if tags:
            if not any(t in entry.tags for t in tags):
                continue
        entries.append(entry)
    return entries


def register_bundle(bundle_path: str | Path) -> tuple[bool, str]:
    """Register a rule bundle in the marketplace.

    Returns (success, message).
    """
    path = Path(bundle_path)
    if not path.is_file():
        return False, f"File not found: {bundle_path}"

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        return False, f"Invalid YAML: {e}"

    errors = validate_bundle(data)
    if errors:
        return False, f"Invalid bundle: {'; '.join(errors)}"

    entries = _load_registry()

    # Check for duplicate
    name = data.get("name", "")
    for entry in entries:
        if entry.get("name") == name:
            entry.update({
                "version": data.get("version", ""),
                "description": data.get("description", ""),
                "author": data.get("author", ""),
                "source": str(path.resolve()),
            })
            _save_registry(entries)
            return True, f"Updated '{name}' in marketplace."

    entries.append({
        "name": name,
        "version": data.get("version", ""),
        "description": data.get("description", ""),
        "author": data.get("author", ""),
        "tags": [],
        "source": str(path.resolve()),
        "installed": False,
    })
    _save_registry(entries)
    return True, f"Registered '{name}' in marketplace."


def install_from_marketplace(name: str, cwd: str | None = None) -> tuple[bool, list[str]]:
    """Install a bundle from the marketplace by name.

    Returns (success, messages).
    """
    entries = _load_registry()
    target = None
    for entry in entries:
        if entry.get("name") == name:
            target = entry
            break

    if not target:
        return False, [f"Bundle '{name}' not found in marketplace."]

    source = target.get("source", "")
    if not source:
        return False, [f"No source path for bundle '{name}'."]

    success, messages = import_from_file(source, cwd)
    if success:
        target["installed"] = True
        _save_registry(entries)
        messages.append(f"Marked '{name}' as installed.")

    return success, messages


def unregister_bundle(name: str) -> tuple[bool, str]:
    """Remove a bundle from the marketplace registry."""
    entries = _load_registry()
    new_entries = [e for e in entries if e.get("name") != name]

    if len(new_entries) == len(entries):
        return False, f"Bundle '{name}' not found in marketplace."

    _save_registry(new_entries)
    return True, f"Removed '{name}' from marketplace."


def format_marketplace(entries: list[MarketplaceEntry]) -> str:
    """Format marketplace entries for display."""
    lines = ["\n  ⚖  Tribunal Rule Marketplace\n"]

    if not entries:
        lines.append("  No bundles registered.")
        lines.append("  Use 'tribunal marketplace register <file>' to add bundles.")
        lines.append("")
        return "\n".join(lines)

    for entry in entries:
        status = "✓ installed" if entry.installed else "available"
        lines.append(f"  {entry.name} v{entry.version} [{status}]")
        if entry.description:
            lines.append(f"    {entry.description}")
        if entry.author:
            lines.append(f"    by {entry.author}")
        if entry.tags:
            lines.append(f"    tags: {', '.join(entry.tags)}")
        lines.append("")

    return "\n".join(lines)
