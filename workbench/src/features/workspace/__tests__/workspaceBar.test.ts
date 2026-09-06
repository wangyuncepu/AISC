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
import { useSettingsStore } from "../../../stores/settings";
import type { SettingsDocument } from "../../../types";
import WorkspaceBar from "../WorkspaceBar.vue";

/** Minimal settings doc fixture (full section shapes for vue-tsc). */
const settingsDoc: SettingsDocument = {
  schemaVersion: 1,
  revision: 0,
  aiscCliPath: null,
  ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: [], default_tab_agent: "bash", default_new_page: "workspace" },
  terminal: {
    font_family: "Cascadia Mono, Consolas, monospace",
    font_size: 14,
    line_height: 1.2,
    letter_spacing: 0,
    scrollback: 5000,
    renderer: "auto",
    smooth_scroll_duration: 100,
  },
  window: { remember_geometry: true, close_behavior: "quit", geometry: null },
  issues: [],
  corrupted: false,
  readOnly: false,
};

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

  it("+ split button: + opens the launcher, ▾ menu 设置 opens the settings tab", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] }, attachTo: document.body });
    // 10d: menu placement measures the anchor rect — jsdom has no layout, so
    // stub a real one (the zero-rect guard would otherwise refuse to open).
    (bar.element.querySelector(".add-group .add-caret") as HTMLElement).getBoundingClientRect = () =>
      ({ left: 400, right: 420, top: 40, bottom: 60, width: 20, height: 20, x: 400, y: 40 }) as DOMRect;
    // + activates the launcher (default new workspace).
    await bar.find(".add-group .add").trigger("click");
    expect(ws.activeId).toBe(ws.launcher.id);
    // ▾ menu: teleported, carries 设置, opens the workspace-layer sentinel.
    await bar.find(".add-group .add-caret").trigger("click");
    const item = document.querySelector(".wsp-menu.menu [role=menuitem]") as HTMLElement;
    expect(item).toBeTruthy();
    expect(item.textContent).toContain("设置");
    item.click();
    await nextTick();
    expect(ws.settingsTabActive).toBe(true);
    bar.unmount();
  });

  it("Settings chip (3d): exists only while open, × reverts unsaved edits then closes", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    // Closed: no settings chip at all (round-3 model).
    expect(bar.findAll(".chip").some((c) => c.text().includes("设置"))).toBe(false);
    ws.openSettingsTab();
    expect(ws.settingsTabActive).toBe(true);
    await nextTick(); // store mutation → DOM update is async
    const settingsChip = bar.findAll(".chip")[bar.findAll(".chip").length - 1]!;
    expect(settingsChip.text()).toContain("设置");
    expect(settingsChip.classes()).toContain("active");
    expect(settingsChip.find(".close").exists()).toBe(true);

    // Dirty the settings form, then ×: cancel() reverts to lastSaved, sentinel closes.
    const settings = useSettingsStore();
    settings.doc = {
      ...settingsDoc,
      ui: { ...settingsDoc.ui, language: "en-US" },
    };
    settings.lastSaved = JSON.parse(JSON.stringify(settingsDoc)) as SettingsDocument;
    await settingsChip.find(".close").trigger("click");
    expect(settings.doc?.ui.language).toBe("auto"); // reverted
    expect(ws.settingsTabOpen).toBe(false);
    expect(ws.activeId).toBe(ws.runtimes[0].id); // falls back to the last workspace
  });

  it("▾ menu 网络与用量 opens the network-usage sentinel (IDEA-2 2d)", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] }, attachTo: document.body });
    // 10d: menu placement measures the anchor rect — jsdom has no layout, so
    // stub a real one (the zero-rect guard would otherwise refuse to open).
    (bar.element.querySelector(".add-group .add-caret") as HTMLElement).getBoundingClientRect = () =>
      ({ left: 400, right: 420, top: 40, bottom: 60, width: 20, height: 20, x: 400, y: 40 }) as DOMRect;
    await bar.find(".add-group .add-caret").trigger("click");
    const items = [...document.querySelectorAll(".wsp-menu.menu [role=menuitem]")];
    const usage = items.find((el) => el.textContent?.includes("网络与用量"));
    expect(usage, "menu must list 网络与用量").toBeTruthy();
    (usage as HTMLElement).click();
    await nextTick();
    expect(ws.networkUsageTabActive).toBe(true);
    expect(ws.settingsTabActive).toBe(false); // the two sentinels are independent
    bar.unmount();
  });

  it("Network-usage chip: exists only while open, × closes and falls back", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    expect(bar.findAll(".chip").some((c) => c.text().includes("网络与用量"))).toBe(false);
    ws.openNetworkUsageTab();
    await nextTick();
    const chip = bar.findAll(".chip").find((c) => c.text().includes("网络与用量"))!;
    expect(chip.classes()).toContain("active");
    expect(chip.find(".close").exists()).toBe(true);
    await chip.find(".close").trigger("click");
    expect(ws.networkUsageTabOpen).toBe(false);
    expect(ws.activeId).toBe(ws.runtimes[0].id); // falls back to the last workspace
  });
});
