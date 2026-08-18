/**
 * Stage 1 (S1.6, F-A06): TabBar structure / a11y.
 *
 * Regression for the invalid nested-`<button>` structure: the tab wrapper is a
 * non-interactive element, the activation button is the only `role=tab`, and
 * close/reopen are sibling buttons with accessible labels.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import { useSettingsStore } from "../../../stores/settings";
import { AGENT_TITLE, newPaneTab } from "../../../stores/tabLayout";
import TabBar from "../TabBar.vue";
import type { LaunchAgent, SettingsDocument, Tab, TabSessionState } from "../../../types";

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

function makeTab(agent: LaunchAgent, state: TabSessionState, id: string): Tab {
  const t = newPaneTab(id, agent, AGENT_TITLE[agent], null);
  const p = t.panes[t.activePaneId]!;
  p.sessionId = id;
  p.sessionState = state;
  t.sessionId = id;
  t.sessionState = state;
  return t;
}

vi.mock("../../../lib/ipc", () => ({
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  runtimeInspect: vi.fn(),
  stopRuntime: vi.fn(),
}));
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

function setupStore() {
  const s = useRuntimeStore();
  s.tabs = [makeTab("bash", "running", "t1"), makeTab("claude", "running", "t2")];
  s.activeTabId = "t1";
  return s;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});
afterEach(() => {
  vi.useRealTimers();
});

describe("S1.6 TabBar structure (no nested buttons)", () => {
  it("renders one role=tab activation button per tab, no nested buttons", () => {
    setupStore();
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });

    expect(wrapper.findAll("[role=tab]").length).toBe(2);
    // No interactive element may be nested inside another interactive element.
    expect(wrapper.findAll(".tab button button").length).toBe(0);
    expect(wrapper.findAll(".tab-main button").length).toBe(0);
    wrapper.unmount();
  });

  it("close/reopen are sibling buttons with accessible labels", () => {
    setupStore();
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });

    // A running tab shows a close button, and it is a sibling of tab-main.
    const firstTab = wrapper.findAll(".tab")[0]!;
    const closeBtn = firstTab.find(".actions .x");
    expect(closeBtn.exists()).toBe(true);
    expect(closeBtn.attributes("aria-label")).toBeTruthy();
    expect(firstTab.find(".tab-main").element.contains(closeBtn.element)).toBe(false);
    wrapper.unmount();
  });

  it("activating a tab via the activation button focuses and selects it", async () => {
    const s = setupStore();
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });

    await wrapper.findAll(".tab-main")[1]!.trigger("click");
    expect(s.activeTabId).toBe("t2");
    wrapper.unmount();
  });

  it("arrows move focus within the tablist WITHOUT activating; Enter activates", async () => {
    const s = setupStore();
    // attachTo: focus()/document.activeElement only work on an attached tree.
    const wrapper = mount(TabBar, {
      global: { plugins: [i18n] },
      attachTo: document.body,
    });
    const mains = wrapper.findAll(".tab-main");
    const tabbar = wrapper.find(".tabbar");

    // Focus the first tab, then ArrowRight moves focus to the second but does
    // not activate (the app-wide activeTabId watcher would move focus away).
    (mains[0]!.element as HTMLElement).focus();
    await tabbar.trigger("keydown", { key: "ArrowRight" });
    expect(document.activeElement).toBe(mains[1]!.element);
    expect(s.activeTabId).toBe("t1");

    // Enter on the focused tab activates it.
    await tabbar.trigger("keydown", { key: "Enter" });
    expect(s.activeTabId).toBe("t2");
    wrapper.unmount();
  });
});

describe("IDEA-1 + split button (S3)", () => {
  it("+ creates the configured default agent tab directly", async () => {
    const s = setupStore();
    const settings = useSettingsStore();
    settings.doc = { ...settingsDoc, ui: { ...settingsDoc.ui, default_tab_agent: "codex" } };
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });

    await wrapper.find(".menu-wrap .add").trigger("click");
    expect(s.tabs.length).toBe(3);
    expect(s.tabs[2]!.agent).toBe("codex");
    expect(s.activeTabId).toBe(s.tabs[2]!.tabId);
    // Direct create: no menu opened.
    expect(document.querySelector(".tab-new-menu")).toBeNull();
    wrapper.unmount();
  });

  it("+ falls back to bash when no settings doc is loaded", async () => {
    const s = setupStore();
    useSettingsStore().doc = null;
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });

    await wrapper.find(".menu-wrap .add").trigger("click");
    expect(s.tabs.length).toBe(3);
    expect(s.tabs[2]!.agent).toBe("bash");
    wrapper.unmount();
  });

  it("▾ menu lists 3 agents + Provider 管理; agent entry creates that tab", async () => {
    const s = setupStore();
    const wrapper = mount(TabBar, { global: { plugins: [i18n] } });
    await wrapper.find(".menu-wrap .add-caret").trigger("click");

    const menu = document.querySelector(".tab-new-menu");
    expect(menu).toBeTruthy();
    const items = menu!.querySelectorAll("[role=menuitem]");
    expect(items.length).toBe(4); // claude/codex/bash + Provider 管理（设置已升工作区层，cc-switch TUI 已移除）
    expect(menu!.querySelector("[role=separator]")).toBeTruthy();

    (items[1] as HTMLElement).click(); // codex
    await nextTick();
    expect(s.tabs.length).toBe(3);
    expect(s.tabs[2]!.agent).toBe("codex");
    expect(document.querySelector(".tab-new-menu")).toBeNull(); // closed after pick
    wrapper.unmount();
  });

});
