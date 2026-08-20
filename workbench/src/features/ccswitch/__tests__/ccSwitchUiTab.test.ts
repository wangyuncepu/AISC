/**
 * Stage 8e (CS-05/06): the cc-switch Provider UI tab.
 * Secret lifecycle is the point: the key lives in transient form state only,
 * is sent exactly once through the ipc channel, and is cleared immediately.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
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
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    expect(w.text()).toContain("****abcd");
    expect(w.text()).not.toContain("sk-");
    w.unmount();
  });

  it("simple add sends preset+key once via the channel, then clears the field", async () => {
    setup();
    vi.mocked(ipc.ccSwitchAdd).mockResolvedValue(RESULT(["deepseek"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));

    await w.find("header .primary").trigger("click"); // 添加
    const keyInput = w.find('input[type="password"]');
    (keyInput.element as HTMLInputElement).value = "sk-very-secret-1";
    await keyInput.trigger("input");
    await w.find(".form-card .primary").trigger("click"); // submit add

    await vi.waitFor(() => expect(ipc.ccSwitchAdd).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchAdd).mock.calls[0]![3];
    expect(arg.mode).toBe("simple");
    expect(arg.id).toBe("deepseek");
    expect(arg.api_key).toBe("sk-very-secret-1");
    // Transient: the form closes on success; reopening starts from an
    // EMPTY key field (the secret never lingers in the form).
    await vi.waitFor(() => expect(w.find(".form-card").exists()).toBe(false));
    await w.find("header .primary").trigger("click");
    expect(
      (w.find('input[type="password"]').element as HTMLInputElement).value,
    ).toBe("");
    w.unmount();
  });

  it("custom add sends mode=custom with full fields (KI-7① UI regression)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchAdd).mockResolvedValue(RESULT(["mine"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));

    await w.find("header .primary").trigger("click"); // 添加
    // Switch the add form to 自定义 mode.
    const modeBtn = w
      .findAll("button")
      .find((b) => b.text().includes("自定义"))!;
    await modeBtn.trigger("click");
    // Fill the custom fields (name + baseUrl required).
    const inputs = w.findAll(".form-card input");
    const setVal = async (el: typeof inputs[number], v: string) => {
      (el.element as HTMLInputElement).value = v;
      await el.trigger("input");
    };
    // Custom layout: id, name, baseUrl, model, apiKey(password).
    await setVal(inputs[0]!, "mine");
    await setVal(inputs[1]!, "My Provider");
    await setVal(inputs[2]!, "https://example.com/api");
    await setVal(inputs[3]!, "my-model");
    const key = w.find('input[type="password"]');
    await setVal(key, "sk-custom-secret-9");
    await w.find(".form-card .primary").trigger("click");

    await vi.waitFor(() => expect(ipc.ccSwitchAdd).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchAdd).mock.calls[0]![3];
    expect(arg.mode).toBe("custom"); // the KI-7① regression
    expect(arg.provider).toBeUndefined();
    expect(arg.id).toBe("mine");
    expect(arg.name).toBe("My Provider");
    expect(arg.base_url).toBe("https://example.com/api");
    expect(arg.model).toBe("my-model");
    expect(arg.api_key).toBe("sk-custom-secret-9");
    await vi.waitFor(() => expect(w.find(".form-card").exists()).toBe(false));
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

  it("clicking a non-current row activates it and shows feedback", async () => {
    setup();
    vi.mocked(ipc.ccSwitchSwitch).mockResolvedValue(RESULT(["deepseek", "zhipu"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    // Row 1 (zhipu) is not current — clicking it activates.
    await w.findAll(".row")[1]!.trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchSwitch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(ipc.ccSwitchSwitch).mock.calls[0]![3]).toBe("zhipu");
    await vi.waitFor(() =>
      expect(document.querySelector(".switch-toast")?.textContent ?? "")
        .toContain("已切换到"));
    w.unmount();
  });

  it("rows without a base_url are hidden (direct-official placeholders)", async () => {
    setup();
    const bare = RESULT(["deepseek", "zhipu"]);
    bare.providers[1]!.base_url = "";
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(bare);
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    // Only the activatable + current rows render; the bare row is gone.
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(1));
    expect(w.find(".hidden-note").exists()).toBe(true);
    w.unmount();
  });

  it("clicking the current row offers cancel-proxy → official direct", async () => {
    setup();
    vi.mocked(ipc.ccSwitchSwitch).mockResolvedValue(RESULT(["zhipu"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".row")[0]!.trigger("click");
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
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".row")[0]!.trigger("click");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(ipc.ccSwitchSwitch).not.toHaveBeenCalled();
    w.unmount();
  });

  it("delete asks for confirmation and posts the op", async () => {
    setup();
    const { confirm } = await import("@tauri-apps/plugin-dialog");
    vi.mocked(ipc.ccSwitchDelete).mockResolvedValue(RESULT(["zhipu"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".row")[0]!.find(".danger").trigger("click");
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
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(1));
    await w.findAll(".agent-toggle button")[1]!.trigger("click");
    await vi.waitFor(() => expect(w.find(".banner.err").exists()).toBe(true));
    await w.findAll(".agent-toggle button")[0]!.trigger("click");
    // Switching back refetches (default mock: 2 rows) and clears the error.
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
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

  it("claude edit writes all five role slots explicitly (empty deletes)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchEdit).mockResolvedValue(resultWithRoles());
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(1));
    await w.findAll(".row")[0]!.findAll("button")[0]!.trigger("click"); // 编辑

    // Five slot inputs (list=datalist) prefilled from role_env.
    const slots = w.findAll(".form-card input[list]");
    expect(slots.length).toBe(5);
    expect((slots[3]!.element as HTMLInputElement).value).toBe("deepseek-v4-flash");
    // Change HAIKU; clear SUBAGENT (→ null delete); leave the rest.
    const setVal = async (el: typeof slots[number], v: string) => {
      (el.element as HTMLInputElement).value = v;
      await el.trigger("input");
    };
    await setVal(slots[3]!, "deepseek-v4-flash[1m]");
    await setVal(slots[4]!, "");
    // [1m] declaration (round 4): the three applicable slots carry a
    // checkbox; MODEL is prefilled WITH [1m] → checked; toggling strips it.
    const oneMBoxes = w.findAll("input.one-m");
    expect(oneMBoxes.length).toBe(3); // MODEL/OPUS/SONNET only
    // Fixture prefills all three applicable slots WITH [1m] → all checked.
    expect((oneMBoxes[0]!.element as HTMLInputElement).checked).toBe(true);
    expect((oneMBoxes[1]!.element as HTMLInputElement).checked).toBe(true);
    expect((oneMBoxes[2]!.element as HTMLInputElement).checked).toBe(true);
    await oneMBoxes[0]!.trigger("change"); // strip from MODEL
    expect((slots[0]!.element as HTMLInputElement).value).toBe("deepseek-v4-pro");
    await oneMBoxes[0]!.trigger("change"); // re-append
    expect((slots[0]!.element as HTMLInputElement).value).toBe("deepseek-v4-pro[1m]");
    await w.find(".form-card .primary").trigger("click");

    await vi.waitFor(() => expect(ipc.ccSwitchEdit).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchEdit).mock.calls[0]![4]; // 5 params: ws, rt, agent, providerId, request
    expect(arg.patch?.env).toEqual({
      ANTHROPIC_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_OPUS_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_SONNET_MODEL: "deepseek-v4-pro[1m]",
      ANTHROPIC_DEFAULT_HAIKU_MODEL: "deepseek-v4-flash[1m]",
      CLAUDE_CODE_SUBAGENT_MODEL: null, // empty slot = delete the key
    });
    // Claude's model rides the env block, not the single model field.
    expect(arg.patch?.model).toBeUndefined();
    w.unmount();
  });

  it("codex edit keeps the single model field (no mapping UI)", async () => {
    setup();
    vi.mocked(ipc.ccSwitchEdit).mockResolvedValue(RESULT(["deepseek"]));
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".agent-toggle button")[1]!.trigger("click"); // codex
    await vi.waitFor(() => expect(ipc.ccSwitchProviders).toHaveBeenCalledTimes(2));
    await w.findAll(".row")[0]!.findAll("button")[0]!.trigger("click");
    expect(w.find("input[list]").exists()).toBe(false); // no role slots
    await w.find(".form-card .primary").trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchEdit).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(ipc.ccSwitchEdit).mock.calls[0]![4]; // 5 params: ws, rt, agent, providerId, request
    expect(arg.patch?.env).toBeUndefined();
    expect(arg.patch?.model).toBe("m"); // fixture model
    w.unmount();
  });

  it("the dropdown merges fetched ∪ known ∪ current slot values", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchFetchModels).mockResolvedValue({
      available: true, models: ["remote-model-x"], message: "",
    });
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(1));
    await w.findAll(".row")[0]!.findAll("button")[0]!.trigger("click");

    // Tier 2+3 before fetching: known ∪ current (current values ⊂ known here
    // except none — deepseek preset covers them; assert the known list).
    const optionsBefore = w.findAll("#cc-model-options option").map((o) => o.attributes("value"));
    expect(optionsBefore).toContain("deepseek-chat");
    expect(optionsBefore).toContain("deepseek-v4-flash");

    // Tier 1: the fetch button merges the remote list in.
    await w.findAll("button").find((b) => b.text().includes("拉取模型列表"))!.trigger("click");
    await vi.waitFor(() => expect(ipc.ccSwitchFetchModels).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => {
      const options = w.findAll("#cc-model-options option").map((o) => o.attributes("value"));
      expect(options).toContain("remote-model-x");
      expect(options).toContain("deepseek-chat");
    });
    w.unmount();
  });

  it("an unavailable fetch shows the hint, never an error banner", async () => {
    setup();
    vi.mocked(ipc.ccSwitchProviders).mockResolvedValue(resultWithRoles());
    vi.mocked(ipc.ccSwitchFetchModels).mockResolvedValue({
      available: false, models: [], message: "HTTP 401 Unauthorized",
    });
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(1));
    await w.findAll(".row")[0]!.findAll("button")[0]!.trigger("click");
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
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".row")[1]!.trigger("click"); // activate deepseek→target id
    await vi.waitFor(() => expect(ipc.ccSwitchSwitch).toHaveBeenCalledTimes(1));
    // flashId targets the row id ("deepseek"), present until the 1.3s timer.
    await vi.waitFor(() =>
      expect(w.findAll(".row").some((r) => r.classes().includes("flash"))).toBe(true));
    w.unmount();
  });
});
