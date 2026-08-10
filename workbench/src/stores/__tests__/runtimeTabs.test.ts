/**
 * G-08 dynamic-tab store tests (Step 5, A-G08-1/2/6/8): createTab cap and
 * duplicate types, provider gate routing claude/codex to guide, removeTab
 * active-tab fallback (right -> left -> empty), live-session close on
 * removal.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import { normalizePath } from "../tabLayout";
import type { HistoryPatch, WorkbenchHistory } from "../../types";

const mockIpc = vi.hoisted(() => ({
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 2, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  openSession: vi.fn().mockResolvedValue({}),
  writeSession: vi.fn().mockResolvedValue(undefined),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  stopRuntime: vi.fn().mockResolvedValue({ state: "stopped" }),
  runtimeInspect: vi.fn().mockResolvedValue({ state: "stopped" }),
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
  mockIpc.getProviderStatus.mockResolvedValue({});
});

describe("createTab (A-G08-1/8)", () => {
  it("adds an activated tab and opens the session immediately (bash)", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    const id = s.createTab("bash");
    expect(id).not.toBeNull();
    await tick();
    const tab = s.tabs.find((t) => t.tabId === id);
    expect(tab?.agent).toBe("bash");
    expect(tab?.sessionId).not.toBeNull();
    expect(s.activeTabId).toBe(id);
  });

  it("allows duplicate session types with distinct ids", async () => {
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    const a = s.createTab("bash");
    const b = s.createTab("bash");
    expect(a).not.toBe(b);
    expect(s.tabs.filter((t) => t.agent === "bash")).toHaveLength(2);
  });

  it("refuses the 9th tab (per-Runtime leaf cap)", () => {
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    for (let i = 0; i < 8; i++) expect(s.createTab("bash")).not.toBeNull();
    expect(s.createTab("bash")).toBeNull();
    expect(s.tabs).toHaveLength(8);
  });
});

describe("provider gate (A-G08-2)", () => {
  it("routes unconfigured claude to the guide state without open_session", async () => {
    mockIpc.getProviderStatus.mockResolvedValue({
      provider_name: null,
      route_mode: "unknown",
      auth_status: "not_configured",
      observed_at: "x",
    });
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    const id = s.createTab("claude");
    await tick();
    await tick();
    const tab = s.tabs.find((t) => t.tabId === id);
    expect(tab?.sessionState).toBe("guide");
    expect(tab?.sessionId).toBeNull();
    expect(mockIpc.getProviderStatus).toHaveBeenCalledWith("/ws", "rid", "claude");
  });

  it("restore layout gates unconfigured claude/codex to guide (A-G08-3)", async () => {
    mockIpc.getProviderStatus.mockResolvedValue({
      provider_name: null,
      route_mode: "unknown",
      auth_status: "not_configured",
      observed_at: "x",
    });
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    s.initTabs(
      [
        { tab_id: "a", agent: "bash", title: "Bash", position: 0 },
        { tab_id: "b", agent: "codex", title: "Codex", position: 1 },
      ],
      { openAgents: ["bash", "codex"] }
    );
    await tick();
    await tick();
    const bash = s.tabs.find((t) => t.agent === "bash");
    const codex = s.tabs.find((t) => t.agent === "codex");
    expect(["starting", "running"]).toContain(bash?.sessionState); // bash opens directly
    expect(bash?.sessionId).not.toBeNull();
    expect(codex?.sessionState).toBe("guide"); // codex gated, no session
    expect(codex?.sessionId).toBeNull();
  });

  it("opens the session when the provider is configured", async () => {
    mockIpc.getProviderStatus.mockResolvedValue({
      provider_name: "official",
      route_mode: "official-direct",
      auth_status: "configured",
      observed_at: "x",
    });
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    const id = s.createTab("codex");
    await tick();
    await tick();
    const tab = s.tabs.find((t) => t.tabId === id);
    expect(["starting", "running"]).toContain(tab?.sessionState);
    expect(tab?.sessionId).not.toBeNull();
  });
});

describe("removeTab (A-G08-6)", () => {
  async function threeTabs() {
    const s = useRuntimeStore();
    s.runtimeState = "running"; s.runtimeId = "rid";
    const a = s.createTab("bash")!;
    const b = s.createTab("bash")!;
    const c = s.createTab("bash")!;
    await tick();
    return { s, a, b, c };
  }

  it("removes the tab; active falls to the right neighbor", async () => {
    const { s, a, b, c } = await threeTabs();
    s.activateTab(a);
    await s.removeTab(a);
    expect(s.tabs.find((t) => t.tabId === a)).toBeUndefined();
    expect(s.activeTabId).toBe(b); // right neighbor
    void c;
  });

  it("active at the end falls to the left neighbor", async () => {
    const { s, b, c } = await threeTabs();
    s.activateTab(c);
    await s.removeTab(c);
    expect(s.activeTabId).toBe(b);
  });

  it("removing the last tab yields the empty state", async () => {
    const { s, a } = await threeTabs();
    await s.removeTab(a);
    await s.removeTab(s.tabs[0].tabId);
    await s.removeTab(s.tabs[0].tabId);
    expect(s.tabs).toHaveLength(0);
    expect(s.activeTabId).toBeNull();
  });

  it("closes a live session best-effort and removes immediately", async () => {
    const { s, a, b } = await threeTabs();
    const running = s.tabs.find((t) => t.tabId === a)!;
    expect(["starting", "running"]).toContain(running.sessionState);
    await s.removeTab(a);
    expect(mockIpc.closeSession).toHaveBeenCalledWith(running.sessionId);
    expect(s.tabs.find((t) => t.tabId === a)).toBeUndefined();
    expect(s.tabs).toHaveLength(2);
    void b;
  });
});

describe("history memory stays in sync with disk (G-07 last-layout fallback)", () => {
  it("doSave reloads history.value, so a runtime stop preserves the multi-tab layout", async () => {
    // Disk starts with a stale single-codex layout (e.g. from a prior session).
    const wsPath = normalizePath("/ws");
    let disk: WorkbenchHistory = {
      schema_version: 2,
      revision: 0,
      workspaces: [
        {
          path: wsPath,
          last_used_at: "t",
          pinned: false,
          last_agent: "codex",
          runtime: null,
          layout: {
            active_tab_id: null,
            tabs: [{ tab_id: "old", agent: "codex", title: "Codex", position: 0 }],
          },
        },
      ],
    };
    mockIpc.loadHistory.mockImplementation(async () => disk);
    mockIpc.saveHistory.mockImplementation(async (_rev: number, patch: HistoryPatch) => {
      const patched = patch.workspaces[0];
      const others = disk.workspaces.filter((w) => w.path !== patched.path);
      disk = { schema_version: 2, revision: disk.revision + 1, workspaces: [patched, ...others] };
      return disk.revision;
    });

    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    await s.loadHistory(); // memory seeded from disk = single [codex]

    // Open two tabs; the debounced save must carry BOTH and doSave must reload
    // history.value so the in-memory copy mirrors the freshly-saved disk state.
    await s.initTabs(
      [
        { tab_id: "a", agent: "bash", title: "Bash", position: 0 },
        { tab_id: "b", agent: "codex", title: "Codex", position: 1 },
      ],
      { openAgents: ["bash", "codex"] }
    );
    await tick();
    await tick();
    await s.flushSave();
    await tick();

    const rec = s.history?.workspaces.find((w) => w.path === wsPath);
    expect(rec?.layout?.tabs).toHaveLength(2); // memory synced, NOT the stale [codex]
    expect(disk.workspaces[0].layout?.tabs).toHaveLength(2); // disk too
  });

  it("stopRuntime flushes the CURRENT layout before clearing tabs", async () => {
    // Disk starts with a stale single-codex layout; the current session opens
    // two tabs and stops immediately (before the 300ms debounce fires).
    const wsPath = normalizePath("/ws");
    let disk: WorkbenchHistory = {
      schema_version: 2,
      revision: 0,
      workspaces: [
        {
          path: wsPath,
          last_used_at: "t",
          pinned: false,
          last_agent: "codex",
          runtime: null,
          layout: {
            active_tab_id: null,
            tabs: [{ tab_id: "old", agent: "codex", title: "Codex", position: 0 }],
          },
        },
      ],
    };
    mockIpc.loadHistory.mockImplementation(async () => disk);
    mockIpc.saveHistory.mockImplementation(async (_rev: number, patch: HistoryPatch) => {
      const patched = patch.workspaces[0];
      const others = disk.workspaces.filter((w) => w.path !== patched.path);
      disk = { schema_version: 2, revision: disk.revision + 1, workspaces: [patched, ...others] };
      return disk.revision;
    });

    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    s.workspace = "/ws";
    await s.loadHistory();
    await s.initTabs(
      [
        { tab_id: "a", agent: "bash", title: "Bash", position: 0 },
        { tab_id: "b", agent: "codex", title: "Codex", position: 1 },
      ],
      { openAgents: ["bash", "codex"] }
    );
    await tick();
    await tick();

    await s.stopRuntime(); // no wait for the debounce - flushSave must persist the 2 tabs

    expect(s.tabs).toHaveLength(0); // runtime stopped, tabs cleared
    const rec = s.history?.workspaces.find((w) => w.path === wsPath);
    expect(rec?.layout?.tabs).toHaveLength(2); // current layout survived the stop
    expect(disk.workspaces[0].layout?.tabs).toHaveLength(2); // disk too
  });
});
