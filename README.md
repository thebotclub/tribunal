# tribunal.dev

The website and Python CLI for [Tribunal](https://tribunal.dev) — local quality gates for AI-generated code.

## Repository Structure

```
tribunal.dev/
├── src/              # Next.js website (tribunal.dev)
├── tribunal/         # Python CLI package
│   ├── src/tribunal/ # Core modules (26 modules)
│   └── tests/        # Test suite (432 tests)
├── vscode-tribunal/  # VS Code extension scaffold
├── docs/             # MkDocs documentation site
├── .github/          # CI/CD workflows (test matrix, PyPI publish, website)
├── ROADMAP-V2.md     # V2 roadmap (Phases 5-10)
└── package.json      # Website dependencies
```

## Tribunal CLI

Tribunal enforces TDD, secret scanning, linting, and team standards across CI, pre-commit, and AI coding agent workflows.

```bash
pip install tribunal
tribunal init
```

**Core CLI commands** cover quality checks, project initialization, rule packs, audit logs, configuration inspection, and installation health checks.

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
