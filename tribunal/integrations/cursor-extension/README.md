# Tribunal for Cursor

A thin VS Code / Cursor extension that streams chat opens, tool calls, file saves,
and terminal lifecycle events to the local Tribunal daemon. All policy and
storage live in the daemon; this extension is purely a translator.

## Build

```bash
cd integrations/cursor-extension
npm install
npm run compile
# To produce a .vsix:
npx @vscode/vsce package
```

## Install (development)

In Cursor / VS Code:

1. `Cmd+Shift+P` -> "Developer: Install Extension from Location..."
2. Pick the `integrations/cursor-extension` folder.
3. Make sure the Tribunal daemon is running (`tribunal serve`).

## Configuration

Settings live under the `tribunal.*` namespace:

- `tribunal.daemonUrl` -- default `http://127.0.0.1:8088`
- `tribunal.token` -- bearer token; leave blank for local-only
- `tribunal.captureFileSaves` -- set to `false` to suppress file.write events

## Commands

- **Tribunal: Open Audit Dashboard** -- opens the daemon's local dashboard
- **Tribunal: Ping Daemon** -- sanity check the connection
