/**
 * IDEA-3 (3c): the workspace layer — launcher materialization, activation
 * cycling, the MAX_WORKSPACES cap, per-workspace close (confirm + layout
 * flush + stream GC + neighbor activation), the merged history save cycle
 * (one saveHistory call for N dirty workspaces), and the aggregated exit
 * gate. Workspaces are born through the REAL path (initTabs → onReady →
 * materialize), never by poking store internals.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkspacesStore, MAX_WORKSPACES } from "../workspaces";
import { useRuntimeStore } from "../runtime";
import type { HistoryPatch, Tab } from "../../types";
import { confirm as confirmDialog } from "@tauri-apps/plugin-dialog";

const mockIpc = vi.hoisted(() => ({
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
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

function bareTab(id: string, live = false): Tab {
  const paneId = id;
  return {
    tabId: id,
    agent: "bash",
    title: "Bash",
    sessionId: live ? `sid-${id}` : null,
    sessionState: live ? "running" : "idle",
    exit: null,
    savedTabId: null,
    tree: { kind: "pane", paneId, sessionType: "bash" },
    activePaneId: paneId,
    panes: { [paneId]: { sessionId: live ? `sid-${id}` : null, sessionState: live ? "running" : "idle", exit: null } },
  };
}

/** Drive the REAL birth path: the launcher preflight-ready → initTabs →
 * onReady → materialize into a workspace. */
async function launchWorkspace(ws: ReturnType<typeof useWorkspacesStore>, path: string): Promise<void> {
  ws.launcher.workspace.value = path;
  ws.launcher.runtimeId.value = `rid-${path}`;
  await ws.launcher.initTabs([]);
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mockIpc.stopRuntime.mockResolvedValue({ state: "stopped" });
  mockIpc.loadHistory.mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] });
});

describe("launcher materialization (3c)", () => {
  it("promotes the ready launcher into a workspace and mints a fresh picker launcher", async () => {
    const ws = useWorkspacesStore();
    expect(ws.runtimes).toHaveLength(0);
    await launchWorkspace(ws, "C:/a");
    expect(ws.runtimes).toHaveLength(1);
    expect(ws.runtimes[0].workspace.value).toBe("C:/a");
    expect(ws.activeId).toBe(ws.runtimes[0].id);
    expect(ws.launcher.status.value).toBe("picker"); // re-minted, never idle
    expect(ws.launcher.id).not.toBe(ws.runtimes[0].id);
    // Facade re-targets the new workspace (zero per-component changes).
    const rt = useRuntimeStore();
    expect(rt.workspace).toBe("C:/a");
  });

  it("adopts the EXISTING workspace on a duplicate path and resets the launcher", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/dup");
    const firstId = ws.runtimes[0].id;
    await launchWorkspace(ws, "C:/dup");
    expect(ws.runtimes).toHaveLength(1); // not two runtimes on one path
    expect(ws.activeId).toBe(firstId); // existing adopted
    expect(ws.launcher.status.value).toBe("picker");
  });

  it("refuses openLauncher at the cap (MAX_WORKSPACES) without moving focus", async () => {
    const ws = useWorkspacesStore();
    for (let i = 0; i < MAX_WORKSPACES; i++) {
      await launchWorkspace(ws, `C:/w${i}`);
    }
    expect(ws.runtimes).toHaveLength(MAX_WORKSPACES);
    const active = ws.activeId;
    expect(ws.openLauncher()).toBe(false);
    expect(ws.activeId).toBe(active);
    expect(ws.launcher.status.value).toBe("picker"); // untouched mid-flight state irrelevant
  });
});

describe("activation cycling (3c)", () => {
  it("cycles workspaces with the launcher riding last", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/a");
    await launchWorkspace(ws, "C:/b");
    const [a, b] = ws.runtimes;
    expect(ws.activeId).toBe(b.id); // materialize activates the newborn
    ws.cycle(1);
    expect(ws.activeId).toBe(ws.launcher.id); // b → launcher
    ws.cycle(1);
    expect(ws.activeId).toBe(a.id); // launcher → a (wraps)
    ws.cycle(-1);
    expect(ws.activeId).toBe(ws.launcher.id); // back to launcher
  });
});

describe("closeWorkspace (3c)", () => {
  it("confirms with live-pane count, flushes the layout BEFORE clearing, GCs streams, activates the neighbor", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/a");
    await launchWorkspace(ws, "C:/b");
    const [a, b] = ws.runtimes;
    a.tabs.value = [bareTab("t-a", true)];
    a.paneStreams.value["t-a"] = ["chunk"];
    a.streamCursor.value["t-a"] = 1;

    await ws.closeWorkspace(a.id);

    expect(confirmDialog).toHaveBeenCalledWith(expect.stringContaining("1"));
    expect(ws.runtimes.map((r) => r.id)).toEqual([b.id]);
    expect(ws.activeId).toBe(b.id); // right neighbor
    // The layout was persisted while tabs were still present (G-07).
    const calls = mockIpc.saveHistory.mock.calls as [number, HistoryPatch][];
    const last = calls[calls.length - 1]?.[1];
    expect(last?.workspaces.some((w) => w.layout?.tabs?.length === 1)).toBe(true);
    // Stream buffers GC'd (first writer ever).
    expect(Object.keys(a.paneStreams.value)).toHaveLength(0);
    expect(a.streamCursor.value).toEqual({});
  });

  it("keeps the workspace open on stop failure (error state, retryable)", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/a");
    mockIpc.stopRuntime.mockResolvedValue({ state: "running" });
    mockIpc.runtimeInspect.mockResolvedValue({ state: "running" });
    await ws.closeWorkspace(ws.runtimes[0].id);
    expect(ws.runtimes).toHaveLength(1);
    expect(ws.runtimes[0].status.value).toBe("error");
  });
});

describe("merged history save (3c)", () => {
  it("two dirty workspaces coalesce into ONE saveHistory call with both records", async () => {
    vi.useFakeTimers();
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/a");
    await launchWorkspace(ws, "C:/b");
    mockIpc.saveHistory.mockClear();
    // Arm dirt on both instances via their own actions (activateTab →
    // scheduleSave → markDirty(id)).
    for (const r of ws.runtimes) {
      r.tabs.value = [bareTab(`t-${r.id}`)];
      r.activateTab(`t-${r.id}`);
    }
    await Promise.resolve();
    expect(mockIpc.saveHistory).not.toHaveBeenCalled(); // inside the window
    await vi.advanceTimersByTimeAsync(300);
    expect(mockIpc.saveHistory).toHaveBeenCalledTimes(1);
    const [, patch] = mockIpc.saveHistory.mock.calls[0] as [number, HistoryPatch];
    expect(patch.workspaces).toHaveLength(2);
    vi.useRealTimers();
  });
});

describe("aggregated exit gate (3c)", () => {
  it("counts live panes across ALL workspaces, not just the active one", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/a");
    await launchWorkspace(ws, "C:/b");
    ws.runtimes[0].tabs.value = [bareTab("t-a", true)];
    ws.runtimes[1].tabs.value = [bareTab("t-b", true)];
    // Focus a; b's pane must still be counted.
    ws.activate(ws.runtimes[0].id);
    vi.mocked(confirmDialog).mockResolvedValueOnce(false);
    const ok = await ws.confirmExit();
    expect(ok).toBe(false);
    expect(confirmDialog).toHaveBeenCalledWith(expect.stringContaining("2"));
    expect(ws.livePaneCount()).toBe(2);
  });
});
