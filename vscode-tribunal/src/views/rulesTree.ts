/**
 * Rules TreeView — displays .tribunal/rules.yaml rules in the sidebar.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

interface RuleDef {
  trigger?: string;
  action?: string;
  message?: string;
  enabled?: boolean;
  condition?: string;
  match?: { tool?: string; path?: string };
  require_tool?: boolean;
}

export class RulesTreeProvider implements vscode.TreeDataProvider<RuleItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<RuleItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private workspaceRoot: string) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: RuleItem): vscode.TreeItem {
    return element;
  }

  getChildren(): RuleItem[] {
    const rulesPath = path.join(this.workspaceRoot, ".tribunal", "rules.yaml");
    if (!fs.existsSync(rulesPath)) {
      return [new RuleItem("No rules.yaml found — run: tribunal init", "", "", false)];
    }

    try {
      const content = fs.readFileSync(rulesPath, "utf-8");
      // Simple YAML parsing for rules (avoids dependency on yaml package)
      const items: RuleItem[] = [];
      const rules = this.parseRulesYaml(content);

      for (const [name, def] of Object.entries(rules)) {
        const enabled = def.enabled !== false;
        const action = def.action || "block";
        const trigger = def.trigger || "PreToolUse";
        const message = def.message || "";
        items.push(new RuleItem(name, action, trigger, enabled, message));
      }

      return items.length > 0
        ? items
        : [new RuleItem("No rules defined", "", "", false)];
    } catch {
      return [new RuleItem("Error reading rules.yaml", "", "", false)];
    }
  }

  private parseRulesYaml(content: string): Record<string, RuleDef> {
    // Minimal YAML parser for rules section — works for standard tribunal configs
    const rules: Record<string, RuleDef> = {};
    let inRules = false;
    let currentRule = "";

    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (trimmed === "rules:") {
        inRules = true;
        continue;
      }
      if (!inRules) continue;

      // Top-level key in rules section (2-space indent)
      const ruleMatch = line.match(/^  (\S[\w-]+):\s*$/);
      if (ruleMatch) {
        currentRule = ruleMatch[1];
        rules[currentRule] = {};
        continue;
      }

      // Properties of current rule (4-space indent)
      if (currentRule) {
        const propMatch = line.match(/^\s{4,}(\w+):\s*(.+)$/);
        if (propMatch) {
          const [, key, value] = propMatch;
          const def = rules[currentRule];
          if (key === "trigger") def.trigger = value.trim();
          else if (key === "action") def.action = value.trim();
          else if (key === "message") def.message = value.replace(/^["']|["']$/g, "").trim();
          else if (key === "enabled") def.enabled = value.trim() !== "false";
          else if (key === "condition") def.condition = value.trim();
        }
      }
    }

    return rules;
  }
}

class RuleItem extends vscode.TreeItem {
  constructor(
    public readonly name: string,
    private action: string,
    private trigger: string,
    private enabled: boolean,
    private message: string = "",
  ) {
    super(name, vscode.TreeItemCollapsibleState.None);

    if (!action) {
      // Info/placeholder item
      this.iconPath = new vscode.ThemeIcon("info");
      return;
    }

    const icon = action === "block" ? "error" : action === "warn" ? "warning" : "info";
    this.iconPath = new vscode.ThemeIcon(enabled ? icon : "circle-slash");

    this.description = `${action} on ${trigger}`;
    this.tooltip = this.message || `${name}: ${action} on ${trigger}`;
  }
}
