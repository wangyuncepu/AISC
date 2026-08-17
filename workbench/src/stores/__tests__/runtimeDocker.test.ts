/**
 * Docker wake-up boot loop (KI-1 UX, user feedback 2026-08-17): the polling
 * must be QUIET — `status` never flips (summary→preflight→summary every 3s
 * was a full-view flash), the report turns green IN PLACE, and the loop stops
 * with a stable timeout error instead of hanging.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import type { PreflightReport } from "../../types";

const mockIpc = vi.hoisted(() => ({
  startDocker: vi.fn(),
  runtimePreflight: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
}));

vi.mock("../../lib/ipc", () => mockIpc);

function report(docker: "pass" | "fail"): PreflightReport {
  return {
    spec: {},
    checks: [
      {
        id: "docker",
        status: docker,
        error_code: docker === "fail" ? "AISC_ERR_DOCKER_UNAVAILABLE" : null,
        detail: null,
      },
    ],
    can_start: docker === "pass",
    recommended_action: "start",
    matching_runtime_id: null,
    conflicts: null,
    observed_at: "2026-01-01T00:00:00Z",
  };
}

function setup(): ReturnType<typeof useRuntimeStore> {
  const s = useRuntimeStore();
  s.status = "summary";
  s.workspace = "C:\\ws";
  s.runtimeId = "rid-1";
  return s;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mockIpc.startDocker.mockResolvedValue(undefined);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("startDockerAndRepreflight (quiet boot loop)", () => {
  it("never flips status while probing; turns the gate green in place", async () => {
    const s = setup();
    mockIpc.runtimePreflight
      .mockResolvedValueOnce(report("fail")) // boot still in progress
      .mockResolvedValueOnce(report("pass")); // engine up

    const pending = s.startDockerAndRepreflight();
    await vi.advanceTimersByTimeAsync(0); // first probe runs immediately
    expect(s.dockerStarting).toBe(true);
    expect(s.status).toBe("summary"); // NO summary→preflight→summary flash
    expect(s.preflight?.checks[0]?.status).toBe("fail");

    await vi.advanceTimersByTimeAsync(3_000); // second probe succeeds
    expect(s.dockerStarting).toBe(false);
    expect(s.dockerStartedAt).toBeNull();
    expect(s.status).toBe("summary"); // green in place, no churn
    expect(s.preflight?.checks[0]?.status).toBe("pass");
    expect(s.error).toBeNull();
    await pending;
  });

  it("marks the elapsed clock while starting and clears it after", async () => {
    const s = setup();
    mockIpc.runtimePreflight.mockResolvedValue(report("fail"));
    const pending = s.startDockerAndRepreflight();
    await vi.advanceTimersByTimeAsync(0);
    expect(typeof s.dockerStartedAt).toBe("number");
    await vi.advanceTimersByTimeAsync(3_000);
    expect(s.dockerStarting).toBe(true); // still booting, clock still set
    await vi.advanceTimersByTimeAsync(120_000); // exhaust the deadline
    expect(s.dockerStarting).toBe(false);
    expect(s.dockerStartedAt).toBeNull();
    await pending;
  });

  it("times out with a stable error and stays on summary", async () => {
    const s = setup();
    mockIpc.runtimePreflight.mockRejectedValue(new Error("engine unreachable"));
    const pending = s.startDockerAndRepreflight();
    await vi.advanceTimersByTimeAsync(130_000);
    expect(s.dockerStarting).toBe(false);
    expect(s.status).toBe("summary");
    expect(s.error?.code).toBe("WB_ERR_DOCKER_START_TIMEOUT");
    await pending;
  });

  it("a startDocker failure surfaces the error and stops the loop", async () => {
    const s = setup();
    mockIpc.startDocker.mockRejectedValue({
      code: "WB_ERR_CLI",
      message: "spawn failed",
    });
    await s.startDockerAndRepreflight();
    expect(s.dockerStarting).toBe(false);
    expect(s.error?.message).toBe("spawn failed");
    expect(mockIpc.runtimePreflight).not.toHaveBeenCalled();
  });
});
