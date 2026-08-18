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
  ccSwitchProviders: vi.fn(),
  ccSwitchAdd: vi.fn(),
  ccSwitchEdit: vi.fn(),
  ccSwitchSwitch: vi.fn(),
  ccSwitchDelete: vi.fn(),
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
      expect(w.find(".banner.ok").text()).toContain("已切换到"));
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

  it("clicking the current row is a no-op", async () => {
    setup();
    const w = mount(CcSwitchUiTab, { global: { plugins: [i18n] } });
    await vi.waitFor(() => expect(w.findAll(".row").length).toBe(2));
    await w.findAll(".row")[0]!.trigger("click");
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
});
