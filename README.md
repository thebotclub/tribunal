# tribunal.dev

The website and Python CLI for [Tribunal](https://tribunal.dev) — enterprise-grade discipline for Claude Code.

## Repository Structure

```
tribunal.dev/
├── src/              # Next.js website (tribunal.dev)
├── tribunal/         # Python CLI package
│   ├── src/tribunal/ # Core modules (18 modules)
│   └── tests/        # Test suite (266 tests)
├── ROADMAP.md        # Architecture review & feature roadmap
└── package.json      # Website dependencies
```

## Tribunal CLI

Tribunal enforces TDD, quality gates, and team standards on Claude Code sessions via the hook protocol.

```bash
pip install tribunal
tribunal init
```

**20 CLI commands** covering: rules, audit, cost budgets, analytics, review agents, MCP server, skills, permissions, memory injection, air-gapped bundles, model routing, marketplace, dashboard, and enterprise fleet management.

See [tribunal/README.md](tribunal/README.md) for full documentation.

## Website

The marketing site at [tribunal.dev](https://tribunal.dev) is built with Next.js and deployed on Cloudflare Pages.

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # Production build
```

## Links

- **Website:** [tribunal.dev](https://tribunal.dev)
- **PyPI:** [pypi.org/project/tribunal](https://pypi.org/project/tribunal/)
- **GitHub:** [github.com/thebotclub/tribunal.dev](https://github.com/thebotclub/tribunal.dev)

## License

MIT
