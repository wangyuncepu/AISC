/**
 * runtime-lifecycle-ux Stage 5 → O9 r2 (D-11, user ruling 2026-09-02):
 * NO layout restore. The lazy dormant-placeholder scheme (r0) and the
 * full-restore scheme (r1) are both gone — the user ruled that closing a
 * workspace closes it: reopening ALWAYS starts fresh from the default
 * single Bash tab, regardless of what the history layout records hold.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { i18n } from "../../i18n";
import { useWorkspacesStore } from "../workspaces";
import { useRuntimeStore } from "../runtime";
import type { TabRecord } from "../../types";

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
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn().mockResolvedValue(true), open: vi.fn() }));
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

describe("no layout restore (O9 r2, D-11)", () => {
  it("reopening a workspace with a saved layout starts FRESH: one default Bash tab", async () => {
    // A rich saved layout (two tabs, a split codex) must be IGNORED.
    const saved = layoutRecord(
      [bashRecord("saved-a", 0), bashRecord("saved-b", 1)],
      "saved-b"
    );
    mockIpc.loadHistory.mockResolvedValue(saved);
    await launch();
    const rt = useRuntimeStore();
    expect(rt.tabs).toHaveLength(1); // fresh default, not the 2 saved tabs
    expect(rt.tabs[0].agent).toBe("bash");
    // Fresh ids: the new tab binds to NONE of the saved records.
    expect(rt.tabs[0].savedTabId).not.toBe("saved-a");
    expect(rt.tabs[0].savedTabId).not.toBe("saved-b");
    expect(mockIpc.openSession).toHaveBeenCalledTimes(1); // only its session
  });

  it("no history at all → the same single Bash tab (identical path)", async () => {
    mockIpc.loadHistory.mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] });
    await launch();
    const rt = useRuntimeStore();
    expect(rt.tabs).toHaveLength(1);
    expect(rt.tabs[0].agent).toBe("bash");
    expect(mockIpc.openSession).toHaveBeenCalledTimes(1);
  });

  it("re-activating the running tab never double-opens its session", async () => {
    await launch();
    const ws = useWorkspacesStore();
    const rt = useRuntimeStore();
    const inst = ws.runtimes.find((r) => r.workspace.value === "/ws")!;
    const id = rt.tabs[0].tabId;
    const before = mockIpc.openSession.mock.calls.length;
    inst.activateTab(id);
    await Promise.resolve();
    expect(mockIpc.openSession.mock.calls.length).toBe(before);
  });
});
