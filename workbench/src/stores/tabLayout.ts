/**
 * Pure tab-layout helpers (02 §2.3, A-INFRA-1).
 *
 * Restore input is the complete `layout.tabs[]` (TabRecord list), never an
 * agent list: records are rebuilt one-by-one preserving duplicates and order,
 * with a saved tab_id → new tab_id map for the active-tab mapping. No
 * agent-based `.find()` dedup.
 */
import type {
  LaunchAgent,
  PaneLeafNode,
  PaneNode,
  PaneRuntime,
  PersistedPaneNode,
  SplitLayout,
  Tab,
  TabRecord,
} from "../types";
import { singleLeaf } from "./paneTree";

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

// --- G-17 (Step 16): persisted (snake_case) <-> in-memory (camelCase) trees ---

/** Convert a persisted split_layout tree to the in-memory PaneNode. */
export function persistedToInternal(node: PersistedPaneNode): PaneNode {
  if (node.kind === "pane") {
    return { kind: "pane", paneId: node.pane_id, sessionType: node.session_type };
  }
  return {
    kind: "split",
    axis: node.axis,
    ratio: node.ratio,
    first: persistedToInternal(node.first),
    second: persistedToInternal(node.second),
  };
}

/** Convert an in-memory PaneNode to the persisted snake_case form. */
export function internalToPersisted(node: PaneNode): PersistedPaneNode {
  if (node.kind === "pane") {
    return { kind: "pane", pane_id: node.paneId, session_type: node.sessionType };
  }
  return {
    kind: "split",
    axis: node.axis,
    ratio: node.ratio,
    first: internalToPersisted(node.first),
    second: internalToPersisted(node.second),
  };
}

function emptyPanes(tree: PaneNode): Record<string, PaneRuntime> {
  const panes: Record<string, PaneRuntime> = {};
  const walk = (n: PaneNode): void => {
    if (n.kind === "pane") panes[n.paneId] = { sessionId: null, sessionState: "idle", exit: null };
    else {
      walk(n.first);
      walk(n.second);
    }
  };
  walk(tree);
  return panes;
}

/** Build a fresh Tab with the pane model. `splitLayout` (persisted, history
 * v2) is restored into an in-memory tree; absent -> a single-leaf tree whose
 * pane shares the tab's UUID (a G-08 flat tab). */
export function newPaneTab(
  tabId: string,
  agent: LaunchAgent,
  title: string,
  savedTabId: string | null,
  splitLayout?: SplitLayout | null
): Tab {
  const tree = splitLayout ? persistedToInternal(splitLayout.root) : singleLeaf(tabId, agent);
  // Active pane: the persisted id when it is a leaf, else the DFS-first leaf.
  const savedActive = splitLayout?.active_pane_id ?? null;
  const activePaneId =
    savedActive && findPane(tree, savedActive)
      ? savedActive
      : tree.kind === "pane"
        ? tree.paneId
        : firstPane(tree).paneId;
  // Derive BOTH agent and title from the active leaf, never from the persisted
  // flat record alone: a split's history `title` may predate the split (saved
  // before the 300ms debounce flushed), leaving the tab bar on the old agent
  // while the window title (from `agent`) showed the new one (G-17 feedback
  // 2026-08-10). The persisted title is only a fallback for unknown agents.
  const activeType = findPane(tree, activePaneId)?.sessionType ?? agent;
  return {
    tabId,
    agent: activeType,
    title: AGENT_TITLE[activeType] ?? title,
    sessionId: null,
    sessionState: "idle",
    exit: null,
    savedTabId,
    tree,
    activePaneId,
    panes: emptyPanes(tree),
  };
}

function firstPane(n: PaneNode): PaneLeafNode {
  if (n.kind === "pane") return n;
  return firstPane(n.first);
}

function findPane(n: PaneNode, paneId: string): PaneLeafNode | null {
  if (n.kind === "pane") return n.paneId === paneId ? n : null;
  return findPane(n.first, paneId) ?? findPane(n.second, paneId);
}

/**
 * Build per-record tabs. Every record produces exactly one tab; duplicate
 * session types are kept (A-INFRA-1 regression: the old restore deduped via
 * `tabs.find(t => t.agent === agent)`). G-17: each tab carries its restored
 * split tree (single leaf when the record has no split_layout).
 */
export function tabsFromRecords(
  records: TabRecord[]
): { tabs: Tab[]; bySavedId: Map<string, string> } {
  const tabs: Tab[] = [];
  const bySavedId = new Map<string, string>();
  for (const rec of records) {
    const tabId = newTabId();
    tabs.push(
      newPaneTab(tabId, rec.agent, rec.title || AGENT_TITLE[rec.agent], rec.tab_id ?? null, rec.split_layout)
    );
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
