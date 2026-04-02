/**
 * Status bar — shows rule count and last audit event at a glance.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

export class TribunalStatus implements vscode.Disposable {
  private statusItem: vscode.StatusBarItem;

  constructor(private workspaceRoot: string) {
    this.statusItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      50,
    );
    this.statusItem.command = "tribunal.refresh";
    this.update();
    this.statusItem.show();
  }

  update(): void {
    const rulesPath = path.join(this.workspaceRoot, ".tribunal", "rules.yaml");
    const auditPath = path.join(this.workspaceRoot, ".tribunal", "audit.jsonl");

    let ruleCount = 0;
    let blocked = 0;

    // Count rules
    if (fs.existsSync(rulesPath)) {
      try {
        const content = fs.readFileSync(rulesPath, "utf-8");
        // Count top-level rule names (2-space indent + name + colon)
        const matches = content.match(/^  \S[\w-]+:\s*$/gm);
        ruleCount = matches ? matches.length : 0;
      } catch {
        // Ignore
      }
    }

    // Count blocked events
    if (fs.existsSync(auditPath)) {
      try {
        const content = fs.readFileSync(auditPath, "utf-8");
        blocked = (content.match(/"allowed":false/g) || []).length;
      } catch {
        // Ignore
      }
    }

    this.statusItem.text = `$(law) ${ruleCount} rules`;
    if (blocked > 0) {
      this.statusItem.text += ` · ${blocked} blocked`;
    }
    this.statusItem.tooltip = `Tribunal: ${ruleCount} rules active, ${blocked} events blocked`;
  }

  dispose(): void {
    this.statusItem.dispose();
  }
}
