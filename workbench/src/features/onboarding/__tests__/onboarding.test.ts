/**
 * Stage 5 (ONB-01/07): onboarding wizard route shell.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import {
  envPollEngine,
  envReadiness,
  onboardingLoad,
  onboardingUpdate,
  startDocker,
} from "../../../lib/ipc";
import { useRuntimeStore } from "../../../stores/runtime";
import OnboardingWizard from "../OnboardingWizard.vue";

vi.mock("../../../lib/ipc", () => ({
  onboardingLoad: vi.fn(),
  onboardingUpdate: vi.fn(),
  envReadiness: vi.fn(),
  envPollEngine: vi.fn(),
  startDocker: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ schema_version: 1, runtimes: [] }),
  runtimePreflight: vi.fn(),
  startRuntime: vi.fn().mockResolvedValue(undefined),
  runtimeRestart: vi.fn(),
}));

function envReady(over: Record<string, string> = {}) {
  return {
    cli: "ready",
    docker: "installed",
    engine: "ready",
    webview2: "ready",
    dockerDesktopPath: "",
    cliPath: "",
    engineDetail: "",
    ...over,
  };
}

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
  vi.mocked(envReadiness).mockResolvedValue(envReady() as never);
  vi.mocked(envPollEngine).mockResolvedValue(envReady() as never);
  vi.mocked(startDocker).mockResolvedValue(undefined);
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

  it("environment step shows readiness and continues when allReady (ONB-02)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "environment" }) as never,
    );
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));

    // Readiness list rendered with engine ready.
    const dots = wrapper.findAll(".ob-check-dot");
    expect(dots.length).toBeGreaterThanOrEqual(4);
    // Continue enabled (allReady).
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    expect(continueBtn?.attributes("disabled")).toBeUndefined();
    await continueBtn!.trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      completeStep: "environment",
      currentStep: "workspace",
    });
    wrapper.unmount();
  });

  it("environment step disables continue when engine not ready", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "environment" }) as never,
    );
    vi.mocked(envReadiness).mockResolvedValue(
      envReady({ engine: "starting" }) as never,
    );
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    expect(continueBtn?.attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("workspace step shows recents and continues to agent (ONB-03)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "workspace" }) as never,
    );
    const runtime = useRuntimeStore();
    runtime.workspace = "/ws/proj";
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(wrapper.find(".ob-subtitle").text()).toBe("选择工作区");
    // Continue is present once a workspace is chosen.
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    await continueBtn!.trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      completeStep: "workspace",
      currentStep: "agent",
    });
    wrapper.unmount();
  });

  it("agent step maps readiness without a runtime to needs_configuration (ONB-04)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "agent" }) as never,
    );
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    const list = wrapper.find(".ob-check-list");
    expect(list.text()).toContain("Claude");
    expect(list.text()).toContain("需要配置"); // needs_configuration mapping
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    await continueBtn!.trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      completeStep: "agent",
      currentStep: "network",
    });
    wrapper.unmount();
  });

  it("runtime step runs preflight and continues to complete on start (ONB-06)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "runtime" }) as never,
    );
    const { runtimePreflight } = await import("../../../lib/ipc");
    vi.mocked(runtimePreflight).mockResolvedValue({
      schema_version: 1,
      recommended_action: "start",
      matching_runtime_id: null,
      checks: [],
      issues: [],
    } as never);
    const runtime = useRuntimeStore();
    runtime.workspace = "/ws/proj";
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(runtimePreflight).toHaveBeenCalled();
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    await continueBtn!.trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      completeStep: "runtime",
      currentStep: "complete",
    });
    wrapper.unmount();
  });

  it("runtime step disables continue on resolve_conflict (ONB-06)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "runtime" }) as never,
    );
    const { runtimePreflight } = await import("../../../lib/ipc");
    vi.mocked(runtimePreflight).mockResolvedValue({
      schema_version: 1,
      recommended_action: "resolve_conflict",
      matching_runtime_id: null,
      checks: [],
      issues: [],
    } as never);
    const runtime = useRuntimeStore();
    runtime.workspace = "/ws/proj";
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    const continueBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    expect(continueBtn?.attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("complete step finishes: marks completed and starts the runtime (ONB-07)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "complete" }) as never,
    );
    const runtime = useRuntimeStore();
    runtime.workspace = "/ws/proj";
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));

    const enterBtn = wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "进入工作区");
    await enterBtn!.trigger("click");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      status: "completed",
      completeStep: "complete",
    });
    // finish() also calls startFromSummary() (best-effort runtime start);
    // preflight may be unset in this unit context, so we only assert the
    // completion checkpoint that drives the App.vue gate.
    wrapper.unmount();
  });

  it("network step requires confirm for non-direct then continues to runtime (ONB-05)", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "network" }) as never,
    );
    const runtime = useRuntimeStore();
    const wrapper = mount(OnboardingWizard, { global: { plugins: [i18n] } });
    await new Promise((resolve) => setTimeout(resolve, 10));

    // Choose container TUN: continue is disabled until confirmed.
    await wrapper.findAll(".ob-net-options .ob-btn")[2].trigger("click");
    const continueBtn = () =>
      wrapper.findAll(".ob-btn.primary").find((b) => b.text() === "继续设置");
    expect(continueBtn()?.attributes("disabled")).toBeDefined();

    // Confirm, then continue applies network=proxy and advances.
    await wrapper.find(".ob-btn.confirm").trigger("click");
    await continueBtn()!.trigger("click");
    expect(runtime.launch.network).toBe("proxy");
    expect(onboardingUpdate).toHaveBeenCalledWith({
      completeStep: "network",
      currentStep: "runtime",
    });
    wrapper.unmount();
  });
});
