/**
 * G-05/G-12 sidebar tests (Step 8; 04-observability.md §六):
 * - A-G05-1: no 1s ticker - a 12s idle window produces ZERO DOM mutations in
 *   the user-layer sections (only network requests would occur in the app).
 * - A-G05-2: running -> stopped updates within one poll cycle; stale shows
 *   the last-known marker instead of deterministic green.
 * - A-G05-3: the developer-details field list covers the documented minimum
 *   (IDs/container/owner/fingerprint/freshness/observed/image/network/scope/
 *   provider/route/auth) with copyable IDs.
 * - A-G12: auth labels never present unconfigured for unknown capability;
 *   the guide action renders for not_configured/login_required only.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import RuntimeSidebar from "../RuntimeSidebar.vue";
import type { RuntimeSnapshot } from "../../../types";

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

const SNAP: RuntimeSnapshot = {
  runtime_id: "11111111-1111-4111-8111-111111111111",
  state: "running",
  config: { workspace: "/ws", image: "super-claude:latest", network: "direct", scope: "project" },
  owner: "workbench",
  config_fingerprint: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  container_name: "aisc-wb-test",
  container_id: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  registry_state: "registered",
  observed_at: new Date(Date.now() - 5000).toISOString(),
  stale: false,
};

function setupStore() {
  const s = useRuntimeStore();
  s.runtimeState = "running";
  s.freshness = "fresh";
  s.runtimeSnapshot = JSON.parse(JSON.stringify(SNAP));
  s.workspace = "/ws";
  s.runtimeId = SNAP.runtime_id;
  s.tabs = [
    { tabId: "t1", agent: "bash", title: "Bash", sessionId: "s1", sessionState: "running", exit: null, savedTabId: null },
  ];
  s.activeTabId = "t1";
  s.capability = { provider_status: true } as never;
  s.providerStatuses = {
    claude: {
      runtime_id: SNAP.runtime_id,
      agent: "claude",
      provider_id: "pid-1",
      provider_name: "OpenAI Official",
      route_mode: "official-direct",
      auth_status: "configured",
      observed_at: new Date().toISOString(),
    },
    codex: null,
  };
  return s;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("A-G05-1 no 1s ticker", () => {
  it("12s idle window produces zero DOM mutations in the user layer", async () => {
    const s = setupStore();
    const wrapper = mount(RuntimeSidebar, { global: { plugins: [i18n] } });
    const sidebarEl = wrapper.find("aside").element;
    let mutations = 0;
    const mo = new MutationObserver((list) => {
      // Ignore the details-section subtree (collapsed, untouched anyway).
      mutations += list.filter(
        (m) => !(m.target as HTMLElement).closest?.("details") && m.type !== "attributes"
      ).length;
    });
    mo.observe(sidebarEl, { childList: true, subtree: true, characterData: true });
    // Let the initial render settle, then 12s of idle polling-free time.
    await vi.advanceTimersByTimeAsync(12000);
    expect(mutations).toBe(0);
    expect(wrapper.find(".sidebar").exists()).toBe(true);
    mo.disconnect();
    void s;
    wrapper.unmount();
  });
});

describe("A-G05-2 state changes", () => {
  it("running -> stopped updates the label within one cycle", async () => {
    const s = setupStore();
    const wrapper = mount(RuntimeSidebar, { global: { plugins: [i18n] } });
    expect(wrapper.find(".state").text()).toBe("运行中");
    s.runtimeState = "stopped";
    s.runtimeSnapshot = { ...SNAP, state: "stopped" } as RuntimeSnapshot;
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".state").text()).toBe("已停止");
    wrapper.unmount();
  });

  it("stale shows the last-known marker, not deterministic green", async () => {
    const s = setupStore();
    const wrapper = mount(RuntimeSidebar, { global: { plugins: [i18n] } });
    s.freshness = "stale";
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".state").attributes("data-fresh")).toBe("stale");
    expect(wrapper.find(".last-known").text()).toContain("上次已知");
    expect(wrapper.find(".state").classes()).not.toContain("state-running");
    wrapper.unmount();
  });
});

describe("A-G05-3 developer details completeness", () => {
  it("covers the documented field list and copyable IDs", async () => {
    const s = setupStore();
    s.tabs = [
      { tabId: "t1", agent: "bash", title: "Bash", sessionId: "s1", sessionState: "running", exit: null, savedTabId: null },
      { tabId: "t2", agent: "claude", title: "Claude", sessionId: "s2", sessionState: "running", exit: null, savedTabId: null },
    ];
    s.activeTabId = "t2"; // provider fields appear only for claude/codex
    const wrapper = mount(RuntimeSidebar, { global: { plugins: [i18n] } });
    const details = wrapper.find("details");
    expect(details.exists()).toBe(true);
    await details.find("summary").trigger("click"); // expand (native toggle)
    const text = wrapper.find(".dev").text();
    for (const field of [
      "runtime_id",
      "container_name",
      "container_id",
      "owner",
      "config_fingerprint",
      "registry_state",
      "freshness",
      "stale",
      "observed",
      "image",
      "network",
      "scope",
      "workspace",
      "provider_id",
      "provider_name",
      "route",
      "auth",
    ]) {
      expect(text, `missing detail field ${field}`).toContain(field);
    }
    const copyables = wrapper.findAll(".dev .copyable");
    expect(copyables.length).toBeGreaterThanOrEqual(5); // id/container/fp/workspace/provider
    wrapper.unmount();
  });
});

describe("A-G12 auth labels and actions", () => {
  it("shows the cc-switch action for not_configured, never for configured", async () => {
    const s = setupStore();
    s.activeTabId = "t2";
    s.tabs.push({ tabId: "t2", agent: "claude", title: "Claude", sessionId: null, sessionState: "guide", exit: null, savedTabId: null });
    const wrapper = mount(RuntimeSidebar, { global: { plugins: [i18n] } });
    expect(wrapper.find(".auth").text()).toBe("已配置");
    expect(wrapper.find(".auth-row .link").exists()).toBe(false);

    s.providerStatuses.claude!.auth_status = "not_configured";
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".auth").text()).toBe("未配置");
    expect(wrapper.find(".auth-row .link").exists()).toBe(true);

    s.providerStatuses.claude!.auth_status = "login_required";
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".auth").text()).toBe("需要登录");
    expect(wrapper.find(".auth-row .link").exists()).toBe(true);
    wrapper.unmount();
  });
});
