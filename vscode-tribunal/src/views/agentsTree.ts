/**
 * Agents TreeView — displays active and completed agents from .tribunal/state.json.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

interface AgentState {
  agent_type?: string;
  started_at?: string;
  stopped_at?: string;
  cost_usd?: number;
  tool_calls?: number;
}

export class AgentsTreeProvider implements vscode.TreeDataProvider<AgentItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<AgentItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private workspaceRoot: string) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: AgentItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: AgentItem): AgentItem[] {
    if (element) return [];

    const statePath = path.join(this.workspaceRoot, ".tribunal", "state.json");
    if (!fs.existsSync(statePath)) {
      return [new AgentItem("No agent data", "info", "")];
    }

    try {
      const state = JSON.parse(fs.readFileSync(statePath, "utf-8"));
      const items: AgentItem[] = [];

      // Active agents
      const active = state.active_agents || {};
      for (const [id, info] of Object.entries(active) as [string, AgentState][]) {
        items.push(new AgentItem(
          `🟢 ${id}`,
          "play",
          `${info.agent_type || "agent"} — $${(info.cost_usd || 0).toFixed(4)}`,
          `Started: ${info.started_at || "?"}\nTools: ${info.tool_calls || 0}`,
        ));
      }

      // Recent completed agents (last 5)
      const completed = (state.completed_agents || []).slice(-5);
      for (const info of completed as AgentState[]) {
        items.push(new AgentItem(
          `⚫ ${(info as any).agent_id || "agent"}`,
          "circle-slash",
          `$${(info.cost_usd || 0).toFixed(4)}`,
          `${info.started_at || ""} → ${info.stopped_at || ""}`,
        ));
      }

      return items.length > 0
        ? items
        : [new AgentItem("No agents tracked yet", "info", "")];
    } catch {
      return [new AgentItem("Error reading state", "warning", "")];
    }
  }
}

class AgentItem extends vscode.TreeItem {
  constructor(
    label: string,
    icon: string,
    description: string,
    tooltip?: string,
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.iconPath = new vscode.ThemeIcon(icon);
    this.description = description;
    if (tooltip) this.tooltip = tooltip;
  }
}
