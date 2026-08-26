/**
 * runtime-lifecycle-ux Stage 5: lazy layout restore (01 §4.2).
 *
 * - history layout → dormant placeholder tabs; ONLY the active tab opens a
 *   session at start; others wake on activation (fresh ids, never a reattach)
 * - no layout → the default single Bash tab (G-08 fallback)
 * - re-activating a woken tab never double-opens (gate bails on starting)
 * - closing a dormant placeholder never terminates anything (no sessionId,
 *   no closeSession call) — only history changes
 * - dormant renders distinct from exited (TabBar label/class)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../i18n";
import { useWorkspacesStore } from "../workspaces";
import { useRuntimeStore } from "../runtime";
import TabBar from "../../features/workspace/TabBar.vue";
import type { HistoryPatch, TabRecord } from "../../types";

const PASSING_PREFLIGHT = {
  spec: {}, checks: [], can_start: true,
  recommended_action: "start", matching_runtime_id: null,
  conflicts: [], observed_at: "",
};

function reconcilePayload() {
  return {
    schema_version: "aisc.runtime-reconcile/v1",
    workspace_key: "k", classification: "clean", runtime_id: null,
    can_proceed: true,
    cleanup: { attempted: false, stopped: false, removed: false, registry_pruned: false },
    observed_at: "", error_code: null, technical_detail: null,
  };
}

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  runtimeReconcile: vi.fn(),
  runtimePreflight: vi.fn(),
  startRuntime: vi.fn().mockResolvedValue({}),
  leaseClaim: vi.fn().mockResolvedValue({ outcome: "claimed", lease_id: "l", workspace_key: "k" }),
  openSession: vi.fn().mockResolvedValue({ session_id: "s-1" }),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  getProviderStatus: vi.fn().mockResolvedValue({}),
}));

vi.mock("../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({
  Channel: class {
    onmessage: unknown = null;
  },
}));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
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

function layoutRecord(tabs: TabRecord[], activeTabId: string | null) {
  return {
    schema_version: 2,
    revision: 1,
    workspaces: [
      {
        path: "/ws",
        last_used: "2026-08-25T00:00:00Z",
        runtime: null,
        last_agent: "bash",
        layout: { schema_version: 2, tabs, active_tab_id: activeTabId },
      },
    ],
  };
}

function lastRec() {
  const calls = mockIpc.saveHistory.mock.calls as [number, HistoryPatch][];
  const patch = calls[calls.length - 1]?.[1];
  return patch?.workspaces?.find((w) => w.path?.includes("ws"));
}

function bashRecord(id: string, pos: number): TabRecord {
  return { tab_id: id, agent: "bash", title: "Bash", position: pos };
}

async function launch(wsPath = "/ws"): Promise<void> {
  const ws = useWorkspacesStore();
  await ws.loadHistory(); // normally runs with negotiate; tests skip negotiate
  ws.launcher.workspace.value = wsPath;
  await ws.launcher.runPreflight(); // reconcile → preflight (both mocked pass)
  await ws.launcher.startFromSummary();
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  vi.clearAllMocks();
  mockIpc.runtimeReconcile.mockResolvedValue(reconcilePayload());
  mockIpc.runtimePreflight.mockResolvedValue({ ...PASSING_PREFLIGHT });
  mockIpc.openSession.mockClear();
});
afterEach(() => vi.clearAllMocks());

describe("lazy layout restore (Stage 5)", () => {
  it("history layout restores as dormant placeholders; only the active tab opens", async () => {
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    const rt = useRuntimeStore();
    expect(rt.tabs).toHaveLength(2);
    // active = saved-b → its session opened; saved-a stays dormant.
    const b = rt.tabs.find((t) => t.savedTabId === "saved-b" || t.title === "Bash");
    const active = rt.tabs.find((t) => t.tabId === rt.activeTabId);
    expect(active).toBeTruthy();
    expect(mockIpc.openSession).toHaveBeenCalledTimes(1); // only the active tab
    const dormant = rt.tabs.find((t) => t.tabId !== rt.activeTabId);
    expect(dormant?.sessionState).toBe("dormant");
    expect(dormant?.sessionId).toBeNull();
    void b;
  });

  it("no history layout → default single Bash tab", async () => {
    mockIpc.loadHistory.mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] });
    await launch();
    const rt = useRuntimeStore();
    expect(rt.tabs).toHaveLength(1);
    expect(rt.tabs[0].agent).toBe("bash");
    expect(mockIpc.openSession).toHaveBeenCalledTimes(1);
  });

  it("activating a dormant tab wakes it once; re-activation never double-opens", async () => {
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    const ws = useWorkspacesStore();
    const rt = useRuntimeStore();
    const dormant = rt.tabs.find((t) => t.tabId !== rt.activeTabId)!;
    expect(dormant.sessionState).toBe("dormant");

    const inst = ws.runtimes.find((r) => r.workspace.value === "/ws")!;
    inst.activateTab(dormant.tabId);
    await Promise.resolve();
    expect(mockIpc.openSession).toHaveBeenCalledTimes(2); // active + woken
    expect(dormant.sessionState).not.toBe("dormant");

    const before = mockIpc.openSession.mock.calls.length;
    inst.activateTab(dormant.tabId); // re-activation: no double session
    await Promise.resolve();
    expect(mockIpc.openSession.mock.calls.length).toBe(before);
  });

  it("closing a dormant placeholder never terminates (no closeSession)", async () => {
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    const ws = useWorkspacesStore();
    const rt = useRuntimeStore();
    const dormant = rt.tabs.find((t) => t.tabId !== rt.activeTabId)!;
    const inst = ws.runtimes.find((r) => r.workspace.value === "/ws")!;
    mockIpc.closeSession.mockClear();
    inst.removeTab(dormant.tabId);
    expect(mockIpc.closeSession).not.toHaveBeenCalled(); // history-only change
    expect(rt.tabs).toHaveLength(1);
  });

  it("the layout persists (dormant never serialized — records carry no state)", async () => {
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    // The save is debounced 300ms — wait for the patch that carries BOTH
    // restored tabs (the first preflight-time save predates the tab set).
    let rec: Awaited<ReturnType<typeof lastRec>> | undefined;
    await vi.waitFor(() => {
      rec = lastRec();
      expect(rec?.layout?.tabs?.length).toBe(2);
    });
    expect(JSON.stringify(rec?.layout)).not.toContain("dormant");
  });

  it("TabBar renders dormant distinctly from exited", async () => {
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    const rt = useRuntimeStore();
    const w = mount(TabBar, { global: { plugins: [i18n] } });
    try {
      // B-02: the state label only surfaces after persisting 150ms.
      expect(w.find(".tab.dormant").exists()).toBe(true);
      await vi.waitFor(() => {
        expect(w.find(".tab.dormant").text()).toContain("待启动");
      });
      expect(w.find(".tab.dormant").text()).not.toContain("已退出");
    } finally {
      w.unmount();
      void rt;
    }
  });
});
