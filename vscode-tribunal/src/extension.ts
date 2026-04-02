/**
 * Tribunal VS Code Extension — main entry point.
 *
 * Provides:
 * - Activity bar with Rules/Audit/Agents/Cost tree views
 * - Status bar showing rule count and last audit event
 * - File watcher for auto-refresh on .tribunal/ changes
 * - Commands: refresh, doctor, init, rotate, validate
 */

import * as vscode from "vscode";
import { RulesTreeProvider } from "./views/rulesTree";
import { AuditTreeProvider } from "./views/auditTree";
import { AgentsTreeProvider } from "./views/agentsTree";
import { CostTreeProvider } from "./views/costTree";
import { TribunalStatus } from "./statusBar";

let statusBar: TribunalStatus;

export function activate(context: vscode.ExtensionContext) {
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspaceRoot) return;

  // Tree view providers
  const rulesProvider = new RulesTreeProvider(workspaceRoot);
  const auditProvider = new AuditTreeProvider(workspaceRoot);
  const agentsProvider = new AgentsTreeProvider(workspaceRoot);
  const costProvider = new CostTreeProvider(workspaceRoot);

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("tribunal.rules", rulesProvider),
    vscode.window.registerTreeDataProvider("tribunal.audit", auditProvider),
    vscode.window.registerTreeDataProvider("tribunal.agents", agentsProvider),
    vscode.window.registerTreeDataProvider("tribunal.cost", costProvider),
  );

  // Status bar
  statusBar = new TribunalStatus(workspaceRoot);
  context.subscriptions.push(statusBar);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand("tribunal.refresh", () => {
      rulesProvider.refresh();
      auditProvider.refresh();
      agentsProvider.refresh();
      costProvider.refresh();
      statusBar.update();
    }),

    vscode.commands.registerCommand("tribunal.doctor", async () => {
      const terminal = vscode.window.createTerminal("Tribunal Doctor");
      terminal.sendText("tribunal doctor");
      terminal.show();
    }),

    vscode.commands.registerCommand("tribunal.initProject", async () => {
      const terminal = vscode.window.createTerminal("Tribunal Init");
      terminal.sendText("tribunal init");
      terminal.show();
    }),

    vscode.commands.registerCommand("tribunal.rotateAudit", async () => {
      const terminal = vscode.window.createTerminal("Tribunal");
      terminal.sendText("tribunal audit rotate");
      terminal.show();
    }),

    vscode.commands.registerCommand("tribunal.validateConfig", async () => {
      const terminal = vscode.window.createTerminal("Tribunal");
      terminal.sendText("tribunal config validate");
      terminal.show();
    }),
  );

  // File watcher for auto-refresh
  const config = vscode.workspace.getConfiguration("tribunal");
  if (config.get<boolean>("autoRefresh", true)) {
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(workspaceRoot, ".tribunal/**"),
    );
    watcher.onDidChange(() => vscode.commands.executeCommand("tribunal.refresh"));
    watcher.onDidCreate(() => vscode.commands.executeCommand("tribunal.refresh"));
    watcher.onDidDelete(() => vscode.commands.executeCommand("tribunal.refresh"));
    context.subscriptions.push(watcher);
  }
}

export function deactivate() {
  // Cleanup handled by disposables
}
