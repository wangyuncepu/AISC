/**
 * PaneTree - immutable split-tree model for G-17 (Step 16; 03 §六).
 *
 * A Tab owns one PaneTree. Leaves are Panes that bind (or prepare to bind) a
 * Session; split nodes divide first/second with an axis + ratio. The tree is a
 * pure value: every op returns a new tree or null on rejection, never mutates,
 * and leaves the tree unchanged on any refused op (A-G17-2).
 *
 * Schema (03 §6.3 tagged union, persisted in history v2):
 *   PaneNode = SplitNode | PaneLeaf
 *   SplitNode = { kind:"split", axis:"horizontal"|"vertical", ratio:number,
 *                 first:PaneNode, second:PaneNode }
 *   PaneLeaf  = { kind:"pane", pane_id:UUID, session_type:LaunchAgent }
 *
 * Limits (03 §6.1): MAX_DEPTH=4 (root at depth 1, leaves at depth <=4), leaf
 * count <=8 per tree, ratio clamped 0.10..0.90 (default 0.50).
 */
import type { LaunchAgent, PaneLeafNode, PaneNode, PaneSplitNode, SplitAxis } from "../types";

export type { PaneLeafNode, PaneNode, PaneSplitNode, SplitAxis } from "../types";

/** Back-compat aliases (module originally defined these). */
export type SplitNode = PaneSplitNode;
export type PaneLeaf = PaneLeafNode;

export const MAX_DEPTH = 4;
export const MAX_LEAVES = 8;
export const MIN_RATIO = 0.1;
export const MAX_RATIO = 0.9;
export const DEFAULT_RATIO = 0.5;
/** Keyboard/pointer resize step (A-G17-4). */
export const RATIO_STEP = 0.05;

export function clampRatio(r: number): number {
  if (!Number.isFinite(r)) return DEFAULT_RATIO;
  return Math.min(MAX_RATIO, Math.max(MIN_RATIO, r));
}

/** Single-leaf tree (a G-08 tab has exactly this; 03 §六.1). */
export function singleLeaf(paneId: string, sessionType: LaunchAgent): PaneLeaf {
  return { kind: "pane", paneId, sessionType };
}

/** Number of leaves (resource-cap check, A-G17-6). */
export function leafCount(node: PaneNode): number {
  if (node.kind === "pane") return 1;
  return leafCount(node.first) + leafCount(node.second);
}

/** Root depth is 1; a leaf under k splits sits at depth k+1 (cap 4). */
export function depth(node: PaneNode): number {
  if (node.kind === "pane") return 1;
  return 1 + Math.max(depth(node.first), depth(node.second));
}

/** Depth of the path to a specific leaf (0 when absent). */
export function leafDepth(node: PaneNode, paneId: string): number {
  if (node.kind === "pane") return node.paneId === paneId ? 1 : 0;
  const d1 = leafDepth(node.first, paneId);
  if (d1 > 0) return d1 + 1;
  const d2 = leafDepth(node.second, paneId);
  return d2 > 0 ? d2 + 1 : 0;
}

export function contains(node: PaneNode, paneId: string): boolean {
  if (node.kind === "pane") return node.paneId === paneId;
  return contains(node.first, paneId) || contains(node.second, paneId);
}

/** All leaves, depth-first order (active/legacy resolution, 03 §6.3). */
export function listLeaves(node: PaneNode): PaneLeaf[] {
  if (node.kind === "pane") return [node];
  return [...listLeaves(node.first), ...listLeaves(node.second)];
}

export function findLeaf(node: PaneNode, paneId: string): PaneLeaf | null {
  return listLeaves(node).find((l) => l.paneId === paneId) ?? null;
}

/** First leaf in depth-first order (legacy `agent` fallback, 03 §6.3). */
export function firstLeaf(node: PaneNode): PaneLeaf | null {
  return listLeaves(node)[0] ?? null;
}

/**
 * Split the leaf `targetPaneId` into a split whose first side keeps the old
 * leaf and second side is a new leaf `newPaneId` (axis/ratio for the divider).
 * Returns null (tree unchanged) when the tree is already at capacity or the
 * target leaf sits at max depth. The size-insufficient check is a UI/store
 * concern (the leaf's measured pixels) and lives outside this pure module.
 */
export function splitLeaf(
  node: PaneNode,
  targetPaneId: string,
  newPaneId: string,
  axis: SplitAxis,
  newSessionType: LaunchAgent,
  ratio: number = DEFAULT_RATIO
): PaneNode | null {
  if (leafCount(node) >= MAX_LEAVES) return null;
  if (leafDepth(node, targetPaneId) >= MAX_DEPTH) return null;
  if (node.kind === "pane") {
    if (node.paneId !== targetPaneId) return node;
    const newLeaf: PaneLeaf = { kind: "pane", paneId: newPaneId, sessionType: newSessionType };
    return { kind: "split", axis, ratio: clampRatio(ratio), first: node, second: newLeaf };
  }
  const first = splitLeaf(node.first, targetPaneId, newPaneId, axis, newSessionType, ratio);
  if (first === null) return null; // capacity/depth refusal inside -> propagate
  if (first !== node.first) return { ...node, first };
  const second = splitLeaf(node.second, targetPaneId, newPaneId, axis, newSessionType, ratio);
  if (second === null) return null;
  if (second !== node.second) return { ...node, second };
  return node;
}

/**
 * Remove a leaf; when a split is left with one child the split collapses to
 * the remaining sibling (03 §6.1 "父 Split 压缩为剩余兄弟"). Returns null only
 * when the last leaf is removed - the store then keeps the tab as a single
 * dormant leaf (03 §6.1). Tree is unchanged if the pane is absent.
 */
export function removeLeaf(node: PaneNode, paneId: string): PaneNode | null {
  if (node.kind === "pane") return node.paneId === paneId ? null : node;
  const first = removeLeaf(node.first, paneId);
  const second = removeLeaf(node.second, paneId);
  if (first === null) return second; // left subtree collapsed entirely
  if (second === null) return first;
  const out: SplitNode = { ...node, first, second };
  if (first !== node.first || second !== node.second) return out;
  return node;
}

/**
 * Unique, stable key for a split node = its leaf pane ids (sorted). Dividers
 * are rendered per split and adjust ratio via this key (setRatioBySplitKey).
 * Pane ids are unique UUIDs, so keys are unique across the tree.
 */
export function splitKey(node: SplitNode): string {
  return listLeaves(node)
    .map((l) => l.paneId)
    .sort()
    .join(",");
}

/** Clamp + set the ratio of the split matching `key`; tree unchanged if absent. */
export function setRatioBySplitKey(node: PaneNode, key: string, ratio: number): PaneNode {
  if (node.kind === "pane") return node;
  if (splitKey(node) === key) return { ...node, ratio: clampRatio(ratio) };
  const first = setRatioBySplitKey(node.first, key, ratio);
  if (first !== node.first) return { ...node, first };
  const second = setRatioBySplitKey(node.second, key, ratio);
  if (second !== node.second) return { ...node, second };
  return node;
}

/** All split keys in the tree, depth-first (for divider rendering). */
export function listSplitKeys(node: PaneNode): string[] {
  if (node.kind === "pane") return [];
  return [splitKey(node), ...listSplitKeys(node.first), ...listSplitKeys(node.second)];
}

// --- G-17 (Step 16): spatial pane navigation (Ctrl+arrows / hjkl) ---

export type NavDir = "left" | "right" | "up" | "down";

/** Map hjkl to a direction (vim: h left, j down, k up, l right). */
export function hjklToDir(key: string): NavDir | null {
  switch (key) {
    case "h":
      return "left";
    case "j":
      return "down";
    case "k":
      return "up";
    case "l":
      return "right";
    default:
      return null;
  }
}

/**
 * The pane to move focus to from `paneId` in `dir`, or null when there is no
 * neighbor (the focus stays). Walks from the leaf up: the first ancestor split
 * whose axis matches the direction and whose sibling contains a target subtree
 * yields that subtree's first leaf (depth-first).
 */
export function navigateLeaf(node: PaneNode, paneId: string, dir: NavDir): string | null {
  const horizontal = dir === "left" || dir === "right";
  const moveFromSecond = dir === "left" || dir === "up";
  let found: string | null = null;
  const walk = (n: PaneNode): "found" | "stop" | "none" => {
    if (n.kind === "pane") {
      return n.paneId === paneId ? "found" : "none";
    }
    const axisOk = horizontal ? n.axis === "horizontal" : n.axis === "vertical";
    const inFirst = contains(n.first, paneId);
    const inSecond = contains(n.second, paneId);
    if (inFirst) {
      if (axisOk && !moveFromSecond) {
        found = firstLeaf(n.second)?.paneId ?? null;
        return "stop";
      }
      return walk(n.first);
    }
    if (inSecond) {
      if (axisOk && moveFromSecond) {
        found = firstLeaf(n.first)?.paneId ?? null;
        return "stop";
      }
      return walk(n.second);
    }
    return "none";
  };
  walk(node);
  return found;
}

export interface ValidationResult {
  ok: boolean;
  reasons: string[];
}

/** 03 §6.3: illegal kind/axis, non-finite ratio, duplicate pane IDs, depth >4,
 * leaves >8 or an empty tree invalidate a persisted tree. */
export function validateTree(node: PaneNode): ValidationResult {
  const reasons: string[] = [];
  if (node.kind === "split") {
    if (node.axis !== "horizontal" && node.axis !== "vertical") reasons.push("bad axis");
    if (!Number.isFinite(node.ratio) || node.ratio < MIN_RATIO || node.ratio > MAX_RATIO) {
      reasons.push("ratio out of range");
    }
  }
  const leaves = listLeaves(node);
  if (leaves.length === 0) reasons.push("empty tree");
  if (leaves.length > MAX_LEAVES) reasons.push(`>${MAX_LEAVES} leaves`);
  if (depth(node) > MAX_DEPTH) reasons.push(`depth >${MAX_DEPTH}`);
  const seen = new Set<string>();
  for (const l of leaves) {
    if (seen.has(l.paneId)) reasons.push("duplicate pane id");
    seen.add(l.paneId);
  }
  return { ok: reasons.length === 0, reasons };
}
