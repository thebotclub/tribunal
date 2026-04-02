/**
 * Audit TreeView — displays recent audit log entries from .tribunal/audit.jsonl.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

interface AuditEntry {
  ts?: string;
  hook?: string;
  tool?: string;
  allowed?: boolean;
  path?: string;
  command?: string;
  label?: string;
}

export class AuditTreeProvider implements vscode.TreeDataProvider<AuditItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<AuditItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private workspaceRoot: string) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: AuditItem): vscode.TreeItem {
    return element;
  }

  getChildren(): AuditItem[] {
    const auditPath = path.join(this.workspaceRoot, ".tribunal", "audit.jsonl");
    if (!fs.existsSync(auditPath)) {
      return [new AuditItem({ label: "No audit log yet" }, false)];
    }

    try {
      const content = fs.readFileSync(auditPath, "utf-8").trim();
      if (!content) {
        return [new AuditItem({ label: "Audit log is empty" }, false)];
      }

      const lines = content.split("\n");
      const recent = lines.slice(-30); // Last 30 entries

      const items: AuditItem[] = [];
      for (const line of recent.reverse()) {
        try {
          const entry: AuditEntry = JSON.parse(line);
          items.push(new AuditItem(entry, true));
        } catch {
          continue;
        }
      }

      if (items.length === 0) {
        return [new AuditItem({ label: "No valid entries" }, false)];
      }

      return items;
    } catch {
      return [new AuditItem({ label: "Error reading audit log" }, false)];
    }
  }
}

class AuditItem extends vscode.TreeItem {
  constructor(entry: AuditEntry, isEntry: boolean) {
    const label = isEntry
      ? `${entry.tool || "?"} — ${entry.hook || "?"}`
      : (entry.label || "");
    super(label, vscode.TreeItemCollapsibleState.None);

    if (!isEntry) {
      this.iconPath = new vscode.ThemeIcon("info");
      return;
    }

    const allowed = entry.allowed !== false;
    this.iconPath = new vscode.ThemeIcon(allowed ? "check" : "error");
    this.description = entry.ts?.replace("T", " ").replace("Z", "") || "";
    this.tooltip = `${allowed ? "Allowed" : "Blocked"}: ${entry.tool} (${entry.hook})\n${entry.path || entry.command || ""}`;
  }
}
