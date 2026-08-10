/**
 * G-04 theme tests (Step 17; A-G04-1/2):
 * - resolveTheme: fixed dark/light win over the OS; system follows it;
 *   unknown/falsy falls back to system.
 * - applyTheme: sets the DOM data-theme + color-scheme, publishes the reactive
 *   effectiveTheme, and refreshes the localStorage render hint.
 */
import { describe, expect, it } from "vitest";
import { applyTheme, effectiveTheme, readCachedTheme, resolveTheme } from "../../theme";

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
});
