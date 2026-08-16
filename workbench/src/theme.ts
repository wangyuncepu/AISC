/**
 * Theme (G-04, Step 17; 02 §3.5): `system | dark | light` mode, resolved to an
 * effective `dark | light` that drives the DOM `data-theme` / `color-scheme`
 * and the xterm palette.
 *
 * - `system` follows `prefers-color-scheme` (listener, single instance).
 * - A fixed `dark`/`light` wins over the system and stops reacting to it.
 * - The resolved value is cached in localStorage so `index.html` can paint the
 *   correct theme BEFORE the bundle loads (A-G04-2: no dark/light flash).
 * - Only DOM tokens / xterm options change on switch - never a Session/PTY.
 */

import { ref } from "vue";

export type ThemeMode = "system" | "dark" | "light";
export type EffectiveTheme = "dark" | "light";

export const THEME_MODES: readonly ThemeMode[] = ["system", "dark", "light"] as const;

/** localStorage key holding the last resolved effective theme (a render hint,
 * not the mode - the mode lives in the settings file). */
const CACHE_KEY = "aisc-wb-theme";

/** Lazy access so tests can stub `matchMedia` before first use. */
function getMediaQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
}

/** Current system color-scheme preference (dark-first default). */
export function systemDark(): boolean {
  return getMediaQuery()?.matches ?? true;
}

/** Resolve a mode against the system preference. Unknown/falsy => `system`. */
export function resolveTheme(mode: ThemeMode | string | null | undefined, sysDark: boolean): EffectiveTheme {
  if (mode === "dark") return "dark";
  if (mode === "light") return "light";
  return sysDark ? "dark" : "light";
}

/** Reactive effective theme - the xterm palette / any consumer watches this. */
export const effectiveTheme = ref<EffectiveTheme>("dark");

export function readCachedTheme(): EffectiveTheme | null {
  try {
    if (typeof window === "undefined") return null;
    const v = window.localStorage.getItem(CACHE_KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;
  }
}

function writeCache(theme: EffectiveTheme): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(CACHE_KEY, theme);
  } catch {
    /* storage unavailable (e.g. tests): cache is best-effort */
  }
}

/** Apply a mode to the document root and publish the effective theme. Also
 * refreshes the localStorage hint so the next cold start paints correctly. */
export function applyTheme(mode: ThemeMode | string | null | undefined): EffectiveTheme {
  const eff = resolveTheme(mode, systemDark());
  const root = document.documentElement;
  root.dataset.theme = eff;
  root.style.colorScheme = eff;
  effectiveTheme.value = eff;
  writeCache(eff);
  return eff;
}

/** Register a listener for system dark/light changes. Returns an unsubscribe;
 * the caller owns the lifecycle (single instance + cleanup, A-G04-4). */
export function createSystemListener(onChange: (dark: boolean) => void): () => void {
  const mq = getMediaQuery();
  if (!mq || typeof mq.addEventListener !== "function") return () => {};
  const handler = (e: MediaQueryListEvent) => onChange(e.matches);
  mq.addEventListener("change", handler);
  return () => mq.removeEventListener("change", handler);
}
