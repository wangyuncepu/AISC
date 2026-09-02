/**
 * G-06 renderer policy tests (A-G06-1/2): the Workbench renderer enum is a
 * load/dispose policy, not an xterm option; explicit `default` always wins,
 * `webgl`/`auto` resolve to webgl when available. Theme tokens carry the
 * documented contrast claims (A-G06-5 spot checks).
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import {
  LIGHT_TERMINAL_THEME,
  resolveRenderer,
  TERMINAL_THEME,
  terminalTheme,
  webglGpuSummary,
} from "../renderer";

describe("resolveRenderer (A-G06-1/2)", () => {
  it("explicit default always wins, even when webgl is available", () => {
    expect(resolveRenderer("default", true)).toBe("default");
    expect(resolveRenderer("default", false)).toBe("default");
  });

  it("webgl resolves to webgl when available, falls back otherwise", () => {
    expect(resolveRenderer("webgl", true)).toBe("webgl");
    expect(resolveRenderer("webgl", false)).toBe("default");
  });

  it("auto prefers webgl like an explicit choice", () => {
    expect(resolveRenderer("auto", true)).toBe("webgl");
    expect(resolveRenderer("auto", false)).toBe("default");
  });
});

describe("webglGpuSummary (O3, D-11)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when no WebGL context exists (jsdom, hardened browsers)", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    expect(webglGpuSummary()).toBeNull();
  });

  it("reports the unmasked renderer and flags software rasterizers", () => {
    const fake = {
      getExtension: (name: string) =>
        name === "WEBGL_debug_renderer_info" ? { UNMASKED_RENDERER_WEBGL: 0x9246 } : null,
      getParameter: (k: number) => (k === 0x9246 ? "SwiftShader (software)" : "GL"),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(fake as unknown as WebGLRenderingContext);
    expect(webglGpuSummary()).toEqual({
      renderer: "SwiftShader (software)",
      software: true,
    });
  });

  it("hardware renderer is not flagged software", () => {
    const fake = {
      RENDERER: 0x1f01, // gl.RENDERER — read off the context object itself
      getExtension: () => null, // no debug ext -> falls back to RENDERER
      getParameter: (k: number) => (k === 0x1f01 ? "ANGLE (NVIDIA GeForce)" : "GL"),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(fake as unknown as WebGLRenderingContext);
    expect(webglGpuSummary()?.software).toBe(false);
  });
});

// WCAG relative luminance + contrast ratio (4.5:1 AA for body text).
function lum(hex: string): number {
  const c = hex.slice(1);
  const ch = [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16) / 255);
  const lin = ch.map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}
function ratio(a: string, b: string): number {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

describe("TERMINAL_THEME contrast (A-G06-5)", () => {
  it("body text and selection meet WCAG AA 4.5:1", () => {
    expect(ratio(TERMINAL_THEME.foreground!, TERMINAL_THEME.background!)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(TERMINAL_THEME.selectionForeground!, TERMINAL_THEME.selectionBackground!)).toBeGreaterThanOrEqual(4.5);
  });

  it("has explicit foreground/background/selection (no silent defaults)", () => {
    expect(TERMINAL_THEME.background).toBe("#1e1e1e");
    expect(TERMINAL_THEME.foreground).toBe("#d4d4d4");
    expect(TERMINAL_THEME.selectionBackground).toBe("#264f78");
  });
});

describe("terminalTheme (G-04)", () => {
  it("resolves dark/light to the matching palettes", () => {
    expect(terminalTheme("dark")).toBe(TERMINAL_THEME);
    expect(terminalTheme("light")).toBe(LIGHT_TERMINAL_THEME);
  });

  it("light body text and selection meet WCAG AA 4.5:1", () => {
    expect(ratio(LIGHT_TERMINAL_THEME.foreground!, LIGHT_TERMINAL_THEME.background!)).toBeGreaterThanOrEqual(4.5);
    expect(
      ratio(LIGHT_TERMINAL_THEME.selectionForeground!, LIGHT_TERMINAL_THEME.selectionBackground!)
    ).toBeGreaterThanOrEqual(4.5);
  });
});
