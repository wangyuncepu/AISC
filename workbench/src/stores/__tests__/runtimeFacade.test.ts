/**
 * IDEA-3 (3a): the runtime store is a FACADE over one workspace instance
 * (`createWorkspaceRuntime`, stores/workspaceRuntime.ts). This locks the
 * forwarding contract every existing consumer relies on — direct state
 * assignment, deep mutation, watch reactivity, method forwarding, and the
 * shell-owned history cycle — before 3c swaps the fixed instance for the
 * workspaces store's active one. The hard 3a gate itself is "all other
 * suites green with zero test edits"; this file is the extra insurance.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { watch } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore, SETTINGS_TAB_ID } from "../runtime";
import { normalizePath } from "../tabLayout";
import type { Tab } from "../../types";

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

function bareTab(id: string): Tab {
  const paneId = id;
  return {
    tabId: id,
    agent: "bash",
    title: "Bash",
    sessionId: null,
    sessionState: "idle",
    exit: null,
    savedTabId: null,
    tree: { kind: "pane", paneId, sessionType: "bash" },
    activePaneId: paneId,
    panes: { [paneId]: { sessionId: null, sessionState: "idle", exit: null } },
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("facade state forwarding (3a)", () => {
  it("round-trips direct assignment through the store", () => {
    const s = useRuntimeStore();
    s.status = "summary";
    s.workspace = "C:/tmp/w";
    s.runtimeId = "rid";
    s.tabs = [bareTab("t1")];
    expect(s.status).toBe("summary");
    expect(s.workspace).toBe("C:/tmp/w");
    expect(s.runtimeId).toBe("rid");
    expect(s.tabs).toHaveLength(1);
    expect(s.tabs[0].tabId).toBe("t1");
  });

  it("sees deep mutations on forwarded objects", () => {
    const s = useRuntimeStore();
    s.tabs = [bareTab("t1")];
    s.tabs[0].title = "Claude";
    expect(s.tabs[0].title).toBe("Claude");
  });

  it("keeps watch() reactivity through the facade", async () => {
    const s = useRuntimeStore();
    const seen: (string | null)[] = [];
    const stop = watch(() => s.activeTabId, (v) => seen.push(v));
    s.openSettingsTab();
    await vi.waitFor(() => expect(seen).toContain(SETTINGS_TAB_ID));
    expect(s.settingsTabOpen).toBe(true);
    expect(s.activeTabId).toBe(SETTINGS_TAB_ID);
    stop();
  });

  it("forwards instance methods (closeSettingsTab falls back to the last tab)", () => {
    const s = useRuntimeStore();
    s.tabs = [bareTab("t1")];
    s.openSettingsTab();
    s.closeSettingsTab();
    expect(s.settingsTabOpen).toBe(false);
    expect(s.activeTabId).toBe("t1");
  });
});

describe("facade shell-owned surface (3a)", () => {
  it("exposes the shell keys (capability/history/negotiate/exit)", () => {
    const s = useRuntimeStore();
    expect(s.capability).toBeNull();
    expect(s.recentWorkspaces).toEqual([]);
    expect(typeof s.negotiate).toBe("function");
    expect(typeof s.pickAndPinCli).toBe("function");
    expect(typeof s.confirmExit).toBe("function");
    expect(typeof s.loadHistory).toBe("function");
  });

  it("loadHistory populates the shared history + recents", async () => {
    mockIpc.loadHistory.mockResolvedValue({
      schema_version: 1,
      revision: 2,
      workspaces: [
        { path: "C:/a", last_used_at: "2026-08-01T00:00:00Z" },
        { path: "C:/b", last_used_at: "2026-08-02T00:00:00Z" },
      ],
    });
    const s = useRuntimeStore();
    await s.loadHistory();
    expect(s.historyRevision).toBe(2);
    expect(s.recentWorkspaces.map((w) => w.path)).toEqual(["C:/b", "C:/a"]);
  });

  it("runs the merged save cycle: instance markDirty -> facade debounce -> one saveHistory", async () => {
    vi.useFakeTimers();
    const s = useRuntimeStore();
    s.workspace = "C:/tmp/w";
    s.runtimeId = "rid";
    s.runtimeState = "running";
    // createTab is an INSTANCE action whose scheduleSave lands on the facade.
    s.createTab("bash");
    await Promise.resolve(); // bash opens via a resolved ipc promise (microtask)
    expect(mockIpc.saveHistory).not.toHaveBeenCalled(); // debounce not fired yet
    await vi.advanceTimersByTimeAsync(300); // facade debounce fires
    expect(mockIpc.saveHistory).toHaveBeenCalledTimes(1);
    const [, patch] = mockIpc.saveHistory.mock.calls[0] as [number, { workspaces: { path: string }[] }];
    expect(patch.workspaces).toHaveLength(1);
    // normalizePath is platform-dependent (backslashes on Windows): expect the
    // function's own output, not a hardcoded separator form (CI runs Linux).
    expect(patch.workspaces[0].path).toBe(normalizePath("C:/tmp/w"));
  });
});
