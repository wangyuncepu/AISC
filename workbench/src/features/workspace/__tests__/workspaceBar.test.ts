/**
 * IDEA-3 (3c): the workspace strip — chips for every workspace (not just the
 * active one), activation on click, × closing via closeWorkspace, the
 * single-flight launcher chip and the MAX_WORKSPACES cap.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore, MAX_WORKSPACES } from "../../../stores/workspaces";
import WorkspaceBar from "../WorkspaceBar.vue";


const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
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
  runtimeStatus: vi.fn().mockResolvedValue({ snapshot: { state: "stopped" }, services: null }),
  // runtime-lifecycle-ux Stage 3: the background close teardown
  // (stop -> verify -> remove -> lease release) needs these on the mock,
  // otherwise the path silently degrades and logs on every close test.
  removeRuntime: vi.fn().mockResolvedValue({ state: "not_found" }),
  leaseRelease: vi.fn().mockResolvedValue(true),
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
  it("round-3 model: only REAL open pages — workspaces only once one is active", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    await launchWorkspace(ws, "C:/beta");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const chips = bar.findAll(".chip");
    // 2 workspaces; the launcher chip is GONE (a workspace is focused) and
    // settings is closed — no persistent chips.
    expect(chips).toHaveLength(2);
    const active = chips.filter((c) => c.classes("active"));
    expect(active).toHaveLength(1);
    expect(active[0]!.text()).toContain("beta");
    expect(chips.some((c) => c.text().includes("新建工作区"))).toBe(false);
    expect(chips.some((c) => c.text().includes("设置"))).toBe(false);
    expect(bar.find('[role="tablist"]').exists()).toBe(true);
    expect(chips[0]!.attributes("role")).toBe("tab");
  });

  it("the launcher chip reappears while it is the FOCUSED page (+ re-opens it)", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    expect(bar.text()).not.toContain("新建工作区"); // hidden: workspace focused
    await bar.find(".add-group .add").trigger("click"); // + opens the launcher
    await nextTick();
    expect(ws.activeId).toBe(ws.launcher.id);
    const chips = bar.findAll(".chip");
    expect(chips.some((c) => c.text().includes("新建工作区"))).toBe(true);
    bar.unmount();
  });

  it("round-4 labels: folder name only; full path only to disambiguate same-name folders", async () => {
    const ws = useWorkspacesStore();
    // Windows backslashed paths (the round-4 bug: "/"-only basename leaked
    // the whole path) + a same-name pair elsewhere.
    await launchWorkspace(ws, "C:\\Users\\me\\projects\\alpha");
    await launchWorkspace(ws, "D:\\work\\alpha");
    await launchWorkspace(ws, "C:\\solo");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const labels = bar.findAll(".chip .name").map((n) => n.text());
    expect(labels).toContain("solo"); // unique → bare folder name
    // Both alpha folders show their FULL paths to disambiguate.
    expect(labels.some((l) => l.includes("projects\\alpha"))).toBe(true);
    expect(labels.some((l) => l.includes("D:\\work\\alpha"))).toBe(true);
    expect(labels.some((l) => l === "alpha")).toBe(false);
    bar.unmount();
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

  it("refuses new launches at the cap: the + button disables (workspace default)", async () => {
    const ws = useWorkspacesStore();
    for (let i = 0; i < MAX_WORKSPACES; i++) {
      await launchWorkspace(ws, `C:/w${i}`);
    }
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    const plus = bar.find(".add-group .add");
    expect(plus.attributes("disabled")).toBeDefined();
    const active = ws.activeId;
    await plus.trigger("click");
    expect(ws.activeId).toBe(active); // cap: no launcher activation
  });

  // W1 (shell-redesign): the ▾ menu + settings/network-usage strip chips
  // are RETIRED (rail-bottom floating panes own those entries now); their
  // tests left with them. The + launcher half survives below.
  it("+ button opens the launcher (W1: the ▾ half is retired)", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] }, attachTo: document.body });
    await bar.find(".add-group .add").trigger("click");
    expect(ws.activeId).toBe(ws.launcher.id);
    expect(bar.find(".add-group .add-caret").exists()).toBe(false);
    bar.unmount();
  });

});
