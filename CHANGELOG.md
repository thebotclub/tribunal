# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.1] -- 2026-05-13

### Changed

- All CLI output is now strict ASCII -- no emoji, smart quotes, or em-dashes.
  Status markers use bracketed tokens: `[ok]`, `[x]`, `[!]`, `[blocked]`, `[T]`,
  `[pkg]`, `[list]`. This makes output stable across terminals, CI logs,
  and Windows consoles that do not always render Unicode glyphs correctly.
- `tribunal --version` now reports `3.0.0` cleanly (was `3.0.0a1`, a leftover
  pre-release tag that confused users on the released `3.0.0` PyPI build).
- README rewritten for clarity; added security policy, code of conduct,
  issue templates, PR template, dependabot config, CODEOWNERS, CHANGELOG.

### Internal

- Removed the legacy `_archive/` folder from the published source tree --
  it shipped v2 modules that were replaced in v3.

## [3.0.0] -- 2026-05-13

### Added

- Cross-agent unified event schema (`spec/event-schema-v1.json`).
- Policy engine v3 with YAML rule packs (`soc2`, `startup`, `enterprise`,
  `security`).
- Cost tracking across agents (`tribunal cost report`).
- Adapters for Claude Code, Cursor, GitHub Copilot CLI, and OpenAI Codex CLI.
- Optional hosted dashboard at app.tribunal.dev (paid tier).
- npm thin launcher so teams using Node toolchains can `npm install -g tribunal`.

### Changed

- The v2 quality-gate scanner moved under `tribunal scan` (was the top-level
  default in v2). All v2 behaviour is preserved.

## [2.x]

Legacy v2 line -- quality-gate CLI only (TDD, secret scanning, lint, SARIF).
No longer receiving fixes. Use 3.x.
