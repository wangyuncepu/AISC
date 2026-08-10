/**
 * Window title computation (G-15, Step 14; 02 §六 F-5).
 *
 * Pure function - the frontend watches the active context (workspace / active
 * tab) and calls `getCurrentWindow().setTitle()` only when it changes; no
 * polling (F-5 rule). Priority (single-session-per-tab model; pane-aware once
 * Step 16 lands):
 *
 * 1. active tab has a Session type  -> `<workspace> · <Session type> · AISC Workbench`
 * 2. workspace chosen, no session   -> `<workspace> · AISC Workbench`
 * 3. otherwise                      -> `AISC Workbench`
 *
 * Session type = the agent (Claude/Codex/Bash/cc-switch), never provider/model
 * (F-5 rule). A tab whose state is `idle` (never opened) has no session leaf,
 * so it falls through to the workspace/product title - no stale type (A-G15-2
 * "空 tree 不显示旧 type").
 */
import { AGENT_TITLE } from "../stores/tabLayout";
import type { LaunchAgent } from "../types";

export const PRODUCT_TITLE = "AISC Workbench";

/** Max grapheme count before truncation (A-G15-3). */
export const MAX_WORKSPACE_GRAPHEMES = 40;
/** Keep the first and last N graphemes when truncating (A-G15-3). */
const KEEP_EDGES = 18;

export interface TitleContext {
  /** Canonical workspace path ("" when none chosen). */
  workspace: string;
  /** Active tab's Session type (agent), or null when the active tab has no
   * session leaf (no active tab, or the tab is idle/never opened). */
  sessionType: LaunchAgent | null;
}

/** Cross-separator basename: strips trailing `/`/`\`, takes the last segment.
 * Drive root `C:\` -> `C:` (trailing separator removed, nothing left to split). */
export function workspaceBasename(workspace: string): string {
  const trimmed = workspace.trim();
  if (!trimmed) return "";
  const stripped = trimmed.replace(/[\\/]+$/, "");
  const parts = stripped.split(/[\\/]/);
  const name = parts[parts.length - 1] ?? "";
  return truncateGraphemes(name);
}

/** Truncate to <=40 graphemes keeping first/last 18 with `…` between; grapheme
 * clusters (CJK, emoji, combining marks) are never split mid-cluster (A-G15-3). */
export function truncateGraphemes(s: string): string {
  let graphemes: string[];
  try {
    const seg = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    graphemes = [...seg.segment(s)].map((x) => x.segment);
  } catch {
    graphemes = [...s]; // fallback: codepoint-level
  }
  if (graphemes.length <= MAX_WORKSPACE_GRAPHEMES) return s;
  const head = graphemes.slice(0, KEEP_EDGES).join("");
  const tail = graphemes.slice(-KEEP_EDGES).join("");
  return `${head}…${tail}`;
}

/** The full window title (F-5 priority). Pure and unit-testable. */
export function computeWindowTitle(ctx: TitleContext): string {
  const ws = workspaceBasename(ctx.workspace);
  if (ctx.sessionType && ws) return `${ws} · ${AGENT_TITLE[ctx.sessionType]} · ${PRODUCT_TITLE}`;
  if (ctx.sessionType) return `${AGENT_TITLE[ctx.sessionType]} · ${PRODUCT_TITLE}`; // workspace-less (defensive)
  if (ws) return `${ws} · ${PRODUCT_TITLE}`;
  return PRODUCT_TITLE;
}
