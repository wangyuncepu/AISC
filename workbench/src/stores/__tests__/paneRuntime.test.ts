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
import { findLeaf, leafCount, leafDepth, listLeaves, singleLeaf, splitLeaf } from "../paneTree";

/** Channels handed to openSession (the store owns them; tests emit events). */
const channels: Array<{ onmessage?: (ev: unknown) => void }> = [];

const mockIpc = vi.hoisted(() => ({
  getProviderStatus: vi.fn().mockResolvedValue({}),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 2, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  openSession: vi.fn().mockImplementation((...args: unknown[]) => {
    const ch = args[4] as { onmessage?: (ev: unknown) => void };
    channels.push(ch ?? {});
    return Promise.resolve({});
  }),
  writeSession: vi.fn().mockResolvedValue(undefined),
}));

function lastChannel(): { onmessage?: (ev: unknown) => void } {
  return channels[channels.length - 1];
}

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
  channels.length = 0;
});

describe("store session ops route through the active pane (A-G17-5)", () => {
  it("createTab builds a single-leaf tree and the projection matches", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
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

  it("store-owned session opens on create and Exit finalizes the pane", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    const id = s.createTab("bash")!;
    await tick();
    const tab = s.tabs.find((t) => t.tabId === id)!;
    // The STORE opens the session (no Terminal involvement): starting -> running.
    expect(tab.panes[id].sessionId).not.toBeNull();
    expect(tab.sessionId).toBe(tab.panes[id].sessionId); // projection synced
    expect(tab.panes[id].sessionState).toBe("running");
    // A PTY exit event (store channel) finalizes the pane + projection.
    lastChannel().onmessage?.({ type: "exit", reason: "process_exit", exitCode: 0 });
    expect(tab.panes[id].sessionState).toBe("exited");
    expect(tab.panes[id].exit?.reason).toBe("process_exit");
    expect(tab.exit?.reason).toBe("process_exit");
  });

  it("first PTY output promotes a starting pane to running (onTabOpenOk)", async () => {
    // Delay the open_session invoke: while it is still pending, PTY output
    // arriving on the channel must already flip the pane to running.
    mockIpc.openSession.mockImplementationOnce((...args: unknown[]) => {
      channels.push((args[4] as { onmessage?: (ev: unknown) => void }) ?? {});
      return new Promise<void>(() => {}); // never settles - invoke stays pending
    });
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    const id = s.createTab("bash")!;
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab.panes[id].sessionState).toBe("starting"); // invoke still pending
    lastChannel().onmessage?.({ type: "output", bytes: "eA==" }); // bash prompt arrives
    expect(tab.panes[id].sessionState).toBe("running"); // output => running
    expect(tab.sessionState).toBe("running"); // projection synced
  });

  it("open failure keeps a failed pane (no silent rollback, A-G17-2)", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    const id = s.createTab("bash")!;
    await tick();
    s.openTab(id);
    s.onTabOpenFail(id);
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab.panes[id].sessionState).toBe("failed");
    expect(tab.sessionState).toBe("failed");
  });
});

describe("split / close / ratio (A-G17-1/2/5)", () => {
  async function oneTab(): Promise<{ s: ReturnType<typeof useRuntimeStore>; id: string }> {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    const id = s.createTab("bash")!;
    await tick();
    s.openTab(id);
    return { s, id };
  }

  it("splitTabPane creates + activates a second leaf and opens it", async () => {
    const { s, id } = await oneTab();
    const newPane = s.splitTabPane(id, "horizontal", "claude");
    expect(newPane).not.toBeNull();
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(leafCount(tab.tree)).toBe(2);
    expect(tab.activePaneId).toBe(newPane);
    // claude with the provider mock ({} -> not configured) routes to guide,
    // never a session (A-G12-1).
    await vi.waitFor(() => expect(tab.panes[newPane!].sessionState).toBe("guide"));
    void newPane;
  });

  it("split is refused at the 8-leaf cap and leaves the tree unchanged", async () => {
    const { s, id } = await oneTab();
    // Fill to 8 leaves by always splitting a leaf at depth < 4 (so the depth
    // cap never trips before the leaf cap).
    for (let i = 0; i < 7; i++) {
      const tab = s.tabs.find((t) => t.tabId === id)!;
      const target = listLeaves(tab.tree).find((l) => leafDepth(tab.tree, l.paneId) < 4)!;
      s.setActivePane(id, target.paneId);
      const np = s.splitTabPane(id, "vertical", "bash");
      expect(np).not.toBeNull();
    }
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(leafCount(tab.tree)).toBe(8);
    const before = JSON.stringify(tab.tree);
    const r = s.splitTabPane(id, "vertical", "bash");
    expect(r).toBeNull();
    expect(JSON.stringify(tab.tree)).toBe(before);
  });

  it("closePane compresses the parent split", async () => {
    const { s, id } = await oneTab();
    const p2 = s.splitTabPane(id, "horizontal", "claude")!;
    let tab = s.tabs.find((t) => t.tabId === id)!;
    expect(leafCount(tab.tree)).toBe(2);
    s.setActivePane(id, id); // active = original pane
    await s.closePane(id, p2);
    tab = s.tabs.find((t) => t.tabId === id)!;
    expect(leafCount(tab.tree)).toBe(1);
    expect(tab.panes[p2]).toBeUndefined();
  });

  it("closing the last pane keeps the tab with a single dormant leaf", async () => {
    const { s, id } = await oneTab();
    await s.closePane(id, id);
    const tab = s.tabs.find((t) => t.tabId === id)!;
    expect(tab).toBeDefined(); // tab kept
    expect(leafCount(tab.tree)).toBe(1);
    expect(Object.values(tab.panes)[0].sessionState).toBe("idle"); // dormant
  });

  it("setSplitRatio clamps to 0.10..0.90", async () => {
    const { s, id } = await oneTab();
    s.splitTabPane(id, "horizontal", "claude");
    const tab = s.tabs.find((t) => t.tabId === id)!;
    const key = listLeaves(tab.tree).map((l) => l.paneId).sort().join(",");
    s.setSplitRatio(id, key, 0.95);
    const t2 = s.tabs.find((t) => t.tabId === id)!;
    expect((t2.tree as { ratio: number }).ratio).toBe(0.9);
    s.setSplitRatio(id, key, 0.0);
    const t3 = s.tabs.find((t) => t.tabId === id)!;
    expect((t3.tree as { ratio: number }).ratio).toBe(0.1);
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

describe("restore of unconfigured claude|codex panes (G-17 feedback 2026-08-10)", () => {
  it("initTabs routes every split leaf through the guide gate - none stays idle", async () => {
    mockIpc.getProviderStatus.mockResolvedValue({
      provider_name: null,
      route_mode: "unknown",
      auth_status: "not_configured",
      observed_at: "x",
    });
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    // Persisted split: claude | codex (both unconfigured), active = claude leaf.
    const tree = splitLeaf(singleLeaf("p1", "claude"), "p1", "p2", "horizontal", "codex", 0.5)!;
    s.initTabs(
      [
        {
          tab_id: "saved1",
          agent: "claude",
          title: "Claude",
          position: 0,
          split_layout: { version: 2, active_pane_id: "p1", root: internalToPersisted(tree) },
        },
      ],
      {}
    );
    await tick();
    await tick();
    const tab = s.tabs[0];
    expect(tab).toBeDefined();
    // Every leaf is gated to guide (no session), never left idle.
    expect(tab.panes["p1"].sessionState).toBe("guide");
    expect(tab.panes["p2"].sessionState).toBe("guide");
    expect(tab.panes["p1"].sessionId).toBeNull();
    expect(tab.panes["p2"].sessionId).toBeNull();
    // Projection mirrors the ACTIVE (claude) pane - tab bar label too.
    expect(tab.sessionState).toBe("guide");
    expect(tab.agent).toBe("claude");
    expect(tab.title).toBe("Claude");
  });

  it("restore of a CONFIGURED codex opens a live session - never dormant", async () => {
    mockIpc.getProviderStatus.mockResolvedValue({
      provider_name: "official",
      route_mode: "official-direct",
      auth_status: "configured",
      observed_at: "x",
    });
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    const tree = singleLeaf("p1", "codex");
    s.initTabs(
      [
        {
          tab_id: "saved1",
          agent: "codex",
          title: "Codex",
          position: 0,
          split_layout: { version: 1, active_pane_id: "p1", root: internalToPersisted(tree) },
        },
      ],
      {}
    );
    await tick();
    await tick();
    const tab = s.tabs[0];
    expect(tab).toBeDefined();
    // Configured codex must open a session (TUI), NOT stay idle/dormant.
    expect(["starting", "running"]).toContain(tab.panes["p1"].sessionState);
    expect(tab.panes["p1"].sessionId).not.toBeNull();
  });
});
