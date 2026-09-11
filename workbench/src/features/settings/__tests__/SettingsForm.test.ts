/**
 * Manual-test #1 regression (2026-09-06): P8 added the 'performance' section
 * to the section list but not to GROUP_KEY — `t(undefined)` threw SyntaxError
 * mid-render, which aborted the App patch and froze the whole UI (settings
 * chip switched, content stuck on the workspace view, dead until restart).
 *
 * This mounts the REAL form with the REAL i18n bundles: every section heading
 * must translate. A future section added to GROUPS without a GROUP_KEY entry
 * (or a missing dictionary key) fails here at test time instead of bricking
 * the app at runtime.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useSettingsStore } from "../../../stores/settings";
import SettingsForm from "../SettingsForm.vue";
import type { SettingsDocument } from "../../../types";

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  loadSettings: vi.fn(),
  saveSettings: vi.fn(),
  resetGuiSettings: vi.fn(),
  cacheUsage: vi.fn().mockResolvedValue({ dockerAvailable: true, rows: [] }),
  lowSpecStatus: vi.fn().mockResolvedValue({ totalRam: 16 * 1024 ** 3, lowSpec: false }),
}));

vi.mock("../../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn().mockResolvedValue(true) }));

const doc: SettingsDocument = {
  schemaVersion: 1,
  revision: 3,
  aiscCliPath: "C:\\aisc.exe",
  ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: [], default_new_page: "workspace", default_tab_agent: "bash" },
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
  hostTools: [],
  remoteMachines: [],
  performance: { lowSpec: false, containerMemory: "3g", containerCpus: 1.5 },
  issues: [],
  corrupted: false,
  readOnly: false,
};

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mockIpc.loadSettings.mockResolvedValue(JSON.parse(JSON.stringify(doc)));
});

describe("SettingsForm section headings (manual-test #1)", () => {
  it("P2-5: nav carries every section; the pane shows the ACTIVE one", async () => {
    const store = useSettingsStore();
    await store.load();
    const wrapper = mount(SettingsForm, { global: { plugins: [i18n] } });

    // The nav lists all seven sections; the pane renders only the active
    // one (VS Code-style left nav + right content — 手测裁决 2026-09-12).
    const nav = wrapper.findAll(".nav-item").map((b) => b.text());
    expect(nav).toEqual([
      i18n.global.t("settings.group.ui"),
      i18n.global.t("settings.group.terminal"),
      i18n.global.t("settings.group.window"),
      i18n.global.t("settings.group.hostTools"),
      i18n.global.t("settings.group.machines"),
      i18n.global.t("settings.group.performance"),
      i18n.global.t("settings.group.disk"),
    ]);
    expect(wrapper.findAll("h3.group").map((h) => h.text())).toEqual([
      i18n.global.t("settings.group.ui"),
    ]);
    // Picking a section swaps the pane and leaves search mode.
    await wrapper.findAll(".nav-item")[4]!.trigger("click");
    expect(wrapper.findAll("h3.group").map((h) => h.text())).toEqual([
      i18n.global.t("settings.group.machines"),
    ]);
  });

  it("P2-5: search dims non-matching nav entries and shows matching groups", async () => {
    const store = useSettingsStore();
    await store.load();
    const wrapper = mount(SettingsForm, { global: { plugins: [i18n] } });

    await wrapper.find(".nav-search").setValue("字体");
    // Terminal matches (字体/字号); ui does not (no such label).
    const dimmed = wrapper.findAll(".nav-item.dim").map((b) => b.text());
    expect(dimmed).not.toContain(i18n.global.t("settings.group.terminal"));
    expect(wrapper.findAll("h3.group").map((h) => h.text())).toContain(
      i18n.global.t("settings.group.terminal"),
    );
    expect(wrapper.findAll("h3.group").map((h) => h.text())).not.toContain(
      i18n.global.t("settings.group.ui"),
    );
  });

  it("renders the low-spec memory/cpus inputs when lowSpec is on", async () => {
    mockIpc.loadSettings.mockResolvedValue(
      JSON.parse(JSON.stringify({ ...doc, performance: { lowSpec: true, containerMemory: "2g", containerCpus: 1.0 } })),
    );
    const store = useSettingsStore();
    await store.load();
    const wrapper = mount(SettingsForm, { global: { plugins: [i18n] } });

    // P2-5: navigate to the performance section first (single-section pane).
    await wrapper.findAll(".nav-item")[5]!.trigger("click");
    const body = wrapper.text();
    expect(body).toContain(i18n.global.t("settings.perf.memory"));
    expect(body).toContain(i18n.global.t("settings.perf.cpus"));
  });
});
