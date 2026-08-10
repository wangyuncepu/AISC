/**
 * G-17 pane-model tests (Step 16; 03 §六, A-G17-2/5):
 * - store session ops route through the tab's ACTIVE pane and keep the
 *   tab-level projection (sessionId/state/exit/agent) in sync;
 * - tabLayout converts persisted (snake_case) <-> in-memory trees and restores
 *   a split_layout record into a tab with per-leaf pane state.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import {
  internalToPersisted,
  newPaneTab,
  persistedToInternal,
  tabsFromRecords,
} from "../tabLayout";
import { findLeaf, listLeaves, singleLeaf, splitLeaf } from "../paneTree";

const mockIpc = vi.hoisted(() => ({
  getProviderStatus: vi.fn().mockResolvedValue({}),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 2, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  openSession: vi.fn().mockResolvedValue({}),
  writeSession: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn().mockResolvedValue(true),
  open: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: vi.fn(() => ({
    isFocused: vi.fn().mockResolvedValue(true),
    isMinimized: vi.fn().mockResolvedValue(false),
  })),
}));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(false),
  requestPermission: vi.fn().mockResolvedValue("denied"),
  sendNotification: vi.fn().mockResolvedValue(undefined),
}));

function tick(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("store session ops route through the active pane (A-G17-5)", () => {
  it("createTab builds a single-leaf tree and the projection matches", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    const id = s.createTab("bash")!;
    await tick();
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab.tree.kind).toBe("pane");
    expect(tab.activePaneId).toBe(id); // pane shares the tab's uuid
    expect(tab.panes[id]).toBeDefined();
    // Projection mirrors the active pane.
    expect(tab.sessionState).toBe(tab.panes[id].sessionState);
    expect(tab.sessionId).toBe(tab.panes[id].sessionId);
  });

  it("openTab binds the active pane and Exit finalizes it + projection", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    const id = s.createTab("bash")!;
    await tick();
    s.openTab(id);
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab.panes[id].sessionState).toBe("starting");
    expect(tab.panes[id].sessionId).not.toBeNull();
    expect(tab.sessionState).toBe("starting");
    s.onTabOpenOk(id);
    expect(tab.panes[id].sessionState).toBe("running");
    expect(tab.sessionState).toBe("running");
    s.onTabSessionExit(id, "process_exit", 0);
    expect(tab.panes[id].sessionState).toBe("exited");
    expect(tab.panes[id].exit?.reason).toBe("process_exit");
    expect(tab.exit?.reason).toBe("process_exit");
  });

  it("open failure keeps a failed pane (no silent rollback, A-G17-2)", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    const id = s.createTab("bash")!;
    await tick();
    s.openTab(id);
    s.onTabOpenFail(id);
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab.panes[id].sessionState).toBe("failed");
    expect(tab.sessionState).toBe("failed");
  });
});

describe("newPaneTab / conversions (03 §6.3)", () => {
  it("builds a single-leaf tree with the active pane", () => {
    const t = newPaneTab("tab1", "bash", "Bash", null);
    expect(t.tree.kind).toBe("pane");
    expect(t.activePaneId).toBe("tab1");
    expect(t.panes["tab1"]).toEqual({ sessionId: null, sessionState: "idle", exit: null });
  });

  it("internal <-> persisted round-trips a nested split", () => {
    const tree = splitLeaf(singleLeaf("p1", "bash"), "p1", "p2", "vertical", "claude", 0.4)!;
    const persisted = internalToPersisted(tree);
    const sp = persisted as Extract<typeof persisted, { kind: "split" }>;
    expect(sp.kind).toBe("split");
    expect(sp.axis).toBe("vertical");
    expect(sp.ratio).toBe(0.4);
    expect(persistedToInternal(persisted)).toEqual(tree);
  });

  it("restores a split_layout record with per-leaf pane state", () => {
    const tree = splitLeaf(singleLeaf("p1", "bash"), "p1", "p2", "horizontal", "codex", 0.5)!;
    const t = newPaneTab("tab1", "bash", "Bash", null, {
      version: 1,
      active_pane_id: "p2",
      root: internalToPersisted(tree),
    });
    expect(listLeaves(t.tree).map((l) => l.paneId).sort()).toEqual(["p1", "p2"]);
    expect(t.activePaneId).toBe("p2");
    expect(Object.keys(t.panes).sort()).toEqual(["p1", "p2"]);
    expect(findLeaf(t.tree, "p1")?.sessionType).toBe("bash");
    expect(findLeaf(t.tree, "p2")?.sessionType).toBe("codex");
  });

  it("tabsFromRecords restores a nested split tree", () => {
    const tree = splitLeaf(singleLeaf("p1", "bash"), "p1", "p2", "horizontal", "codex", 0.5)!;
    const { tabs } = tabsFromRecords([
      {
        tab_id: "saved1",
        agent: "bash",
        title: "Bash",
        position: 0,
        split_layout: { version: 1, active_pane_id: "p2", root: internalToPersisted(tree) },
      },
    ]);
    const tab = tabs[0];
    expect(tab.savedTabId).toBe("saved1");
    expect(listLeaves(tab.tree).map((l) => l.paneId).sort()).toEqual(["p1", "p2"]);
    expect(tab.activePaneId).toBe("p2");
  });
});
