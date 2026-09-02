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
import type { EffectiveTheme } from "../../theme";

export type ActiveRenderer = "webgl" | "default";

/** Pure resolution for tests: explicit `default` always wins; `webgl`/`auto`
 * resolve to webgl when available. */
export function resolveRenderer(setting: string, webglAvailable: boolean): ActiveRenderer {
  if (setting === "default") return "default";
  if (setting === "webgl") return webglAvailable ? "webgl" : "default";
  return webglAvailable ? "webgl" : "default"; // auto
}

/** O3 (opt-batch, D-11): one-shot GPU summary for renderer telemetry —
 * whether the WebGL context actually lands on hardware or a software raster
 * (SwiftShader/llvmpipe — the low-end-device path fit oscillation lived on).
 * The probe canvas is never attached and the context dropped immediately;
 * null wherever WebGL or the debug extension is unavailable (jsdom,
 * hardened browsers). */
export interface WebglGpuSummary {
  renderer: string;
  software: boolean;
}

export function webglGpuSummary(): WebglGpuSummary | null {
  try {
    const canvas = document.createElement("canvas");
    const gl = (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) as
      | (WebGLRenderingContext & {
          getExtension(name: string): {
            UNMASKED_RENDERER_WEBGL: number;
          } | null;
        })
      | null;
    if (!gl) return null;
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = String(
      dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    );
    if (!renderer) return null;
    return {
      renderer,
      software: /swiftshader|llvmpipe|softpipe|software/i.test(renderer),
    };
  } catch {
    return null;
  }
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

/** Light terminal palette (G-04, Step 17): VS Code Light values; foreground
 * #333333 on #ffffff ≈ 15:1, selection foreground #000000 on #add6ff ≈ 9:1 -
 * both ≥ WCAG AA 4.5:1. */
export const LIGHT_TERMINAL_THEME: ITheme = {
  background: "#ffffff",
  foreground: "#333333",
  cursor: "#333333",
  cursorAccent: "#ffffff",
  selectionBackground: "#add6ff",
  selectionForeground: "#000000",
  black: "#000000",
  red: "#cd3131",
  green: "#107c10",
  yellow: "#949800",
  blue: "#0451a5",
  magenta: "#bc05bc",
  cyan: "#0598bc",
  white: "#555555",
  brightBlack: "#686868",
  brightRed: "#cd3131",
  brightGreen: "#00bc00",
  brightYellow: "#949800",
  brightBlue: "#0451a5",
  brightMagenta: "#bc05bc",
  brightCyan: "#0598bc",
  brightWhite: "#a5a5a5",
};

/** G-04: terminal palette for the effective app theme. */
export function terminalTheme(eff: EffectiveTheme): ITheme {
  return eff === "light" ? LIGHT_TERMINAL_THEME : TERMINAL_THEME;
}
