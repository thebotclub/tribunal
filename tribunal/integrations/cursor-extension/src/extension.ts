/**
 * Tribunal for Cursor — VS Code / Cursor extension.
 *
 * Subscribes to the editor events Cursor surfaces and streams them to the
 * local Tribunal daemon. The extension does NOT implement policy or
 * blocking — those live in the daemon. Its only job is to faithfully
 * report what Cursor is doing.
 *
 * The matching translator on the Python side is tribunal.adapters.cursor.
 * Wire format: POST /v1/event with `{type, ...}` plus optional metadata.
 */

import * as vscode from "vscode";

// ── Config ──────────────────────────────────────────────────────────────────

interface Config {
  daemonUrl: string;
  token: string;
  captureFileSaves: boolean;
}

function readConfig(): Config {
  const cfg = vscode.workspace.getConfiguration("tribunal");
  return {
    daemonUrl: cfg.get<string>("daemonUrl") ?? "http://127.0.0.1:8088",
    token: cfg.get<string>("token") ?? "",
    captureFileSaves: cfg.get<boolean>("captureFileSaves") ?? true,
  };
}

// ── Wire ────────────────────────────────────────────────────────────────────

async function emit(payload: Record<string, unknown>): Promise<void> {
  const cfg = readConfig();
  const url = `${cfg.daemonUrl.replace(/\/$/, "")}/v1/event`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (cfg.token) headers["Authorization"] = `Bearer ${cfg.token}`;
  try {
    // Cursor extension host = Node, fetch is available 18+.
    await fetch(url, { method: "POST", headers, body: JSON.stringify(payload) });
  } catch (err) {
    // The daemon may be offline. Don't surface noise to the user.
    console.warn("[tribunal] daemon unreachable:", err);
  }
}

function metadata(): Record<string, unknown> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  return {
    cursor_version: vscode.version,
    workspace_root: folders[0]?.uri.fsPath ?? process.cwd(),
    session_id: `cursor-${Math.floor(Date.now() / 1000)}`,
  };
}

// ── Activate ────────────────────────────────────────────────────────────────

export function activate(ctx: vscode.ExtensionContext): void {
  console.log("[tribunal] extension active; daemon =", readConfig().daemonUrl);

  // Session start
  void emit({ type: "chat.open", ...metadata() });

  // File saves
  ctx.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      if (!readConfig().captureFileSaves) return;
      await emit({
        type: "file.save",
        path: doc.uri.fsPath,
        size: doc.getText().length,
        language: doc.languageId,
        ...metadata(),
      });
    }),
  );

  // Document changes — sampled, not every keystroke. We summarise per
  // editor activation rather than per character to keep volume sane.
  let lastActiveDoc = "";
  ctx.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(async (editor) => {
      const path = editor?.document.uri.fsPath ?? "";
      if (path && path !== lastActiveDoc) {
        lastActiveDoc = path;
        await emit({
          type: "tool.call",
          tool: "read_file",
          args: { path },
          ...metadata(),
        });
      }
    }),
  );

  // Terminal lifecycle
  ctx.subscriptions.push(
    vscode.window.onDidOpenTerminal(async (term) => {
      await emit({
        type: "tool.call",
        tool: "shell",
        args: { name: term.name },
        ...metadata(),
      });
    }),
  );

  // Commands
  ctx.subscriptions.push(
    vscode.commands.registerCommand("tribunal.openDashboard", async () => {
      const url = readConfig().daemonUrl;
      void vscode.env.openExternal(vscode.Uri.parse(url));
    }),
    vscode.commands.registerCommand("tribunal.ping", async () => {
      const cfg = readConfig();
      try {
        const r = await fetch(`${cfg.daemonUrl.replace(/\/$/, "")}/v1/health`);
        const body = await r.json();
        void vscode.window.showInformationMessage(
          `Tribunal daemon ${body.version} — ${body.events} events`,
        );
      } catch (err) {
        void vscode.window.showErrorMessage(`Tribunal daemon unreachable: ${err}`);
      }
    }),
  );
}

export function deactivate(): void {
  void emit({ type: "chat.close", reason: "deactivate", ...metadata() });
}
