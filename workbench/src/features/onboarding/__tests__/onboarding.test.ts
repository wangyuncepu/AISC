/**
 * Stage 5 (ONB-01/07): onboarding wizard route shell.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { onboardingLoad, onboardingUpdate } from "../../../lib/ipc";
import OnboardingWizard from "../OnboardingWizard.vue";

vi.mock("../../../lib/ipc", () => ({
  onboardingLoad: vi.fn(),
  onboardingUpdate: vi.fn(),
}));

function baseState(over: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    flow_version: 1,
    status: "not_started",
    current_step: "",
    completed_steps: [] as string[],
    skipped_steps: [] as string[],
    last_error_code: "",
    source: "",
    ...over,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  vi.mocked(onboardingLoad).mockResolvedValue(baseState() as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OnboardingWizard (ONB-01/07)", () => {
  it("renders begin when not started; begin checkpoints in_progress", async () => {
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(wrapper.find(".ob-title").text()).toContain("AISC Workbench");
    expect(wrapper.find(".ob-btn.primary").text()).toBe("开始设置");

    await wrapper.find(".ob-btn.primary").trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      status: "in_progress",
      currentStep: "environment",
    });
    wrapper.unmount();
  });

  it("renders finished state when onboarding is complete", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "completed", completed_steps: ["complete"] }) as never,
    );
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(wrapper.find(".ob-finished").exists()).toBe(true);
    wrapper.unmount();
  });

  it("skip checkpoints to skipped status", async () => {
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.find(".ob-btn.ghost").trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({ status: "skipped" });
    wrapper.unmount();
  });
});
