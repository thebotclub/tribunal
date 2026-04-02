/**
 * Cost TreeView — displays cost and budget info from .tribunal/state.json.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

export class CostTreeProvider implements vscode.TreeDataProvider<CostItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<CostItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private workspaceRoot: string) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: CostItem): vscode.TreeItem {
    return element;
  }

  getChildren(): CostItem[] {
    const statePath = path.join(this.workspaceRoot, ".tribunal", "state.json");
    if (!fs.existsSync(statePath)) {
      return [new CostItem("No cost data", "info", "")];
    }

    try {
      const state = JSON.parse(fs.readFileSync(statePath, "utf-8"));
      const items: CostItem[] = [];

      // Session cost
      const sessionCost = state.session_cost_usd || 0;
      items.push(new CostItem(
        `Session: $${sessionCost.toFixed(4)}`,
        sessionCost > 0 ? "credit-card" : "circle-outline",
        "",
      ));

      // Budget
      const budget = state.budget || {};
      if (budget.session_usd) {
        const pct = ((sessionCost / budget.session_usd) * 100).toFixed(0);
        const icon = sessionCost >= budget.session_usd ? "error" : "info";
        items.push(new CostItem(
          `Budget: $${budget.session_usd.toFixed(2)} (${pct}% used)`,
          icon,
          "",
        ));
      }

      // Token counts
      const inputTokens = state.input_tokens || 0;
      const outputTokens = state.output_tokens || 0;
      if (inputTokens > 0 || outputTokens > 0) {
        items.push(new CostItem(
          `Tokens: ${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out`,
          "symbol-number",
          "",
        ));
      }

      // Model
      if (state.model) {
        items.push(new CostItem(`Model: ${state.model}`, "symbol-class", ""));
      }

      // Compaction count
      if (state.compaction_count) {
        items.push(new CostItem(
          `Compactions: ${state.compaction_count}`,
          "fold",
          "",
        ));
      }

      return items;
    } catch {
      return [new CostItem("Error reading state", "warning", "")];
    }
  }
}

class CostItem extends vscode.TreeItem {
  constructor(label: string, icon: string, description: string) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.iconPath = new vscode.ThemeIcon(icon);
    this.description = description;
  }
}
