/**
 * Stage 1 (S1.6, F-A06): TabBar structure / a11y.
 *
 * Regression for the invalid nested-`<button>` structure: the tab wrapper is a
 * non-interactive element, the activation button is the only `role=tab`, and
 * close/reopen are sibling buttons with accessible labels.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import { AGENT_TITLE, newPaneTab } from "../../../stores/tabLayout";
import TabBar from "../TabBar.vue";
import type { LaunchAgent, Tab, TabSessionState } from "../../../types";

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
});
