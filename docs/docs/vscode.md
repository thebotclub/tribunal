# VS Code Extension

The Tribunal VS Code extension provides visual governance management.

## Features

- **Rules Tree View** — See all rules with action/trigger icons
- **Audit Tree View** — Browse recent audit entries
- **Agents Tree View** — Monitor active sub-agents
- **Cost Tree View** — Track session costs and budgets
- **Status Bar** — Rule count and blocked event count at a glance

## Installation

The extension is available in the `vscode-tribunal/` directory. Build and install:

```bash
cd vscode-tribunal
npm install
npm run compile
```

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `tribunal.projectRoot` | Project root path | workspace root |
| `tribunal.dashboardUrl` | Team dashboard URL | `http://localhost:8700` |

## Commands

| Command | Description |
|---------|-------------|
| Tribunal: Refresh | Refresh all views |
| Tribunal: Open Rules | Open rules.yaml |
| Tribunal: Open Audit | Open audit.jsonl |
| Tribunal: Open Config | Open config.yaml |
| Tribunal: Run Doctor | Run health check |
