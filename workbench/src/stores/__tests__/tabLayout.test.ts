/**
 * A-INFRA-1: per-TabRecord restore regression gate.
 *
 * The old restore path rebuilt the fixed 4-tab model and opened tabs via
 * `tabs.find((t) => t.agent === agent)` - two saved Bash tabs collapsed into
 * one. These tests pin the per-record semantics (02 §2.3): duplicates kept,
 * order kept, saved tab_id → new tab_id mapping, agent-free active resolution.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LaunchAgent, TabRecord } from "../../types";
import { normalizePath, resolveActiveTabId, sameWorkspace, tabsFromRecords } from "../tabLayout";

function rec(tab_id: string, agent: LaunchAgent, position: number): TabRecord {
  return { tab_id, agent, title: agent, position };
}

describe("tabsFromRecords (A-INFRA-1)", () => {
  it("keeps duplicate session types - the .find(agent) dedup regression", () => {
    const records = [rec("saved-a", "bash", 0), rec("saved-b", "bash", 1)];
    const { tabs } = tabsFromRecords(records);
    expect(tabs).toHaveLength(2);
    expect(tabs.map((t) => t.agent)).toEqual(["bash", "bash"]);
    expect(tabs[0].tabId).not.toBe(tabs[1].tabId);
    // Every restored tab is idle with no session yet (02 §2.3).
    expect(tabs.every((t) => t.sessionId === null && t.sessionState === "idle")).toBe(true);
  });

  it("preserves record order across mixed types", () => {
    const records = [
      rec("a", "claude", 0),
      rec("b", "bash", 1),
      rec("c", "claude", 2),
      rec("d", "cc-switch", 3),
    ];
    const { tabs } = tabsFromRecords(records);
    expect(tabs.map((t) => t.agent)).toEqual(["claude", "bash", "claude", "cc-switch"]);
  });

  it("maps every saved tab_id to exactly one new tab_id", () => {
    const records = [rec("a", "bash", 0), rec("b", "bash", 1), rec("c", "claude", 2)];
    const { tabs, bySavedId } = tabsFromRecords(records);
    expect(bySavedId.size).toBe(3);
    expect(bySavedId.get("a")).toBe(tabs[0].tabId);
    expect(bySavedId.get("b")).toBe(tabs[1].tabId);
    expect(bySavedId.get("c")).toBe(tabs[2].tabId);
    expect(tabs.map((t) => t.savedTabId)).toEqual(["a", "b", "c"]);
  });
});

describe("normalizePath / sameWorkspace (G-07 restore matching)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("win: forward slashes, trailing separators, case-insensitive", () => {
    vi.stubGlobal("navigator", {
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    });
    expect(normalizePath("C:/Users/VE111/ws/")).toBe("C:\\Users\\VE111\\ws");
    expect(normalizePath("C:\\Users\\VE111\\ws\\")).toBe("C:\\Users\\VE111\\ws");
    expect(normalizePath("C:\\")).toBe("C:\\"); // drive root kept
    expect(sameWorkspace("C:/Users/VE111/ws/", "c:\\users\\ve111\\ws")).toBe(true);
    expect(sameWorkspace("C:\\a", "C:\\b")).toBe(false);
  });

  it("posix: trailing slash stripped, case-sensitive", () => {
    vi.stubGlobal("navigator", {
      userAgent: "Mozilla/5.0 (X11; Linux x86_64)",
    });
    expect(normalizePath("/home/u/ws/")).toBe("/home/u/ws");
    expect(normalizePath("/home/u/ws//")).toBe("/home/u/ws");
    expect(normalizePath("/")).toBe("/"); // root kept
    expect(sameWorkspace("/home/u/ws", "/home/u/ws/")).toBe(true);
    expect(sameWorkspace("/A", "/a")).toBe(false);
  });
});

describe("resolveActiveTabId (02 §2.3)", () => {
  it("maps the saved active tab through the saved→new map", () => {
    const records = [rec("a", "bash", 0), rec("b", "bash", 1), rec("c", "claude", 2)];
    const { tabs, bySavedId } = tabsFromRecords(records);
    expect(resolveActiveTabId(tabs, bySavedId, { activeSavedId: "b" })).toBe(
      bySavedId.get("b")
    );
  });

  it("falls back to the first tab when the saved id is missing", () => {
    const { tabs, bySavedId } = tabsFromRecords([rec("a", "bash", 0), rec("b", "bash", 1)]);
    expect(resolveActiveTabId(tabs, bySavedId, { activeSavedId: "ghost" })).toBe(tabs[0].tabId);
  });

  it("falls back to the agent tab on fresh start", () => {
    const { tabs, bySavedId } = tabsFromRecords([
      rec("c", "claude", 0),
      rec("x", "codex", 1),
      rec("b", "bash", 2),
    ]);
    expect(resolveActiveTabId(tabs, bySavedId, { activeAgent: "bash" })).toBe(tabs[2].tabId);
  });

  it("returns null when there are no tabs", () => {
    expect(resolveActiveTabId([], new Map())).toBeNull();
  });
});
