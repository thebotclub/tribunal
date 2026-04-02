# Installation

## Requirements

- Python 3.10+
- Claude Code (for hook integration)

## Install from PyPI

```bash
pip install tribunal
```

## Verify Installation

```bash
tribunal --version
tribunal doctor
```

## Initialize a Project

```bash
cd your-project
tribunal init
```

This creates:

- `.tribunal/rules.yaml` — your governance rules
- `.tribunal/config.yaml` — Tribunal configuration
- `.claude/claudeconfig.json` — Claude Code hook registration

## Install a Rule Pack

```bash
tribunal pack install soc2
```

Available packs: `soc2`, `startup`, `enterprise`, `security`.

## Development Install

```bash
git clone https://github.com/thebotclub/tribunal.dev.git
cd tribunal.dev/tribunal
pip install -e ".[dev]"
```
