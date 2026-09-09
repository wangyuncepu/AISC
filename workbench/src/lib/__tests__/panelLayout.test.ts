/**
 * panelLayout (FIX-3): clamp bounds, persistence round-trip, corrupt-JSON
 * fallback, and the appScale zoom derivation.
 *
 * Module state is a singleton — each test re-imports via resetModules so
 * readPersisted() runs against a freshly seeded localStorage.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "aisc-wb-panel-layout-v1";

async function fresh() {
  vi.resetModules();
  return await import("../panelLayout");
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("clamp bounds", () => {
  it("clamps explorer width to 240..600 and rounds", async () => {
    const m = await fresh();
    expect(m.clampExplorerWidth(100)).toBe(240);
    expect(m.clampExplorerWidth(9999)).toBe(600);
    expect(m.clampExplorerWidth(321.6)).toBe(322);
    expect(m.clampExplorerWidth(320)).toBe(320);
  });

  it("clamps tabbar height to 40..120 (null passes through as natural)", async () => {
    const m = await fresh();
    expect(m.clampTabbarHeight(null)).toBeNull();
    expect(m.clampTabbarHeight(20)).toBe(40); // below natural height ⇒ scrollbar
    expect(m.clampTabbarHeight(500)).toBe(120);
    expect(m.clampTabbarHeight(64.4)).toBe(64);
    expect(m.clampTabbarHeight(Number.NaN)).toBeNull();
  });

  it("non-finite explorer width falls back to the default", async () => {
    const m = await fresh();
    expect(m.clampExplorerWidth(Number.NaN)).toBe(320);
  });
});

describe("persistence", () => {
  it("defaults on a cold store", async () => {
    const m = await fresh();
    expect({ ...m.panelLayout }).toEqual({
      explorerWidth: 320, explorerCollapsed: false, tabbarHeight: null,
    });
  });

  it("setters clamp then persist, and a fresh import reads them back", async () => {
    const m = await fresh();
    m.setExplorerWidth(5000);        // clamped to 600
    m.setExplorerCollapsed(true);
    m.setTabbarHeight(30);           // clamped to 40
    expect({ ...m.panelLayout }).toEqual({
      explorerWidth: 600, explorerCollapsed: true, tabbarHeight: 40,
    });
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
    expect(raw).toEqual({
      explorerWidth: 600, explorerCollapsed: true, tabbarHeight: 40,
    });

    const m2 = await fresh();        // readPersisted runs against the store
    expect({ ...m2.panelLayout }).toEqual({
      explorerWidth: 600, explorerCollapsed: true, tabbarHeight: 40,
    });
  });

  it("collapse does not clobber the remembered width", async () => {
    const m = await fresh();
    m.setExplorerWidth(420);
    m.toggleExplorerCollapsed();
    expect(m.panelLayout.explorerCollapsed).toBe(true);
    expect(m.panelLayout.explorerWidth).toBe(420);
    m.toggleExplorerCollapsed();
    expect(m.panelLayout.explorerCollapsed).toBe(false);
    expect(m.panelLayout.explorerWidth).toBe(420);
  });

  it("corrupt JSON / wrong shapes fall back to defaults", async () => {
    window.localStorage.setItem(KEY, "{not json");
    let m = await fresh();
    expect(m.panelLayout.explorerWidth).toBe(320);

    window.localStorage.setItem(KEY,
      JSON.stringify({ explorerWidth: "wide", explorerCollapsed: "yes", tabbarHeight: [] }));
    m = await fresh();
    expect({ ...m.panelLayout }).toEqual({
      explorerWidth: 320, explorerCollapsed: false, tabbarHeight: null,
    });
  });
});

describe("appScale", () => {
  it("derives scale from innerWidth / .app offsetWidth", async () => {
    const m = await fresh();
    const app = document.createElement("div");
    app.className = "app";
    document.body.appendChild(app);
    const spy = vi.spyOn(app, "offsetWidth", "get").mockReturnValue(500);
    vi.stubGlobal("innerWidth", 1000);
    expect(m.appScale()).toBe(2);
    spy.mockRestore();
    document.body.removeChild(app);
  });

  it("returns 1 without an .app element or with degenerate math", async () => {
    const m = await fresh();
    expect(m.appScale()).toBe(1); // no .app in the jsdom document
  });
});
