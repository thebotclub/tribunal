# Contributing to Tribunal

Thanks for your interest in contributing.

## Local development

```bash
cd tribunal
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # run tests
ruff format src/ tests/      # auto-format
ruff check --fix src/ tests/ # auto-fix lint
```

## What we'd love help with

- **New agent adapters.** Each adapter in
  [`tribunal/src/tribunal/adapters/`](tribunal/src/tribunal/adapters/) is
  ~150 lines. If you use an agent we don't support yet (Aider, Continue,
  Sweep, etc.), open an issue and we'll guide you through wiring it up.
- **Policy rules library.** YAML policy snippets that solve real problems
  (no-secrets-in-prompts, redact-PII, deny-prod-writes-without-approval, etc.)
- **Docs improvements** -- especially examples and screenshots.
- **Bug reports** with a minimal reproduction.

## PR checklist

- Tests added/updated and passing locally (`pytest`)
- `ruff format` and `ruff check` clean
- New behavior documented (README + docs/ if user-facing)

## Code of conduct

Be kind. Discuss ideas, not people. Maintainers reserve the right to lock
threads or remove comments that violate this.

## License

By submitting a PR you agree to license your contribution under the MIT
license, same as the rest of the repo.
