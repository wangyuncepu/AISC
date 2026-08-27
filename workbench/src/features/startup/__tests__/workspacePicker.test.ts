/**
 * v2.1.7 S2 (⑦⑧): the picker's history UX — the 8-entry cap with inline
 * expand, the moved/deleted click guard (record-only clear), and the
 * forget flow (preview dialog → single-IPC transaction, blocked state
 * disables the destructive button, CAS failure keeps the dialog open).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore } from "../../../stores/workspaces";
import WorkspacePicker from "../WorkspacePicker.vue";
import type { ForgetPreview, WorkbenchHistory } from "../../../types";

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  loadHistory: vi.fn(),
  saveHistory: vi.fn().mockResolvedValue(1),
  workspacePathExists: vi.fn(),
  workspaceForgetPreview: vi.fn(),
  workspaceForget: vi.fn(),
  workspaceHistoryRemove: vi.fn().mockResolvedValue(2),
  // facade wiring (not exercised here, but imported at module load)
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  closeSession: vi.fn().mockResolvedValue({}),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  openSession: vi.fn().mockResolvedValue({}),
  writeSession: vi.fn().mockResolvedValue(undefined),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  stopRuntime: vi.fn().mockResolvedValue({ state: "stopped" }),
  runtimeInspect: vi.fn().mockResolvedValue({ state: "stopped" }),
  removeRuntime: vi.fn().mockResolvedValue({ state: "not_found" }),
  leaseClaim: vi.fn().mockResolvedValue({ outcome: "claimed", lease_id: "l", workspace_key: "k" }),
  leaseRelease: vi.fn().mockResolvedValue(true),
  runtimeReconcile: vi.fn().mockResolvedValue({
    schema_version: "aisc.runtime-reconcile/v1", workspace_key: "k",
    classification: "clean", runtime_id: null, can_proceed: true,
    cleanup: { attempted: false, stopped: false, removed: false, registry_pruned: false },
    observed_at: "", error_code: null, technical_detail: null,
  }),
}));

vi.mock("../../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn().mockResolvedValue(true), open: vi.fn() }));
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

function historyWith(n: number): WorkbenchHistory {
  return {
    schema_version: 2,
    revision: 1,
    workspaces: Array.from({ length: n }, (_, i) => ({
      path: `C:\\ws\\project-${i + 1}`,
      last_used_at: `2026-08-27T00:0${i}:00Z`,
      last_agent: "claude",
      pinned: false,
      runtime: null,
      layout: null,
    })),
  };
}

function mountPicker() {
  return mount(WorkspacePicker, { global: { plugins: [i18n] } });
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});
afterEach(() => vi.clearAllMocks());

describe("recents cap + inline expand (⑦)", () => {
  it("caps the list at 8 with a show-all toggle, then collapses", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(10);
    ws.historyRevision = 1;
    const w = mountPicker();
    expect(w.findAll(".recent")).toHaveLength(8);
    const expand = w.find(".expand");
    expect(expand.text()).toContain("2");

    await expand.trigger("click");
    expect(w.findAll(".recent")).toHaveLength(10);
    expect(w.find(".expand").text()).toContain("收起");

    await w.find(".expand").trigger("click");
    expect(w.findAll(".recent")).toHaveLength(8);
  });

  it("renders all rows without a toggle when history fits the cap", () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(5);
    ws.historyRevision = 1;
    const w = mountPicker();
    expect(w.findAll(".recent")).toHaveLength(5);
    expect(w.find(".expand").exists()).toBe(false);
  });
});

describe("moved/deleted click guard (⑧)", () => {
  it("opens the invalid dialog for a missing path and clears ONLY the record", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(1);
    ws.historyRevision = 1;
    mockIpc.workspacePathExists.mockResolvedValue(false);
    const w = mountPicker();

    await w.find(".recent").trigger("click");
    await flushPromises();
    expect(w.find('[role="dialog"]').exists()).toBe(true);
    expect(w.text()).toContain("已移动或删除");

    mockIpc.loadHistory.mockResolvedValue(historyWith(0));
    await w.findAll(".foot button")[1].trigger("click"); // 清除记录
    expect(mockIpc.workspaceHistoryRemove).toHaveBeenCalledWith("C:\\ws\\project-1", 1);
    expect(mockIpc.workspaceForget).not.toHaveBeenCalled();
    expect(w.find('[role="dialog"]').exists()).toBe(false);
  });

  it("launches preflight directly when the path exists", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(1);
    ws.historyRevision = 1;
    mockIpc.workspacePathExists.mockResolvedValue(true);
    const w = mountPicker();
    await w.find(".recent").trigger("click");
    await flushPromises();
    expect(mockIpc.workspaceHistoryRemove).not.toHaveBeenCalled();
    // selectRecentWorkspace ran: the input holds the chosen path.
    expect((w.find(".workspace").element as HTMLInputElement).value).toBe("C:\\ws\\project-1");
  });
});

describe("forget flow (⑦)", () => {
  const PREVIEW_OK: ForgetPreview = {
    workspacePath: "C:\\ws\\project-1",
    workspaceKey: "sha256-v1:abc",
    blockedReason: null,
    dataPresent: true,
    categories: ["claude", "toolchain", "other:2"],
    namedVolumes: ["aisc-toolchain-x"],
    warnings: [],
  };

  it("previews, confirms, executes the single IPC and refreshes history", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(1);
    ws.historyRevision = 3;
    mockIpc.workspaceForgetPreview.mockResolvedValue(PREVIEW_OK);
    mockIpc.workspaceForget.mockResolvedValue({
      workspaceKey: "sha256-v1:abc", historyRemoved: true, dataRemoved: true,
      quarantineLeft: null, namedVolumesKept: [], warnings: [],
    });
    mockIpc.loadHistory.mockResolvedValue(historyWith(0));
    const w = mountPicker();

    await w.find(".kebab").trigger("click");
    await w.find(".ctx-item").trigger("click");
    await flushPromises();
    expect(mockIpc.workspaceForgetPreview).toHaveBeenCalledWith("C:\\ws\\project-1");

    // Dialog shows categories, the kept-volume note and the safety line.
    const dialog = w.find('[role="dialog"]');
    expect(dialog.text()).toContain("持久工具链");
    expect(dialog.text()).toContain("不会被删除");
    expect(dialog.text()).toContain("不会被触碰");

    await w.findAll(".foot button")[1].trigger("click"); // 彻底忘记
    await flushPromises();
    expect(mockIpc.workspaceForget).toHaveBeenCalledWith("C:\\ws\\project-1", 3);
    expect(mockIpc.loadHistory).toHaveBeenCalled();
    expect(w.find('[role="dialog"]').exists()).toBe(false);
  });

  it("disables the destructive button while the workspace is active", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(1);
    ws.historyRevision = 1;
    mockIpc.workspaceForgetPreview.mockResolvedValue({
      ...PREVIEW_OK, blockedReason: "open-here",
    });
    const w = mountPicker();
    await w.find(".kebab").trigger("click");
    await w.find(".ctx-item").trigger("click");
    await flushPromises();
    const confirmBtn = w.findAll(".foot button")[1];
    expect((confirmBtn.element as HTMLButtonElement).disabled).toBe(true);
    expect(w.text()).toContain("当前窗口");
    expect(mockIpc.workspaceForget).not.toHaveBeenCalled();
  });

  it("keeps the dialog open on a CAS conflict so the user can retry", async () => {
    const ws = useWorkspacesStore();
    ws.history = historyWith(1);
    ws.historyRevision = 1;
    mockIpc.workspaceForgetPreview.mockResolvedValue(PREVIEW_OK);
    mockIpc.workspaceForget.mockRejectedValue(new Error("conflict"));
    mockIpc.loadHistory.mockResolvedValue(historyWith(1));
    const w = mountPicker();
    await w.find(".kebab").trigger("click");
    await w.find(".ctx-item").trigger("click");
    await flushPromises();
    await w.findAll(".foot button")[1].trigger("click");
    await flushPromises();
    expect(w.find('[role="dialog"]').exists()).toBe(true);
    // History was still refreshed so a retry uses the new revision.
    expect(mockIpc.loadHistory).toHaveBeenCalled();
  });
});
