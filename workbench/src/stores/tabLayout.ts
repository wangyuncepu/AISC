/**
 * Pure tab-layout helpers (02 §2.3, A-INFRA-1).
 *
 * Restore input is the complete `layout.tabs[]` (TabRecord list), never an
 * agent list: records are rebuilt one-by-one preserving duplicates and order,
 * with a saved tab_id → new tab_id map for the active-tab mapping. No
 * agent-based `.find()` dedup.
 */
import type { LaunchAgent, Tab, TabRecord } from "../types";

/** Platform check evaluated per call so unit tests can stub `navigator`. */
function isWin(): boolean {
  return typeof navigator !== "undefined" && /win/i.test(navigator.userAgent ?? "");
}

/**
 * Normalize a workspace path for history keying and restore matching (G-07
 * refinement): on Windows forward slashes become backslashes and trailing
 * separators are stripped (drive root `C:\` kept); elsewhere only trailing
 * `/` is stripped. Case is preserved - matching is case-insensitive on
 * Windows via `sameWorkspace`, never in the stored key.
 */
export function normalizePath(p: string): string {
  const win = isWin();
  let s = p.trim();
  if (win) s = s.replace(/\//g, "\\");
  const sep = win ? "\\" : "/";
  while (s.length > (win ? 3 : 1) && s.endsWith(sep)) s = s.slice(0, -1);
  return s;
}

/**
 * Whether two workspace paths refer to the same directory. The restore-layout
 * lookup keys history on the stored record path but the user may type or pick
 * the workspace in any slash/case form - compare normalized forms
 * (case-insensitively on Windows, where the filesystem is case-insensitive).
 */
export function sameWorkspace(a: string, b: string): boolean {
  const na = normalizePath(a);
  const nb = normalizePath(b);
  return isWin() ? na.toLowerCase() === nb.toLowerCase() : na === nb;
}

export const AGENT_TITLE: Record<LaunchAgent, string> = {
  claude: "Claude",
  codex: "Codex",
  bash: "Bash",
  "cc-switch": "cc-switch",
};

/** All creatable session types (G-08 + menu order). */
export const AGENTS: LaunchAgent[] = ["claude", "codex", "bash", "cc-switch"];

function newTabId(): string {
  return crypto.randomUUID();
}

/**
 * Build per-record tabs. Every record produces exactly one tab; duplicate
 * session types are kept (A-INFRA-1 regression: the old restore deduped via
 * `tabs.find(t => t.agent === agent)`).
 */
export function tabsFromRecords(
  records: TabRecord[]
): { tabs: Tab[]; bySavedId: Map<string, string> } {
  const tabs: Tab[] = [];
  const bySavedId = new Map<string, string>();
  for (const rec of records) {
    const tabId = newTabId();
    tabs.push({
      tabId,
      agent: rec.agent,
      title: rec.title || AGENT_TITLE[rec.agent],
      sessionId: null,
      sessionState: "idle",
      exit: null,
      savedTabId: rec.tab_id ?? null,
    });
    if (rec.tab_id) bySavedId.set(rec.tab_id, tabId);
  }
  return { tabs, bySavedId };
}

/**
 * Active tab resolution: saved active tab_id → new id (restore); otherwise the
 * tab matching `activeAgent` (fresh start); otherwise the first tab; null when
 * there are no tabs.
 */
export function resolveActiveTabId(
  tabs: Tab[],
  bySavedId: Map<string, string>,
  opts: { activeSavedId?: string | null; activeAgent?: LaunchAgent | null } = {}
): string | null {
  if (opts.activeSavedId) {
    const mapped = bySavedId.get(opts.activeSavedId);
    if (mapped) return mapped;
  }
  if (opts.activeAgent) {
    const byAgent = tabs.find((t) => t.agent === opts.activeAgent);
    if (byAgent) return byAgent.tabId;
  }
  return tabs[0]?.tabId ?? null;
}
