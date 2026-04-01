# Privacy & Network Transparency

Tribunal is an open-source wrapper around [Claude Code](https://github.com/anthropics/claude-code) that enforces TDD, quality gates, and team standards. This document explains every outbound network connection the tool makes, why, and how to disable what you don't want.

> **TL;DR** — Tribunal itself sends **zero** telemetry. All outbound traffic originates from Anthropic's Claude Code CLI, which tribunal wraps. You can disable all non-essential traffic with a single environment variable.

---

## Quick Disable

| What you want | Environment variable |
|---|---|
| Disable all telemetry (Datadog, event logs, surveys) | `DISABLE_TELEMETRY=1` |
| Disable **all** non-essential traffic (telemetry + updates + feature flags) | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` |
| Disable OpenTelemetry tracing | `OTEL_SDK_DISABLED=true` |

Add any of these to your shell profile or `.env` to make them permanent:

```bash
# Recommended: disable all non-essential network traffic
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
```

---

## What Connects Where

### Essential (required for Claude to work)

| Destination | Purpose | Data sent |
|---|---|---|
| `api.anthropic.com` — Claude API | Send prompts, receive responses | Your prompts and code context |
| `api.anthropic.com` — OAuth | Authentication | OAuth tokens (no passwords) |
| `api.anthropic.com` — Sessions | Session management for remote/bridge mode | Session IDs, messages |

These cannot be disabled — Claude Code needs them to function.

### Non-essential telemetry (disabled by `DISABLE_TELEMETRY=1`)

| Destination | Purpose | Data sent |
|---|---|---|
| `api.anthropic.com/api/event_logging/batch` | First-party event logging | Anonymized usage events (tool success/error counts, session lifecycle) |
| `http-intake.logs.us5.datadoghq.com` | Datadog operational logging | Event names, error types, platform/version info. **No code or prompts.** |
| GrowthBook SDK | Feature flags & experiments | Session ID, device ID, platform, subscription type |

### Non-essential features (disabled by `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`)

| Destination | Purpose |
|---|---|
| Auto-update checks | Check for new CLI versions |
| Grove configuration | Cloud-stored account preferences |
| Release notes | Fetch changelog |
| Model capabilities | Fetch model metadata |
| MCP registry | Discover official MCP servers |
| Settings sync | Cloud backup of user settings |

### Optional (user-initiated only)

| Feature | Destination | When |
|---|---|---|
| Feedback submission | `api.anthropic.com/api/claude_cli_feedback` | Only when you explicitly submit feedback |
| Team memory sync | `api.anthropic.com/api/claude_code_teams/*` | Only for team plan users who enable it |
| File attachments | `api.anthropic.com/api/oauth/files/*` | Only when downloading shared files |

### OpenTelemetry (off by default unless you configure it)

OpenTelemetry tracing only activates when you set `OTEL_EXPORTER_OTLP_ENDPOINT`. If you haven't configured this, no OTLP data is sent anywhere. Disable explicitly with `OTEL_SDK_DISABLED=true`.

---

## What Tribunal Adds

Tribunal itself makes **no outbound network connections**. It operates entirely locally as a set of hooks and rules that intercept Claude Code's file-write and command-execution tool calls. Specifically:

- **No phone-home** — Tribunal does not contact any server
- **No telemetry** — Tribunal collects no usage data
- **No analytics** — No third-party tracking scripts
- **No update checks** — Tribunal does not check for updates over the network

The tribunal.dev website fetches the GitHub star count from `api.github.com` for display purposes only — this is standard for open-source project pages and sends no user data.

---

## Why OpenClaw Doctor Flags This

OpenClaw Doctor scans source code for outbound network endpoints and flags anything that transmits data externally. Because tribunal ships alongside the Claude Code CLI source (which includes Anthropic's telemetry infrastructure), the scanner correctly identifies these endpoints.

However:

1. **This is Anthropic's official code** — the same telemetry exists in every `@anthropic-ai/claude-code` installation from npm
2. **It respects opt-out** — all telemetry can be disabled with environment variables
3. **No code/prompts in telemetry** — analytics events contain only operational metrics (event names, error codes, platform info)
4. **Tribunal adds nothing** — all flagged endpoints originate from upstream Claude Code

---

## Recommended Setup for Privacy-Conscious Users

```bash
# Add to ~/.bashrc, ~/.zshrc, or your shell profile:

# Disable all non-essential Claude Code network traffic
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Disable OpenTelemetry (if not using a custom OTLP collector)
export OTEL_SDK_DISABLED=true
```

This leaves only the essential API calls needed for Claude to function.

---

## Verification

You can verify tribunal's network behavior yourself:

```bash
# Monitor all outbound connections while running tribunal
# macOS:
sudo nettop -p $(pgrep -f tribunal) -J bytes_in,bytes_out

# Linux:
strace -e trace=connect -f tribunal 2>&1 | grep -E 'connect\('
```

With `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` set, you should see connections only to `api.anthropic.com` for Claude API requests.

---

## Questions?

Open an issue at [github.com/thebotclub/tribunal](https://github.com/thebotclub/tribunal/issues) if you have privacy concerns or want more details about any specific network call.
