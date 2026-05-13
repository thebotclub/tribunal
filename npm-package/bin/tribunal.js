#!/usr/bin/env node
// SPDX-License-Identifier: MIT
//
// Tribunal npm launcher (v3).
//
// v3 of Tribunal is a Python-first CLI distributed via PyPI as `tribunal`.
// This npm package exists so that `npx tribunal`, `npm install -g tribunal`,
// or a `tribunal` dependency in a Node project gives the same UX as
// `pipx install tribunal` / `pip install tribunal`.
//
// Strategy on first run:
//   1. If a `tribunal` binary is already on PATH (via pipx, pip, brew, etc.)
//      we exec it directly.
//   2. Otherwise we try to bootstrap Tribunal using the user's existing
//      Python toolchain in this preference order:
//        a) `pipx install tribunal==3.0.0` — recommended, isolates deps.
//        b) `python3 -m pip install --user tribunal==3.0.0` — fallback.
//      Then we exec the freshly installed CLI.
//
// We never sudo, never modify system Python, and never silently install
// without telling the user.
//
// Set TRIBUNAL_NO_BOOTSTRAP=1 to disable auto-install and require the user
// to install manually.

"use strict";

const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");
const os = require("node:os");

const VERSION_SPEC = "tribunal==3.0.0";
const HELP_URL = "https://tribunal.dev";
const PIP_HELP = "https://pip.pypa.io/en/stable/installation/";

function which(cmd) {
  // Cross-platform `which` — returns null if not found.
  const isWin = process.platform === "win32";
  const lookup = isWin ? "where" : "which";
  try {
    const res = spawnSync(lookup, [cmd], { encoding: "utf8" });
    if (res.status === 0) {
      const first = res.stdout.split(/\r?\n/).map((s) => s.trim()).find(Boolean);
      return first || null;
    }
  } catch (_) {
    // ignore
  }
  return null;
}

function logInfo(msg) {
  process.stderr.write(`tribunal: ${msg}\n`);
}

function bootstrap() {
  if (process.env.TRIBUNAL_NO_BOOTSTRAP === "1") {
    process.stderr.write(
      [
        "tribunal: the Python CLI is not installed and TRIBUNAL_NO_BOOTSTRAP=1.",
        `tribunal: install it manually with:  pipx install ${VERSION_SPEC}`,
        `tribunal: or:  python3 -m pip install --user ${VERSION_SPEC}`,
        `tribunal: docs: ${HELP_URL}`,
      ].join("\n") + "\n",
    );
    process.exit(127);
  }

  const pipx = which("pipx");
  if (pipx) {
    logInfo(`bootstrapping with pipx → ${VERSION_SPEC} (first run only)`);
    const r = spawnSync(pipx, ["install", VERSION_SPEC], { stdio: "inherit" });
    if (r.status === 0) return true;
    logInfo("pipx install failed, falling back to pip");
  }

  const python = which("python3") || which("python");
  if (!python) {
    process.stderr.write(
      [
        "tribunal: no Python interpreter found on PATH.",
        `tribunal: install Python 3.11+ then re-run, or see ${PIP_HELP}`,
      ].join("\n") + "\n",
    );
    process.exit(127);
  }

  logInfo(`bootstrapping with ${python} -m pip install --user ${VERSION_SPEC}`);
  const r = spawnSync(python, ["-m", "pip", "install", "--user", VERSION_SPEC], {
    stdio: "inherit",
  });
  if (r.status !== 0) {
    process.stderr.write(
      [
        "tribunal: bootstrap failed.",
        `tribunal: try manually:  pipx install ${VERSION_SPEC}`,
        `tribunal: or:  ${python} -m pip install --user ${VERSION_SPEC}`,
      ].join("\n") + "\n",
    );
    process.exit(r.status || 1);
  }
  return true;
}

function exec(binary, args) {
  const child = spawn(binary, args, { stdio: "inherit" });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code == null ? 0 : code);
    }
  });
  child.on("error", (err) => {
    process.stderr.write(`tribunal: failed to launch ${binary}: ${err.message}\n`);
    process.exit(127);
  });
}

function main() {
  let cli = which("tribunal");
  if (!cli) {
    bootstrap();
    cli = which("tribunal");
  }

  if (!cli) {
    // Last-ditch: try `python -m tribunal` if the module is importable.
    const python = which("python3") || which("python");
    if (python) {
      logInfo("tribunal binary not on PATH, falling back to `python -m tribunal`");
      exec(python, ["-m", "tribunal", ...process.argv.slice(2)]);
      return;
    }
    process.stderr.write(
      [
        "tribunal: installation succeeded but the `tribunal` binary is not on PATH.",
        "tribunal: this usually means your pip user bin dir (e.g. ~/.local/bin) isn't on PATH.",
        "tribunal: add it to your shell rc and re-run, or use `pipx install tribunal`.",
      ].join("\n") + "\n",
    );
    process.exit(127);
  }

  exec(cli, process.argv.slice(2));
}

main();
