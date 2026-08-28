/**
 * runtime-lifecycle-ux Stage 3: the launcher's reconcile-first preflight.
 *
 * - can_proceed → preflight runs with a FRESH runtime id (history refs never
 *   drive reuse; the old listRuntimes discovery is gone);
 * - active_other_instance / unknown_owner → conflict status (the Stage 4
 *   minimal block page renders there);
 * - active_same_instance → the shell focuses the existing workspace and the
 *   launcher resets to picker silently (01 §1.3);
 * - reconcile transport failure falls through to preflight (its docker gate
 *   surfaces the real error).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkspacesStore } from "../workspaces";

const PASSING_PREFLIGHT = {
  spec: {}, checks: [], can_start: true,
  recommended_action: "start", matching_runtime_id: null,
  conflicts: [], observed_at: "",
};

function reconcilePayload(over: Record<string, unknown>) {
  return {
    schema_version: "aisc.runtime-reconcile/v1",
    workspace_key: "k", classification: "clean", runtime_id: null,
    can_proceed: true,
    cleanup: { attempted: false, stopped: false, removed: false, registry_pruned: false },
    observed_at: "", error_code: null, technical_detail: null,
    ...over,
  };
}

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  runtimeReconcile: vi.fn(),
  runtimePreflight: vi.fn(),
}));

vi.mock("../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
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

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mockIpc.runtimeReconcile.mockResolvedValue(reconcilePayload({}));
  mockIpc.runtimePreflight.mockResolvedValue({ ...PASSING_PREFLIGHT });
});

describe("reconcile-first preflight (Stage 3)", () => {
  it("clean reconcile → preflight runs with a FRESH runtime id, no listRuntimes discovery", async () => {
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    expect(mockIpc.runtimeReconcile).toHaveBeenCalledWith("C:/ws");
    expect(mockIpc.runtimePreflight).toHaveBeenCalledTimes(1);
    // The pre-existing-runtime discovery is gone: every launch mints fresh.
    expect(mockIpc.listRuntimes).not.toHaveBeenCalled();
    expect(ws.launcher.runtimeId.value).not.toBe("");
    expect(ws.launcher.status.value).toBe("summary");
  });

  it("each preflight mints a NEW id (never the recycled runtime's)", async () => {
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    const first = ws.launcher.runtimeId.value;
    ws.launcher.preflight.value = null;
    await ws.launcher.runPreflight();
    expect(ws.launcher.runtimeId.value).not.toBe(first);
  });

  it("active_other_instance → conflict status, preflight skipped", async () => {
    mockIpc.runtimeReconcile.mockResolvedValue(reconcilePayload({
      classification: "active_other_instance", can_proceed: false,
      error_code: "AISC_ERR_ACTIVE_WORKSPACE_LEASE",
    }));
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    expect(ws.launcher.status.value).toBe("conflict");
    expect(ws.launcher.reconcile.value?.classification).toBe("active_other_instance");
    expect(mockIpc.runtimePreflight).not.toHaveBeenCalled();
  });

  it("active_same_instance → focus the existing workspace, launcher resets to picker", async () => {
    const ws = useWorkspacesStore();
    // Materialize C:/ws through the real path (initTabs → onReady).
    ws.launcher.workspace.value = "C:/ws";
    ws.launcher.runtimeId.value = "rid-live";
    await ws.launcher.initTabs([]);
    expect(ws.runtimes).toHaveLength(1);

    // A second launcher pass on the same path: reconcile says same instance.
    mockIpc.runtimeReconcile.mockResolvedValue(reconcilePayload({
      classification: "active_same_instance", can_proceed: false,
    }));
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    expect(ws.launcher.status.value).toBe("picker");
    // resetWorkspace() deliberately keeps the path (backToPicker semantics)
    // — the launcher is simply back at the picker, never started a runtime.
    expect(ws.launcher.runtimeId.value).toBe("");
    expect(ws.activeId).toBe(ws.runtimes[0].id); // focused the existing one
    expect(mockIpc.runtimePreflight).not.toHaveBeenCalled();
  });

  it("reconcile transport failure falls through to preflight (docker gate reports)", async () => {
    mockIpc.runtimeReconcile.mockRejectedValue(new Error("transport"));
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    expect(ws.launcher.status.value).toBe("summary");
    expect(mockIpc.runtimePreflight).toHaveBeenCalledTimes(1);
    expect(ws.launcher.reconcile.value).toBeNull();
  });

  it("docker_unavailable is not a conflict — falls through to preflight (S8a)", async () => {
    // The old route parked docker-down launches on the generic 「启动已被阻断」
    // block page with the reason hidden behind 诊断; the summary's docker gate
    // is the actionable place (启动 Docker button + auto wake-up).
    mockIpc.runtimeReconcile.mockResolvedValue(reconcilePayload({
      classification: "docker_unavailable", can_proceed: false,
      error_code: "AISC_ERR_DOCKER_UNAVAILABLE",
      technical_detail: "docker daemon/CLI unavailable; nothing removed",
    }));
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    await ws.launcher.runPreflight();
    expect(ws.launcher.status.value).toBe("summary");
    expect(mockIpc.runtimePreflight).toHaveBeenCalledTimes(1);
    expect(ws.launcher.reconcile.value?.classification).toBe("docker_unavailable");
  });
});
