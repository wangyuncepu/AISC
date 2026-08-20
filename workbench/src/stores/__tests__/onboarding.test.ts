/**
 * Stage 5 (ONB-01): onboarding store — load, patch, step helpers, finished flags.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useOnboardingStore } from "../onboarding";
import { onboardingLoad, onboardingUpdate } from "../../lib/ipc";

vi.mock("../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
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
  vi.mocked(onboardingLoad).mockResolvedValue(baseState() as never);
});

describe("onboarding store (ONB-01)", () => {
  it("loads the persisted state and exposes status", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({ status: "in_progress", current_step: "environment" }) as never,
    );
    const s = useOnboardingStore();
    await s.load();
    expect(s.loaded).toBe(true);
    expect(s.status).toBe("in_progress");
    expect(s.state?.current_step).toBe("environment");
  });

  it("reports finished for completed/skipped/abandoned", async () => {
    for (const status of ["completed", "skipped", "abandoned"]) {
      vi.mocked(onboardingLoad).mockResolvedValue(baseState({ status }) as never);
      const s = useOnboardingStore();
      await s.load();
      expect(s.isFinished).toBe(true);
      expect(s.isInProgress).toBe(false);
    }
  });

  it("patch delegates to onboardingUpdate and stores the returned state", async () => {
    vi.mocked(onboardingUpdate).mockResolvedValue(
      baseState({
        status: "in_progress",
        current_step: "workspace",
        completed_steps: ["environment"],
      }) as never,
    );
    const s = useOnboardingStore();
    await s.load();
    const ok = await s.patch({ currentStep: "workspace", completeStep: "environment" });
    expect(ok).toBe(true);
    expect(onboardingUpdate).toHaveBeenCalledWith({
      currentStep: "workspace",
      completeStep: "environment",
    });
    expect(s.state?.status).toBe("in_progress");
    expect(s.isStepComplete("environment")).toBe(true);
  });

  it("load failure fails closed (error set, loaded true)", async () => {
    vi.mocked(onboardingLoad).mockRejectedValue(new Error("corrupt"));
    const s = useOnboardingStore();
    await s.load();
    expect(s.loaded).toBe(true);
    expect(s.error).toMatch(/corrupt/i);
    expect(s.status).toBe("not_started");
  });

  it("step helpers track complete and skipped independently", async () => {
    vi.mocked(onboardingLoad).mockResolvedValue(
      baseState({
        status: "in_progress",
        completed_steps: ["welcome"],
        skipped_steps: ["network"],
      }) as never,
    );
    const s = useOnboardingStore();
    await s.load();
    expect(s.isStepComplete("welcome")).toBe(true);
    expect(s.isStepComplete("network")).toBe(false);
    expect(s.isSkipped("network")).toBe(true);
  });
});
