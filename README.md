# Tribunal

> **One audit log, one policy engine, one spend ledger — for every coding agent on your team.**

[![PyPI](https://img.shields.io/pypi/v/tribunal.svg)](https://pypi.org/project/tribunal/)
[![npm](https://img.shields.io/npm/v/tribunal.svg)](https://www.npmjs.com/package/tribunal)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Today's coding agents — Claude Code, Cursor, Copilot CLI, Codex CLI — each
have their own logs, their own caps, and their own admin surfaces. Tribunal
sits underneath all of them, normalises every tool call into a unified event
schema, enforces cross-agent policy, tracks cost, and produces an audit trail
your security and compliance team can actually use.

The CLI, daemon, adapters, policy engine, and event schema are **open source
(MIT)**. The hosted dashboard ([app.tribunal.dev](https://app.tribunal.dev))
with SSO, retention, tamper-evident logs, and a SOC 2 evidence pack is the
paid tier.

## Install

```bash
# Python (recommended)
pipx install tribunal

# Or via npm (thin launcher; pulls the Python package on first run)
npm install -g tribunal
```

## Quickstart

```bash
tribunal init        # detect installed agents, wire hooks, start the local daemon
tribunal status      # show what's connected
tribunal audit tail  # live tail of the unified event stream
```

Power-user subcommands:

```bash
tribunal scan .         # legacy v2 quality-gate scanner (still supported)
tribunal policy test    # dry-run a policy YAML against recent events
tribunal cost report    # cross-agent spend over the last 7 days
```

See [`tribunal/README.md`](tribunal/README.md) for the full CLI reference and
[`spec/event-schema-v1.json`](tribunal/spec/event-schema-v1.json) for the
event schema.

## Repository layout

```
tribunal/                  Python package (PyPI: tribunal)
  src/tribunal/            CLI, daemon, adapters, policy engine
  spec/                    Open event schema (v1)
  cloud/                   Reference Cloudflare worker code for self-hosters
  tests/                   Test suite
npm-package/               Thin npm launcher (delegates to pipx)
vscode-tribunal/           VS Code extension (preview)
docs/                      MkDocs site
```

## What's open vs paid

| Open source (this repo) | Paid (tribunal.dev cloud) |
|---|---|
| CLI + daemon | Hosted dashboard at app.tribunal.dev |
| All agent adapters | SSO (Google, Microsoft, Okta) |
| Policy engine + YAML rules | Tamper-evident audit log with retention |
| Event schema | Compliance evidence pack (SOC 2 / ISO 27001) |
| Cost tracking | Stripe billing, seat management |
| Reference cloud workers | DPA, custom retention, dedicated support |

Self-hosting the cloud workers is fully supported — see
[`tribunal/cloud/README.md`](tribunal/cloud/README.md).

## Contributing

Issues and PRs welcome. New agent adapters are especially appreciated —
follow the pattern in
[`src/tribunal/adapters/`](tribunal/src/tribunal/adapters/) and
[`tests/test_adapter_*.py`](tribunal/tests/).

## License

MIT. See [LICENSE](LICENSE).

The hosted cloud product (private repo `thebotclub/tribunal.dev`) is
proprietary; this repo is the entire open layer.
