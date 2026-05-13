# tribunal.dev

> **Heads-up:** Tribunal is mid-pivot to **v3 — the open audit and policy
> layer for coding agents** (Claude Code, Cursor, Copilot CLI, Codex CLI).
> The v2 quality-gates CLI still works and stays supported as a `tribunal scan`
> subcommand. Public 3.0 GA targeted for Q3 2026. See
> [`ROADMAP-V2.md`](ROADMAP-V2.md) and the v3 execution plan attached to the
> first v3 PR for details.

This monorepo hosts the marketing site, the Python package, and the
docs/build infrastructure for [Tribunal](https://tribunal.dev).

## Repository structure

```
tribunal.dev/
├── src/              # Next.js marketing site (tribunal.dev)
├── tribunal/         # Python package
│   ├── src/tribunal/ # Core modules
│   └── tests/        # Test suite
├── docs/             # MkDocs documentation site
├── .github/          # CI/CD workflows
└── package.json      # Website dependencies
```

`vscode-tribunal/` is paused and excluded from the v3 launch surface.

## What Tribunal is (v3, in one line)

**One audit log, one policy engine, one spend ledger — for every coding agent
on your team.**

Today's coding agents (Claude Code, Cursor, Copilot CLI, Codex CLI) each have
their own logs, their own caps, and their own admin surfaces. Tribunal sits
underneath all of them, normalises every tool call into a unified event
schema, enforces cross-agent policy, tracks cost, and produces an audit trail
your security and compliance team can actually use.

The CLI, daemon, adapters, policy engine, and event schema are **open
source (MIT)**. The hosted dashboard, SSO, and SOC 2 evidence pack are the
paid tier.

## Quickstart

```bash
pip install tribunal
tribunal init        # detects installed agents, wires hooks, starts the local daemon
tribunal status      # show what's connected
```

Power-user subcommands:

```bash
tribunal scan .      # the legacy v2 quality-gate scanner (still supported)
tribunal audit tail  # live tail of the unified event stream
tribunal policy test # dry-run a policy YAML against recent events
tribunal cost report # cross-agent spend over the last 7 days
```

See [`tribunal/README.md`](tribunal/README.md) for full CLI docs.

## Marketing site

The site at [tribunal.dev](https://tribunal.dev) is Next.js, deployed on
Cloudflare Pages.

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # production build
```

## Links

- **Website:** [tribunal.dev](https://tribunal.dev)
- **PyPI:** [pypi.org/project/tribunal](https://pypi.org/project/tribunal/)
- **Event schema:** `spec/event-schema-v1.json` (published at
  [tribunal.dev/spec](https://tribunal.dev/spec) once v3 ships)
- **Roadmap:** [`ROADMAP-V2.md`](ROADMAP-V2.md)

## License

MIT for the CLI, daemon, adapters, policy engine, and event schema. The
hosted dashboard and the compliance-tier extras are source-available under a
commercial license (full text shipped alongside v3 GA).
