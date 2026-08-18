/**
 * IDEA-3 (3c): the workspace strip — chips for every workspace (not just the
 * active one), activation on click, × closing via closeWorkspace, the
 * single-flight launcher chip and the MAX_WORKSPACES cap.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore, MAX_WORKSPACES } from "../../../stores/workspaces";
import WorkspaceBar from "../WorkspaceBar.vue";

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

vi.mock("../../../lib/ipc", () => mockIpc);
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

async function launchWorkspace(ws: ReturnType<typeof useWorkspacesStore>, path: string): Promise<void> {
  ws.launcher.workspace.value = path;
  ws.launcher.runtimeId.value = `rid-${path}`;
  await ws.launcher.initTabs([]);
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  i18n.global.locale.value = "zh-CN";
});

describe("WorkspaceBar (3c)", () => {
  it("renders one chip per workspace + the launcher chip, marking the active", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    await launchWorkspace(ws, "C:/beta");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const chips = bar.findAll(".chip");
    expect(chips).toHaveLength(3); // 2 workspaces + launcher
    const active = chips.filter((c) => c.classes("active"));
    expect(active).toHaveLength(1);
    expect(active[0]!.text()).toContain("beta");
    expect(chips[chips.length - 1]!.text()).toContain("新建工作区");
    // Roles for a11y (full roving polish lands in 3e).
    expect(bar.find('[role="tablist"]').exists()).toBe(true);
    expect(chips[0]!.attributes("role")).toBe("tab");
  });

  it("activates a workspace on chip click", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    await launchWorkspace(ws, "C:/beta");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const first = bar.findAll(".chip")[0]!;
    expect(ws.activeId).not.toBe(ws.runtimes[0].id);
    await first.trigger("click");
    expect(ws.activeId).toBe(ws.runtimes[0].id);
  });

  it("× closes via closeWorkspace (confirmed path removes the chip)", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    await launchWorkspace(ws, "C:/beta");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const first = bar.findAll(".chip")[0]!;
    await first.find(".close").trigger("click");
    await vi.waitFor(() => expect(ws.runtimes).toHaveLength(1));
    expect(ws.runtimes[0].workspace.value).toBe("C:/beta");
  });

  it("refuses new launches at the cap without moving focus", async () => {
    const ws = useWorkspacesStore();
    for (let i = 0; i < MAX_WORKSPACES; i++) {
      await launchWorkspace(ws, `C:/w${i}`);
    }
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const launcherChip = bar.findAll(".chip")[bar.findAll(".chip").length - 1]!;
    const active = ws.activeId;
    await launcherChip.trigger("click");
    expect(ws.activeId).toBe(active); // cap: no launcher activation
  });
});
