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
  ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: [], default_tab_agent: "bash" },
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
    expect(chips).toHaveLength(4); // 2 workspaces + launcher + settings (always present)
    const active = chips.filter((c) => c.classes("active"));
    expect(active).toHaveLength(1);
    expect(active[0]!.text()).toContain("beta");
    expect(chips[chips.length - 2]!.text()).toContain("新建工作区");
    expect(chips[chips.length - 1]!.text()).toContain("设置");
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
    const all = bar.findAll(".chip");
    const launcherChip = all[all.length - 2]!;
    const active = ws.activeId;
    await launcherChip.trigger("click");
    expect(ws.activeId).toBe(active); // cap: no launcher activation
  });

  it("+ split button: + opens the launcher, ▾ menu 设置 opens the settings tab", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] }, attachTo: document.body });
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

  it("Settings chip (3d): renders when open, × reverts unsaved edits then closes", async () => {
    const ws = useWorkspacesStore();
    await launchWorkspace(ws, "C:/alpha");
    const bar = mount(WorkspaceBar, { global: { plugins: [i18n] } });
    // Always-present settings chip: no × until open.
    let settingsChip = bar.findAll(".chip")[bar.findAll(".chip").length - 1]!;
    expect(settingsChip.text()).toContain("设置");
    expect(settingsChip.find(".close").exists()).toBe(false);
    ws.openSettingsTab();
    expect(ws.settingsTabActive).toBe(true);
    await nextTick(); // store mutation → DOM update is async
    settingsChip = bar.findAll(".chip")[bar.findAll(".chip").length - 1]!;
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
});
