/**
 * Stage 8e (CS-05/06): the cc-switch Provider UI tab.
 * Secret lifecycle is the point: the key lives in transient form state only,
 * is sent exactly once through the ipc channel, and is cleared immediately.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import * as ipc from "../../../lib/ipc";
import CcSwitchUiTab from "../CcSwitchUiTab.vue";
import type { CcSwitchProvidersResult } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  ccSwitchProviders: vi.fn(),
  ccSwitchAdd: vi.fn(),
  ccSwitchEdit: vi.fn(),
  ccSwitchSwitch: vi.fn(),
  ccSwitchDelete: vi.fn(),
  ccSwitchFetchModels: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn().mockResolvedValue(true),
}));

const RESULT = (ids: string[]): CcSwitchProvidersResult => ({
  agent: "claude",
  operation_id: "op-1",
  providers: ids.map((id, i) => ({
    id, name: id, app_type: "claude",
    base_url: `https://${id}.example`, model: "m",
    has_api_key: i === 0, api_key_mask: i === 0 ? "****abcd" : "",
    is_current: i === 0,
  })),
});

function setup() {
  const s = useRuntimeStore();
  s.status = "ready";
  s.workspace = "C:\\ws";
  s.runtimeId = "11111111-2222-4333-8444-555555555555";
  return s;
}

/** PP r3: an official-direct placeholder row (no base_url) as cc-switch
 * keeps one per agent. */
function resultWithOfficial(): CcSwitchProvidersResult {
  const r = RESULT(["deepseek", "zhipu"]);
  r.providers.push({
    id: "default", name: "default", app_type: "claude",
    base_url: "", model: "", has_api_key: false, api_key_mask: "",
    is_current: false,
  });
  return r;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  vi.clearAllMocks();
  vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(RESULT(["deepseek", "zhipu"]));
});

describe("CcSwitchUiTab (Stage 8e)", () => {
  it("loads the secret-free snapshot on mount (mask, current marker)", async () => {
    setup();
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    // PP (D-12): cards show icon/name/endpoint/badge (no key mask — the
    // desktop parity shape); the secret-free invariant stays: no raw key.
    expect(w.text()).not.toContain("sk-");
    w.unmount();
  });

  it("simple add sends preset+key once via the channel (PP edit page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchAdd).mockResolvedValue(RESULT(["deepseek"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));

    await w.find("header .primary").trigger("click"); // 添加 → edit page
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(true));
    const key = w.find(".edit-page input[type='password']");
    (key.element as HTMLInputElement).value = "sk-very-secret-1";
    await key.trigger("input");
    await w.find(".edit-page .head .primary").trigger("click"); // save

    await vi.waitFor(() => expect(ipc.ccSwitchAdd).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchAdd).mock.calls[0]![3];
    expect(arg.mode).toBe("simple");
    expect(arg.id).toBe("deepseek");
    expect(arg.api_key).toBe("sk-very-secret-1");
    // Success closes the page back to the list.
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(false));
    w.unmount();
  });

  it("custom add sends mode=custom with full fields (KI-7①, PP page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchAdd).mockResolvedValue(RESULT(["mine"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));

    await w.find("header .primary").trigger("click");
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(true));
    // Switch the add mode to 自定义.
    await w.findAll("button").find((b) => b.text().includes("自定义"))!.trigger("click");
    const inputs = w.findAll(".edit-page input:not([type='password'])");
    const setVal = async (el: typeof inputs[number], v: string) => {
      (el.element as HTMLInputElement).value = v;
      await el.trigger("input");
    };
    // Custom layout: id, name, baseUrl (claude has no single model field).
    await setVal(inputs[0]!, "mine");
    await setVal(inputs[1]!, "My Provider");
    await setVal(inputs[2]!, "https://example.com/api");
    const key = w.find(".edit-page input[type='password']");
    await setVal(key, "sk-custom-secret-9");
    await w.find(".edit-page .head .primary").trigger("click");

    await vi.waitFor(() => expect(ipc.ccSwitchAdd).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchAdd).mock.calls[0]![3];
    expect(arg.mode).toBe("custom");
    expect(arg.id).toBe("mine");
    expect(arg.name).toBe("My Provider");
    expect(arg.base_url).toBe("https://example.com/api");
    expect(arg.api_key).toBe("sk-custom-secret-9");
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(false));
    w.unmount();
  });

  it("becoming visible again refetches the list (KI-7②)", async () => {
    setup();
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] }, props: { visible: false } });
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(1));
    // Hidden → visible (user returns from a bash tab where they edited the
    // cc-switch TUI): the kept-alive pane refetches instead of showing stale
    // rows.
    await w.setProps({ visible: true });
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(2));
    w.unmount();
  });

  it("agent toggle refetches with the other agent", async () => {
    setup();
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(1));
    await w.findAll(".agent-toggle button")[1]!.trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(2));
    expect(vi.mocked(ipc.ccSwitchProviders).mock.calls[1]![2]).toBe("codex");
    w.unmount();
  });

  it("switching agents drops the stale badge list immediately (PP r5)", async () => {
    setup();
    // Hold the codex fetch pending: during the window the OLD agent's cards
    // (使用中 badge on claude rows) must be GONE — the loading branch covers
    // the gap instead of the old agent's list lingering in the new view.
    let release!: (v: CcSwitchProvidersResult) => void;
    const gate = new Promise<CcSwitchProvidersResult>((r) => (release = r));
    vi.mocked(ipc.ccSwitchProviders)
      .mockResolvedValueOnce(RESULT(["deepseek"]))          // mount (claude)
      .mockImplementationOnce(() => gate);                   // codex, pending
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    await w.findAll(".agent-toggle button")[1]!.trigger("click");
    await nextTick();
    expect(w.findAll(".card").length).toBe(0);          // no stale claude cards
    expect(w.find(".badge").exists()).toBe(false);      // no lingering 使用中
    expect(w.text()).toContain("加载中");
    release(RESULT(["deepseek"]));
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    w.unmount();
  });

  it("the 启用 button on a non-current row activates it (PP r2)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchSwitch).mockResolvedValue(RESULT(["deepseek", "zhipu"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    // Row 1 (zhipu) is not current — its dedicated 启用 button activates.
    await w.findAll(".card")[1]!.find("button.start").trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchSwitch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(ipc.ccSwitchSwitch).mock.calls[0]![3]).toBe("zhipu");
    await vi.waitFor(() =>
      expect(document.querySelector(".switch-toast")?.textContent ?? "")
        .toContain("已切换到"));
    w.unmount();
  });

  it("official entries stay visible and pin first (PP r3)", async () => {
    setup();
    const bare = RESULT(["deepseek", "zhipu"]);
    bare.providers[1]!.base_url = "";
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(bare);
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    // The bare row renders as the pinned official card (cc-switch parity).
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    const first = w.findAll(".card")[0]!;
    expect(first.text()).toContain("官方直连");
    expect(first.text()).toContain("直连官方端点");
    expect(first.find("button.start").exists()).toBe(true);
    expect(first.find("button.edit").exists()).toBe(false);
    expect(w.find(".hidden-note").exists()).toBe(true);
    w.unmount();
  });

  it("the official card's 启用 offers cancel-proxy → official direct (PP r3)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithOfficial());
    vi.mocked(ipc.ccSwitchSwitch).mockResolvedValue(resultWithOfficial());
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(3));
    // Card 0 is the pinned official-direct entry.
    await w.findAll(".card")[0]!.find("button.start").trigger("click");
    const { confirm } = await import("@tauri-apps/plugin-dialog");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(ipc.ccSwitchSwitch).toHaveBeenCalledTimes(1));
    // Pseudo target flows to the adapter, not a row id.
    expect(vi.mocked(ipc.ccSwitchSwitch).mock.calls[0]![3]).toBe("official");
    await vi.waitFor(() =>
      expect(document.querySelector(".switch-toast")?.textContent ?? "")
        .toContain("官方直连"));
    w.unmount();
  });

  it("declining the cancel confirm sends nothing", async () => {
    setup();
    const { confirm } = await import("@tauri-apps/plugin-dialog");
    vi.mocked(confirm).mockResolvedValueOnce(false);
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithOfficial());
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(3));
    await w.findAll(".card")[0]!.find("button.start").trigger("click");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(ipc.ccSwitchSwitch).not.toHaveBeenCalled();
    w.unmount();
  });

  it("list order is pinned to first-seen (the edit dance never reshuffles)", async () => {
    setup();
    const w = mount(CcSwitchUiTab, {
      global: { plugins: [i18n] }, props: { visible: false },
    });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    // A later snapshot arrives reversed (what a server-side delete→re-add
    // used to do to the order) — the display keeps first-seen order.
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(RESULT(["zhipu", "deepseek"]));
    await w.setProps({ visible: true });
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(2));
    const names = w.findAll(".card .name").map((n) => n.text());
    expect(names[0]!.startsWith("deepseek")).toBe(true);
    expect(names[1]!.startsWith("zhipu")).toBe(true);
    w.unmount();
  });

  it("delete asks for confirmation and posts the op", async () => {
    setup();
    const { confirm } = await import("@tauri-apps/plugin-dialog");
    vi.mocked(ipc.ccSwitchDelete).mockResolvedValue(RESULT(["zhipu"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    await w.findAll(".card")[0]!.find(".danger").trigger("click");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(ipc.ccSwitchDelete).toHaveBeenCalledTimes(1));
    expect(vi.mocked(ipc.ccSwitchDelete).mock.calls[0]![3]).toBe("deepseek");
    w.unmount();
  });

  it("surfaces adapter errors without losing the list", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders)
      .mockResolvedValueOnce(RESULT(["deepseek"]))
      .mockRejectedValueOnce(new Error("AISC_ERR_CC_SWITCH_PROVIDER_NO_SWITCH_TARGET"));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    await w.findAll(".agent-toggle button")[1]!.trigger("click");
    await vi.waitFor(() => expect(w.find(".banner.err").exists()).toBe(true));
    await w.findAll(".agent-toggle button")[0]!.trigger("click");
    // Switching back refetches (default mock: 2 rows) and clears the error.
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    await vi.waitFor(() => expect(w.find(".banner.err").exists()).toBe(false));
    w.unmount();
  });

  // --- IDEA-5 (5d): mapping slots + dropdown tiers + switch feedback ---

  function resultWithRoles(): CcSwitchProvidersResult {
    const r = RESULT(["deepseek"]);
    r.providers[0] = {
      ...r.providers[0]!,
      role_env: {
        ANTHROPIC_MODEL: "deepseek-v4-pro[1m]",
        ANTHROPIC_DEFAULT_OPUS_MODEL: "deepseek-v4-pro[1m]",
        ANTHROPIC_DEFAULT_SONNET_MODEL: "deepseek-v4-pro[1m]",
        ANTHROPIC_DEFAULT_HAIKU_MODEL: "deepseek-v4-flash",
        CLAUDE_CODE_SUBAGENT_MODEL: "deepseek-v4-flash",
      },
      known_models: ["deepseek-chat", "deepseek-v4-pro", "deepseek-v4-pro[1m]",
                     "deepseek-v4-flash"],
    };
    return r;
  }

  it("claude edit writes all five role slots explicitly (PP page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchEdit).mockResolvedValue(resultWithRoles());
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    await w.findAll(".card")[0]!.find("button.edit").trigger("click"); // 编辑
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(true));

    // Advanced tier to reach the mapping editor.
    await w.findAll(".tiers button").find((b) => b.text().includes("高级模式"))!.trigger("click");
    // Three main role rows; expand the advanced pair.
    await vi.waitFor(() => expect(w.findAll(".mapping input[list]").length).toBe(3));
    await w.findAll(".mapping .link")[0]!.trigger("click"); // 展开高级槽位
    const slots = w.findAll(".mapping input[list]");
    expect(slots.length).toBe(5);
    // Fixture order after expansion: main trio (sonnet/opus/haiku) then
    // MODEL + SUBAGENT in the advanced block.
    const setVal = async (el: typeof slots[number], v: string) => {
      (el.element as HTMLInputElement).value = v;
      await el.trigger("input");
    };
    // HAIKU is main row 3 (index 2); MODEL is advanced (index 3); SUBAGENT last.
    await setVal(slots[2]!, "deepseek-v4-flash[1m]");
    await setVal(slots[4]!, ""); // SUBAGENT → null delete
    // [1m] toggles exist on MODEL/OPUS/SONNET only.
    const oneMBtns = w.findAll("button.one-m");
    expect(oneMBtns.length).toBe(3); // opus + sonnet (main) + model (expanded)
    expect(oneMBtns[0]!.classes()).toContain("on"); // fixture prefilled [1m]
    await oneMBtns[0]!.trigger("click"); // strip from OPUS row
    const opusVal = (w.findAll(".mapping input[list]")[0]!.element as HTMLInputElement).value;
    expect(opusVal.endsWith("[1m]")).toBe(false);
    await oneMBtns[0]!.trigger("click"); // re-append
    await w.find(".edit-page .head .primary").trigger("click");

    await vi.waitFor(() => expect(ipc.ccSwitchEdit).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchEdit).mock.calls[0]![4];
    expect(arg.patch?.env).toEqual({
      ANTHROPIC_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_OPUS_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_SONNET_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_HAIKU_MODEL: "deepseek-v4-flash[1m]",
      CLAUDE_CODE_SUBAGENT_MODEL: null,
    });
    expect(arg.patch?.model).toBeUndefined();
    w.unmount();
  });

  it("codex edit keeps the single model field (PP page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchEdit).mockResolvedValue(RESULT(["deepseek"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    await w.findAll(".agent-toggle button")[1]!.trigger("click"); // codex
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(2));
    await w.findAll(".card")[0]!.find("button.edit").trigger("click");
    await vi.waitFor(() => expect(w.find(".edit-page").exists()).toBe(true));
    expect(w.find(".mapping input[list]").exists()).toBe(false); // no role rows on simple tier
    await w.find(".edit-page .head .primary").trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchEdit).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchEdit).mock.calls[0]![4];
    expect(arg.patch?.env).toBeUndefined();
    expect(arg.patch?.model).toBe("m"); // fixture model
    w.unmount();
  });

  it("the mapping dropdown merges fetched ∪ known (PP page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchFetchModels).mockResolvedValue({
      available: true, models: ["remote-model-x"], message: "",
    });
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    await w.findAll(".card")[0]!.find("button.edit").trigger("click");
    await w.findAll(".tiers button").find((b) => b.text().includes("高级模式"))!.trigger("click");
    await vi.waitFor(() => expect(w.findAll(".mapping input[list]").length).toBe(3));

    const opts = () =>
      w.findAll("#pp-map-candidates option").map((o) => o.attributes("value"));
    expect(opts()).toContain("deepseek-chat");
    expect(opts()).toContain("deepseek-v4-flash");

    await w.findAll("button").find((b) => b.text().includes("拉取模型列表"))!.trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchFetchModels).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => {
      expect(opts()).toContain("remote-model-x");
      expect(opts()).toContain("deepseek-chat");
    });
    w.unmount();
  });

  it("an unavailable fetch shows the hint, never an error banner (PP page)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchFetchModels).mockResolvedValue({
      available: false, models: [], message: "HTTP 401 Unauthorized",
    });
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(1));
    await w.findAll(".card")[0]!.find("button.edit").trigger("click");
    await w.findAll(".tiers button").find((b) => b.text().includes("高级模式"))!.trigger("click");
    await w.findAll("button").find((b) => b.text().includes("拉取模型列表"))!.trigger("click");
    await vi.waitFor(() => expect(w.find(".hint.warn").exists()).toBe(true));
    expect(w.find(".hint.warn").text()).toContain("401");
    expect(w.find(".banner.err").exists()).toBe(false);
    w.unmount();
  });

  it("the newly-current row flashes after a switch", async () => {
    setup();
    const switched = RESULT(["zhipu", "deepseek"]); // zhipu now current
    vi.mocked(ipc.ccSwitchSwitch).mockResolvedValue(switched);
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".card").length).toBe(2));
    await w.findAll(".card")[1]!.find("button.start").trigger("click"); // activate deepseek→target id
    await vi.waitFor(() => expect(ipc.ccSwitchSwitch).toHaveBeenCalledTimes(1));
    // flashId targets the row id ("deepseek"), present until the 1.3s timer.
    await vi.waitFor(() =>
      expect(w.findAll(".card").some((r) => r.classes().includes("flash"))).toBe(true));
    w.unmount();
  });
});
