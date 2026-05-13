<div align="center">

# Tribunal

**One audit log. One policy engine. One spend ledger. For every coding agent on your team.**

[![PyPI](https://img.shields.io/pypi/v/tribunal.svg?logo=python&logoColor=white)](https://pypi.org/project/tribunal/)
[![npm](https://img.shields.io/npm/v/tribunal.svg?logo=npm&logoColor=white)](https://www.npmjs.com/package/tribunal)
[![CI](https://github.com/thebotclub/tribunal/actions/workflows/ci.yml/badge.svg)](https://github.com/thebotclub/tribunal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/tribunal/)

</div>

Claude Code, Cursor, Copilot CLI, Codex CLI -- each has its own logs, its
own caps, and its own admin surface. **Tribunal sits underneath all of
them**, normalises every tool call into a unified event schema, enforces
cross-agent policy, tracks cost, and produces an audit trail your security
and compliance team can actually use.

The CLI, daemon, adapters, policy engine, and event schema are
**open source (MIT)** -- this repo. The hosted dashboard at
[app.tribunal.dev](https://app.tribunal.dev) (SSO, retention,
tamper-evident logs, SOC 2 evidence pack) is the paid tier.

## Install

```bash
# Python (recommended)
pipx install tribunal

# Or via npm (thin launcher; pulls the Python package on first run)
npm install -g tribunal
```

## 60-second quickstart

```bash
tribunal init        # detect installed agents, wire hooks, start the local daemon
tribunal status      # show what is connected
tribunal audit tail  # live tail of the unified event stream
```

Power-user subcommands:

```bash
tribunal scan .         # quality-gate scanner (TDD, secrets, lint, SARIF)
tribunal policy test    # dry-run a policy YAML against recent events
tribunal cost report    # cross-agent spend over the last 7 days
tribunal pack list      # list available rule packs (soc2, startup, ...)
```

Full reference: [`tribunal/README.md`](tribunal/README.md).
Event schema: [`tribunal/spec/event-schema-v1.json`](tribunal/spec/event-schema-v1.json).

## What it looks like

```text
$ tribunal status

  [T]  Tribunal v3.0.0

  [ok] daemon running on http://localhost:8088
  [ok] 3 adapters wired (claude-code, cursor, copilot)
  [ok] 247 events in the local log (last 24h)
  [!]  1 policy block in the last hour -- see: tribunal audit tail
```

```text
$ tribunal cost report --by agent --last 7d

  Agent           Sessions   Events    Cost (USD)
  claude-code           14     1240        $38.21
  cursor                 9      672        $12.04
  copilot-cli            6      318         $4.91
  ---
  Total                 29     2230        $55.16
```

## Repository layout

```
tribunal/                Python package (PyPI: tribunal)
  src/tribunal/          CLI, daemon, adapters, policy engine
  spec/                  Open event schema (v1) -- versioned, MIT
  cloud/                 Reference Cloudflare worker code (self-host)
  tests/                 Test suite (pytest)
npm-package/             Thin npm launcher (delegates to the Python pkg)
vscode-tribunal/         VS Code extension (preview)
docs/                    MkDocs site
```

## What is open vs paid

| Open source (this repo)        | Paid (tribunal.dev cloud)                    |
|--------------------------------|----------------------------------------------|
| CLI + local daemon             | Hosted dashboard at app.tribunal.dev         |
| All agent adapters             | SSO (Google, Microsoft, Okta) and SAML       |
| Policy engine + YAML rule DSL  | Tamper-evident audit log with retention      |
| Event schema (v1, MIT, stable) | Compliance evidence pack (SOC 2 / ISO 27001) |
| Cost tracking + caps           | Multi-org, role-based access control         |
| Reference cloud workers        | Stripe billing, seat management, DPA         |
| MIT licensed, fork freely      | Hosted SLA, dedicated support                |

Self-hosting the cloud workers is fully supported -- see
[`tribunal/cloud/README.md`](tribunal/cloud/README.md).

## Adapters

Tribunal ships with adapters for:

- **Claude Code** -- via the `.claude/claudeconfig.json` hooks
- **Cursor** -- via the editor extension and proxy
- **GitHub Copilot CLI** -- via shell wrappers
- **OpenAI Codex CLI** -- via process wrappers

New adapters are ~150 lines. If your agent is not on the list,
[open an issue](https://github.com/thebotclub/tribunal/issues/new) and we
will walk you through it.

## Event schema

Every event the daemon sees is normalised to the schema in
[`tribunal/spec/event-schema-v1.json`](tribunal/spec/event-schema-v1.json).
This schema is **versioned and stable** -- v1 will remain backwards
compatible. Build your own dashboards on top of it; it is just JSONL.

## Contributing

We welcome PRs. The fastest impact areas:

- **New agent adapters** -- see [`tribunal/src/tribunal/adapters/`](tribunal/src/tribunal/adapters/)
- **Policy rules library** -- YAML snippets that solve real problems
- **Docs and examples**
- **Bug reports** with a minimal repro

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions.
See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.
Security issues: please follow [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE). The hosted product
(private repo `thebotclub/tribunal.dev`) is proprietary; this repo is
the entire open layer.
