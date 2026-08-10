/**
 * G-04 theme tests (Step 17; A-G04-1/2):
 * - resolveTheme: fixed dark/light win over the OS; system follows it;
 *   unknown/falsy falls back to system.
 * - applyTheme: sets the DOM data-theme + color-scheme, publishes the reactive
 *   effectiveTheme, and refreshes the localStorage render hint.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, createSystemListener, effectiveTheme, readCachedTheme, resolveTheme } from "../../theme";

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
