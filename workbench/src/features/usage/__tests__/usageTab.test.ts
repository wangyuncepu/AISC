/**
 * IDEA-2 (2d): the「网络与用量」panel — renders the subscription section
 * from the usage store's data and the provider table from the overview
 * envelope; the not-configured state shows the shared import form.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useUsageStore } from "../../../stores/usage";
import type { SubscriptionStatus, UsageOverview } from "../../../types";
import NetworkUsageTab from "../NetworkUsageTab.vue";

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  networkSubscriptionShow: vi.fn(),
  networkSubscriptionImport: vi.fn(),
  networkSubscriptionImportFile: vi.fn(),
  networkSubscriptionRefresh: vi.fn(),
  networkSubscriptionClear: vi.fn(),
  usageOverview: vi.fn(),
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

const SUB_CONFIGURED: SubscriptionStatus = {
  configured: true,
  source: "download",
  url_masked: "https://sub.example/api?****",
  fetched_at: "2026-08-19T14:43:19+08:00",
  config_sha256: "sha256:x",
  has_config_file: true,
  userinfo: { upload: 100, download: 400, total: 1000, expire: 1800000000 },
};

function overview(sub: SubscriptionStatus, withRows = true): UsageOverview {
  const rows = withRows
    ? [{ app: "claude", provider_id: "deepseek", provider_name: "DeepSeek",
        requests: 4, success: 4, failed: 0, tokens_total: 105600,
        cost_estimate: 0.0318, currency: "USD" }]
    : [];
  return {
    subscription: sub,
    range: "7d",
    since: 0,
    workspaces: [
      {
        workspace_hash: "sha256-v1-aaa",
        workspace_path: "C:\\proj\\ttt",
        running: withRows,
        container: withRows ? "ct" : "",
        source: withRows ? "live" : "none",
        fetched_at: withRows ? "2026-08-19T15:00:00+08:00" : null,
        available: true,
        providers: rows,
        models: [],
      },
    ],
    totals: {
      providers: rows,
      requests: withRows ? 4 : 0,
      tokens_total: withRows ? 105600 : 0,
      cost_estimate: withRows ? 0.0318 : 0,
    },
  };
}

describe("NetworkUsageTab (IDEA-2 2d)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("renders the configured subscription (masked URL + usage bar) and provider rows", async () => {
    mockIpc.usageOverview.mockResolvedValue(overview(SUB_CONFIGURED));
    const usage = useUsageStore();
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();

    expect(usage.subscription?.configured).toBe(true);
    expect(tab.text()).toContain("https://sub.example/api?****");
    // usage line: (100+400)/1000 bytes with remaining
    expect(tab.text()).toContain("500 B");
    expect(tab.text()).toContain("DeepSeek");
    expect(tab.text()).toContain("105.6k");
    expect(tab.find(".sub-form").exists()).toBe(false); // no import form
    tab.unmount();
  });

  it("not configured → shows the shared import form, no provider rows", async () => {
    const subNone: SubscriptionStatus = {
      configured: false, source: null, url_masked: null, fetched_at: null,
      config_sha256: null, has_config_file: false, userinfo: null,
    };
    mockIpc.usageOverview.mockResolvedValue(overview(subNone, false));
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();

    expect(tab.find(".sub-form").exists()).toBe(true);
    expect(tab.text()).not.toContain("DeepSeek");
    expect(tab.text()).toContain("暂无用量数据");
    tab.unmount();
  });

  it("manual source (no userinfo) degrades to the no-usage note", async () => {
    const subManual: SubscriptionStatus = {
      ...SUB_CONFIGURED, source: "manual", url_masked: null, userinfo: null,
    };
    mockIpc.usageOverview.mockResolvedValue(overview(subManual));
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();
    expect(tab.text()).toContain("订阅未提供用量信息");
    tab.unmount();
  });

  it("selecting a workspace keeps the full dropdown (server never filters, 2d round 3)", async () => {
    mockIpc.usageOverview.mockResolvedValue(overview(SUB_CONFIGURED));
    const usage = useUsageStore();
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();

    // Two workspaces in the dropdown: 全部 + ttt (fixture has one ws).
    usage.scope = "C:\\proj\\ttt";
    await usage.fetchOverview();
    await flushPromises();

    // The fetch must stay unfiltered — a server-side --workspace would
    // shrink the selector to the selected entry only.
    expect(mockIpc.usageOverview).toHaveBeenLastCalledWith("7d");
    const options = tab.findAll("select")[1]!.findAll("option");
    expect(options.some((o) => o.text().includes("全部工作区"))).toBe(true);
    expect(options.some((o) => o.text().includes("ttt"))).toBe(true);
    tab.unmount();
  });

  it("a successful import switches the panel back to the status view (2d round 2)", async () => {
    const subNone: SubscriptionStatus = {
      configured: false, source: null, url_masked: null, fetched_at: null,
      config_sha256: null, has_config_file: false, userinfo: null,
    };
    mockIpc.usageOverview.mockResolvedValue(overview(subNone, false));
    mockIpc.networkSubscriptionImport.mockResolvedValue(SUB_CONFIGURED);
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();
    expect(tab.find(".sub-form").exists()).toBe(true);

    await tab.find('input[type="url"]').setValue("https://sub.example/api?token=T");
    await tab.find('form').trigger("submit");
    await flushPromises();

    // The form is gone; the freshly imported status (masked URL) is shown.
    // (The form's own ✓ line matters where the form stays mounted — the
    // wizard's inline copy; the panel's feedback IS the status view switch.)
    expect(tab.find(".sub-form").exists()).toBe(false);
    expect(tab.text()).toContain("https://sub.example/api?****");
    tab.unmount();
  });

  it("更换 over an existing subscription flips back too (挂账① 手测: subConfigured stays true→true)", async () => {
    mockIpc.usageOverview.mockResolvedValue(overview(SUB_CONFIGURED));
    mockIpc.networkSubscriptionImport.mockResolvedValue({
      ...SUB_CONFIGURED,
      fetched_at: "2026-08-19T16:00:00+08:00",
      url_masked: "http://sub2.example/api?****",
    });
    const tab = mount(NetworkUsageTab, { global: { plugins: [i18n] } });
    await flushPromises();
    expect(tab.find(".sub-form").exists()).toBe(false); // status view

    // 更换 → the form appears while the old subscription stays configured.
    const replace = tab.findAll("button").find((b) => b.text().includes("更换"));
    expect(replace).toBeDefined();
    await replace!.trigger("click");
    expect(tab.find(".sub-form").exists()).toBe(true);

    await tab.find('input[type="url"]').setValue("http://sub2.example/api?token=T2");
    await tab.find("form").trigger("submit");
    await flushPromises();

    // subConfigured never changed (true→true) — the flip-back must key on
    // the fresh snapshot (fetched_at), not the boolean alone.
    expect(tab.find(".sub-form").exists()).toBe(false);
    expect(tab.text()).toContain("http://sub2.example/api?****");
    tab.unmount();
  });
});
