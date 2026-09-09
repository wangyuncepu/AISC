/**
 * Panel layout (FIX-3, 2026-09-09): user-resizable / collapsible panel
 * geometry — Explorer dock width + collapse, TabBar height.
 *
 * Module-level reactive state (theme.ts pattern): WorkspaceView remounts per
 * workspace (keyed by runtime id) so component-local state would be lost on
 * workspace switch. Persisted to localStorage (NOT the settings chain): this
 * is local UI geometry, loss falls back to defaults harmlessly — same class
 * of state as the theme render hint, and it avoids the settings doc's
 * revision-locked explicit-save flow (drag-to-size must stick immediately).
 */

import { reactive } from "vue";

export interface PanelLayout {
  /** Explorer dock width in LAYOUT px (the zoom-invariant domain; rendering
   * multiplies by the .app scale). */
  explorerWidth: number;
  /** true = dock collapsed to the 40px rail (VS Code-style). */
  explorerCollapsed: boolean;
  /** TabBar height in px; null = natural auto height (no explicit style). */
  tabbarHeight: number | null;
}

const CACHE_KEY = "aisc-wb-panel-layout-v1";

const DEFAULTS: PanelLayout = {
  explorerWidth: 320,
  explorerCollapsed: false,
  tabbarHeight: null,
};

export const EXPLORER_MIN_W = 240;
export const EXPLORER_MAX_W = 600;
/** Natural bar height is ~39px (32px control + 2×3px padding + 1px border);
 * below 40 the forced `overflow-x:auto` turns into a vertical scrollbar. */
export const TABBAR_MIN_H = 40;
export const TABBAR_MAX_H = 120;
export const EXPLORER_COLLAPSED_W = 40;

export function clampExplorerWidth(px: number): number {
  if (!Number.isFinite(px)) return DEFAULTS.explorerWidth;
  return Math.min(EXPLORER_MAX_W, Math.max(EXPLORER_MIN_W, Math.round(px)));
}

export function clampTabbarHeight(px: number | null): number | null {
  if (px == null || !Number.isFinite(px)) return null;
  return Math.min(TABBAR_MAX_H, Math.max(TABBAR_MIN_H, Math.round(px)));
}

/** Visual px per layout px — the `.app` zoom factor. Derived (never read
 * from ui.font_scale: the effective scale is clamped by window size in
 * App.vue). Same formula as TabBar.placeMenu; engine-neutral because `.app`
 * width is `calc(100vw / scale)`, so offsetWidth divides out exactly. */
export function appScale(): number {
  if (typeof window === "undefined" || typeof document === "undefined") return 1;
  const app = document.querySelector(".app");
  const w = (app as HTMLElement | null)?.offsetWidth ?? 0;
  if (!w) return 1;
  const s = window.innerWidth / w;
  return Number.isFinite(s) && s > 0 ? s : 1;
}

function readPersisted(): PanelLayout {
  try {
    if (typeof window === "undefined") return { ...DEFAULTS };
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return { ...DEFAULTS };
    const data = JSON.parse(raw) as Partial<PanelLayout>;
    return {
      explorerWidth: clampExplorerWidth(
        typeof data.explorerWidth === "number" ? data.explorerWidth : DEFAULTS.explorerWidth),
      explorerCollapsed: data.explorerCollapsed === true,
      tabbarHeight: clampTabbarHeight(
        typeof data.tabbarHeight === "number" ? data.tabbarHeight : null),
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function persist(): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(CACHE_KEY, JSON.stringify({ ...panelLayout }));
  } catch {
    /* storage unavailable (e.g. sandboxed): best-effort */
  }
}

/** Live panel geometry — components bind to this (module singleton). */
export const panelLayout = reactive<PanelLayout>(readPersisted());

export function setExplorerWidth(px: number): void {
  panelLayout.explorerWidth = clampExplorerWidth(px);
  persist();
}

export function setExplorerCollapsed(collapsed: boolean): void {
  panelLayout.explorerCollapsed = collapsed;
  persist();
}

export function toggleExplorerCollapsed(): void {
  setExplorerCollapsed(!panelLayout.explorerCollapsed);
}

export function setTabbarHeight(px: number | null): void {
  panelLayout.tabbarHeight = clampTabbarHeight(px);
  persist();
}
