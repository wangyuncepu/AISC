/**
 * Terminal renderer policy (G-06).
 *
 * `terminal.renderer` is a Workbench-level enum (`auto | default | webgl`)
 * that decides whether the WebglAddon is loaded/disposed - it is NOT an xterm
 * `TerminalOptions` field and must never be written into `term.options`
 * (06 §七). `auto` prefers WebGL like an explicit `webgl`; the caller falls
 * back to the DOM renderer on construction failure or context loss (A-G06-2).
 */
import type { ITheme } from "@xterm/xterm";

export type ActiveRenderer = "webgl" | "default";

/** Pure resolution for tests: explicit `default` always wins; `webgl`/`auto`
 * resolve to webgl when available. */
export function resolveRenderer(setting: string, webglAvailable: boolean): ActiveRenderer {
  if (setting === "default") return "default";
  if (setting === "webgl") return webglAvailable ? "webgl" : "default";
  return webglAvailable ? "webgl" : "default"; // auto
}

/**
 * Dark terminal palette aligned with the Workbench CSS tokens (A-G06-5):
 * foreground #d4d4d4 on background #1e1e1e ≈ 12.6:1, selection foreground
 * #ffffff on #264f78 ≈ 7.9:1 - both ≥ WCAG AA 4.5:1. Values are the VS Code
 * dark defaults, the app's established look.
 */
export const TERMINAL_THEME: ITheme = {
  background: "#1e1e1e",
  foreground: "#d4d4d4",
  cursor: "#d4d4d4",
  cursorAccent: "#1e1e1e",
  selectionBackground: "#264f78",
  selectionForeground: "#ffffff",
  black: "#000000",
  red: "#cd3131",
  green: "#0dbc79",
  yellow: "#e5e510",
  blue: "#2472c8",
  magenta: "#bc3fbc",
  cyan: "#11a8cd",
  white: "#e5e5e5",
  brightBlack: "#666666",
  brightRed: "#f14c4c",
  brightGreen: "#23d18b",
  brightYellow: "#f5f543",
  brightBlue: "#3b8eea",
  brightMagenta: "#d670d6",
  brightCyan: "#29b8db",
  brightWhite: "#e5e5e5",
};
