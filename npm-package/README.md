# Tribunal

> Quality gates for AI-generated code — TDD enforcement, secret scanning, and audit trails for coding agents.

[![PyPI](https://img.shields.io/pypi/v/tribunal.svg)](https://pypi.org/project/tribunal/)
[![npm](https://img.shields.io/npm/v/tribunal.svg)](https://www.npmjs.com/package/tribunal)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/thebotclub/tribunal.dev/blob/main/LICENSE)

**Tribunal v3** is the open-source governance plane for coding agents — Claude Code, Cursor, GitHub Copilot CLI, Codex CLI, and anything else that writes code on your behalf. It enforces TDD, scans for secrets and prompt injection, captures an audit trail of every agent action, and rolls up to a hosted dashboard for teams that need org-wide visibility.

## About this package

This is the **npm launcher** for Tribunal v3. The real CLI is a Python package on PyPI ([`tribunal`](https://pypi.org/project/tribunal/)). This npm package exists so that JavaScript-first teams can use `npx tribunal` or `npm install -g tribunal` without leaving their toolchain.

The first time you run it, the launcher will install `tribunal` from PyPI using `pipx` (preferred) or `pip --user`. After that, it just exec's the Python CLI directly — zero overhead.

> **Heads up:** Tribunal `1.x` on npm was a deprecated Claude Code plugin. Tribunal `3.0.0+` is a unified governance CLI that supersedes it.

## Install

### Quick start (any platform)

```bash
npx tribunal init           # one-shot, downloads on first run
```

### Persistent install via npm

```bash
npm install -g tribunal
tribunal --help
```

### Direct (recommended for Python users)

```bash
pipx install tribunal       # isolated install, recommended
# or
pip install --user tribunal # fallback
```

## What it does

```text
tribunal init             # scaffold .tribunal/ in your repo
tribunal status           # show daemon health
tribunal rules list       # list active rules
tribunal scan <file>      # one-shot scan for secrets / prompt injection
tribunal audit tail       # live audit log
tribunal serve            # start the local FastAPI daemon
tribunal pack             # bundle audit logs for the cloud dashboard
tribunal ci check         # CI-mode gate (exits non-zero on violation)
tribunal cost report      # local cost rollup
tribunal policy apply     # apply a policy pack (starter / strict / custom)
tribunal adapter ...      # configure adapters (Claude Code, Cursor, Copilot CLI, Codex CLI)
tribunal doctor           # diagnose your setup
```

## Requirements

- **Python 3.11+** (the launcher will tell you if it can't find a usable Python).
- **macOS, Linux, or Windows.**
- **Node 18+** if you're invoking via `npx` / `npm`.

## Configuration

`TRIBUNAL_NO_BOOTSTRAP=1` — disable auto-install. The launcher will still run `tribunal` if it's already on PATH, but won't try to install it for you.

## Links

- 🌐 Website: <https://tribunal.dev>
- ☁️ Dashboard: <https://app.tribunal.dev>
- 🐍 PyPI: <https://pypi.org/project/tribunal/>
- 💻 GitHub: <https://github.com/thebotclub/tribunal.dev>
- 📚 Docs: <https://tribunal.dev/docs>

## License

MIT — see [LICENSE](./LICENSE).
