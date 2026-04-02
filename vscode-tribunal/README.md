# Tribunal VS Code Extension

Real-time governance dashboard for Claude Code sessions.

## Features

- **Rules TreeView** — see all active rules from `.tribunal/rules.yaml`
- **Audit Log TreeView** — browse recent audit entries with allow/block icons
- **Agents TreeView** — track active and completed sub-agents
- **Cost TreeView** — monitor session costs, budgets, tokens, and compactions
- **Status Bar** — rule count and blocked event count at a glance
- **Auto-refresh** — views update when `.tribunal/` files change
- **Commands** — doctor, init, rotate, validate from the command palette

## Installation

```bash
# From the vscode-tribunal directory:
npm install
npm run compile
# Then install the .vsix or use "Developer: Install Extension from Location"
```

## Requirements

- [Tribunal](https://pypi.org/project/tribunal/) CLI installed (`pip install tribunal`)
- A project with `.tribunal/rules.yaml` (run `tribunal init`)

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `tribunal.autoRefresh` | `true` | Auto-refresh views when `.tribunal/` files change |
| `tribunal.dashboardUrl` | `""` | Team dashboard API endpoint URL |
