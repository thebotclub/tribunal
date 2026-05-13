# Security Policy

## Supported versions

Tribunal follows semver. Security fixes are applied to:

| Version | Supported          |
|---------|--------------------|
| 3.0.x   | [ok] Yes           |
| 2.x     | [x] No (legacy)    |
| < 2.0   | [x] No             |

## Reporting a vulnerability

**Please do not file public GitHub issues for security problems.**

Email: `security@tribunal.dev`

Include:
- A description of the issue and its impact
- Steps to reproduce, or a minimal proof-of-concept
- The version of Tribunal you tested against (`tribunal --version`)
- Your name / handle for the credit line (optional)

You should hear back within 2 business days. We will work with you on a
fix and a coordinated disclosure timeline. If the issue affects the
hosted dashboard at `app.tribunal.dev` as well, we will patch that first
and the OSS release immediately after.

## Scope

In scope:
- `tribunal` Python package (PyPI)
- `tribunal` npm launcher
- The reference Cloud workers under `tribunal/cloud/`
- The VS Code extension under `vscode-tribunal/`

Out of scope (please report to the respective vendor):
- Cloudflare, Stripe, GitHub, or other third-party services we depend on
- Misconfigured self-hosted deployments (we will help you, but it is not
  a Tribunal vulnerability)

## Bounty

We do not currently run a paid bounty programme, but we are happy to
credit researchers in the release notes and on the website.
