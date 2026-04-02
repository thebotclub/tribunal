"""Model routing — route to different models based on task type and cost.

Allows configuring model preferences per operation type, with automatic
fallback and cost-aware routing. Matches Claude Code's model configuration
patterns while adding cost optimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelRoute:
    """A single routing rule for model selection."""

    name: str = ""
    pattern: str = ""  # glob pattern for tool/task matching
    model: str = ""  # target model (e.g. sonnet, opus, haiku)
    max_cost_usd: float = 0.0  # max cost threshold to use this model
    description: str = ""

    def matches(self, tool_name: str = "", task_type: str = "") -> bool:
        """Check if this route matches the given tool/task."""
        import fnmatch

        if not self.pattern:
            return True  # default/fallback route

        target = tool_name or task_type
        return fnmatch.fnmatch(target.lower(), self.pattern.lower())


@dataclass
class ModelConfig:
    """Full model routing configuration."""

    default_model: str = "sonnet"
    routes: list[ModelRoute] = field(default_factory=list)
    cost_aware: bool = True  # auto-downgrade on budget pressure
    budget_threshold_pct: float = 80.0  # switch to cheaper model at this budget %

    def resolve_model(self, tool_name: str = "", task_type: str = "",
                      budget_used_pct: float = 0.0) -> str:
        """Resolve which model to use for the given context."""
        # Cost-aware downgrade
        if self.cost_aware and budget_used_pct >= self.budget_threshold_pct:
            return "haiku"  # cheapest model for budget conservation

        # Check routes in order (first match wins)
        for route in self.routes:
            if route.matches(tool_name, task_type):
                return route.model

        return self.default_model


def load_model_config(cwd: str | None = None) -> ModelConfig:
    """Load model routing config from .tribunal/config.yaml."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    cfg_path = project_dir / ".tribunal" / "config.yaml"

    config = ModelConfig()

    if not cfg_path.is_file():
        return config

    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError:
        return config

    model_data = data.get("model_routing", {})
    if not model_data:
        return config

    if default := model_data.get("default"):
        config.default_model = str(default)

    if "cost_aware" in model_data:
        config.cost_aware = bool(model_data["cost_aware"])

    if threshold := model_data.get("budget_threshold_pct"):
        config.budget_threshold_pct = float(threshold)

    for route_data in model_data.get("routes", []):
        route = ModelRoute(
            name=route_data.get("name", ""),
            pattern=route_data.get("pattern", ""),
            model=route_data.get("model", ""),
            max_cost_usd=float(route_data.get("max_cost_usd", 0)),
            description=route_data.get("description", ""),
        )
        config.routes.append(route)

    return config


def format_model_config(config: ModelConfig) -> str:
    """Format model routing config for display."""
    lines = ["\n  ⚖  Model Routing Configuration\n"]
    lines.append(f"  Default model: {config.default_model}")
    lines.append(f"  Cost-aware: {'yes' if config.cost_aware else 'no'}")

    if config.cost_aware:
        lines.append(f"  Budget threshold: {config.budget_threshold_pct:.0f}%")

    if config.routes:
        lines.append("\n  Routes:")
        for route in config.routes:
            desc = f" — {route.description}" if route.description else ""
            lines.append(f"    {route.pattern or '*'} → {route.model}{desc}")
    else:
        lines.append("\n  No custom routes configured.")

    lines.append("")
    return "\n".join(lines)
