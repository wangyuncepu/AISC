/**
 * G-04 theme tests (Step 17; A-G04-1/2):
 * - resolveTheme: fixed dark/light win over the OS; system follows it;
 *   unknown/falsy falls back to system.
 * - applyTheme: sets the DOM data-theme + color-scheme, publishes the reactive
 *   effectiveTheme, and refreshes the localStorage render hint.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, createSystemListener, effectiveTheme, readCachedTheme, resolveTheme } from "../../theme";

// Token fixtures mirror styles.css (same pattern as the renderer test's
// TERMINAL_THEME values): the contrast gate stays bound to the real palette.
const DARK_TOKENS: Record<string, string> = {
  "--text": "#e6e6e6",
  "--bg": "#1e1e1e",
  "--text-2": "#d0d0d0",
  "--surface": "#252526",
  "--text-muted": "#9a9a9a",
  "--error": "#e57373",
  "--error-fg": "#e0b0b0",
  "--error-bg": "#5a2d2d",
  "--warn-fg": "#e0c97a",
  "--warn-bg": "#3a3220",
  "--accent-fg": "#ffffff",
  "--accent": "#0e639c",
};
const LIGHT_TOKENS: Record<string, string> = {
  "--text": "#1e1e1e",
  "--bg": "#f3f3f3",
  "--text-2": "#2d2d2d",
  "--surface": "#ffffff",
  "--text-muted": "#666666",
  "--error": "#b3261e",
  "--error-fg": "#8f1d1d",
  "--error-bg": "#f6d2d2",
  "--warn-fg": "#6b4d00",
  "--warn-bg": "#f5e9c9",
  "--accent-fg": "#ffffff",
  "--accent": "#0e639c",
};
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

describe("resolveTheme (A-G04-1)", () => {
  it("fixed dark/light win over the system preference", () => {
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("system follows the OS (dark-first default); unknown falls back to system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme(undefined, true)).toBe("dark");
    expect(resolveTheme(undefined, false)).toBe("light");
    expect(resolveTheme("bogus", false)).toBe("light"); // invalid -> system
  });
});

describe("applyTheme (A-G04-2)", () => {
  it("sets DOM data-theme + color-scheme, publishes effectiveTheme, caches", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(effectiveTheme.value).toBe("light");
    expect(readCachedTheme()).toBe("light");

    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(effectiveTheme.value).toBe("dark");
    expect(readCachedTheme()).toBe("dark");
  });

  it("system mode resolves from the OS via matchMedia (dark-first default)", () => {
    vi.stubGlobal("window", {
      ...window,
      matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
    });
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(readCachedTheme()).toBe("light");
  });
});

describe("semantic token contrast (A-G04-3)", () => {
  // Foreground/background pairs that must meet WCAG AA 4.5:1 in BOTH themes.
  const PAIRS: Array<[string, string]> = [
    ["--text", "--bg"],
    ["--text-2", "--surface"],
    ["--text-muted", "--surface"],
    ["--error", "--bg"],
    ["--error-fg", "--error-bg"],
    ["--warn-fg", "--warn-bg"],
    ["--accent-fg", "--accent"],
  ];
  function assertPairs(tokens: Record<string, string>, label: string) {
    for (const [fg, bg] of PAIRS) {
      const r = ratio(tokens[fg], tokens[bg]);
      expect(r, `${label}: ${fg} on ${bg} = ${r.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
    }
  }

  it("dark palette key pairs meet WCAG AA 4.5:1", () => {
    assertPairs(DARK_TOKENS, "dark");
  });

  it("light palette key pairs meet WCAG AA 4.5:1", () => {
    assertPairs(LIGHT_TOKENS, "light");
  });
});

describe("createSystemListener (A-G04-4)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("single listener fires on OS change and unsubscribe removes it", () => {
    const listeners: Array<(e: { matches: boolean }) => void> = [];
    const mq = {
      matches: true,
      addEventListener: vi.fn((_: string, cb: (e: { matches: boolean }) => void) => listeners.push(cb)),
      removeEventListener: vi.fn((_: string, cb: unknown) => {
        const i = listeners.indexOf(cb as (e: { matches: boolean }) => void);
        if (i >= 0) listeners.splice(i, 1);
      }),
    };
    vi.stubGlobal("window", { ...window, matchMedia: () => mq });

    const onChange = vi.fn();
    const stop = createSystemListener(onChange);
    expect(mq.addEventListener).toHaveBeenCalledTimes(1); // single instance
    expect(listeners).toHaveLength(1);

    listeners[0]?.({ matches: false });
    expect(onChange).toHaveBeenCalledWith(false);

    stop();
    expect(mq.removeEventListener).toHaveBeenCalledTimes(1); // cleanup
    expect(listeners).toHaveLength(0); // removed, no further events
  });
});
