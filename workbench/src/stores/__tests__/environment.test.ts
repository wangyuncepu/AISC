/**
 * Stage 5 (A-ONB02): environment readiness store — installed ≠ engine ready,
 * refresh, startDocker, deadline poll.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useEnvironmentStore } from "../environment";
import { envPollEngine, envReadiness, startDocker } from "../../lib/ipc";

vi.mock("../../lib/ipc", () => ({
  envReadiness: vi.fn(),
  envPollEngine: vi.fn(),
  startDocker: vi.fn(),
}));

function ready(over: Partial<ReturnType<typeof Object> & Record<string, string>> = {}) {
  return {
    cli: "ready",
    docker: "installed",
    engine: "ready",
    webview2: "ready",
    dockerDesktopPath: "C:\\Docker Desktop.exe",
    cliPath: "C:\\aisc.exe",
    engineDetail: "",
    ...over,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("environment store (A-ONB02)", () => {
  it("refresh loads readiness and flags allReady when cli+engine ready", async () => {
    vi.mocked(envReadiness).mockResolvedValue(ready() as never);
    const s = useEnvironmentStore();
    await s.refresh();
    expect(s.cliReady).toBe(true);
    expect(s.engineReady).toBe(true);
    expect(s.allReady).toBe(true);
  });

  it("installed docker with starting engine is NOT allReady (installed ≠ ready)", async () => {
    vi.mocked(envReadiness).mockResolvedValue(
      ready({ docker: "installed", engine: "starting" }) as never,
    );
    const s = useEnvironmentStore();
    await s.refresh();
    expect(s.dockerInstalling).toBe(true);
    expect(s.allReady).toBe(false);
  });

  it("not_installed docker also triggers install-and-start (A-ONB02/B)", async () => {
    vi.mocked(envReadiness).mockResolvedValue(
      ready({ docker: "not_installed", engine: "unavailable" }) as never,
    );
    const s = useEnvironmentStore();
    await s.refresh();
    expect(s.dockerInstalling).toBe(true);
    expect(s.allReady).toBe(false);
  });

  it("startDocker delegates and clears installing after success", async () => {
    vi.mocked(startDocker).mockResolvedValue(undefined);
    const s = useEnvironmentStore();
    const p = s.startDocker();
    expect(s.installing).toBe(true); // shows "Installing Docker Desktop…"
    await p;
    expect(startDocker).toHaveBeenCalledTimes(1);
    expect(s.installing).toBe(false);
    expect(s.error).toBeNull();
  });

  it("startDocker failure sets error without throwing", async () => {
    vi.mocked(startDocker).mockRejectedValue(new Error("not found"));
    const s = useEnvironmentStore();
    await s.startDocker();
    expect(s.error).toMatch(/not found/i);
    expect(s.dockerStarting).toBe(false); // no progress state on failure
  });

  it("successful wake-up enters the progress state until the engine answers (KI-1 UX)", async () => {
    vi.mocked(startDocker).mockResolvedValue(undefined);
    vi.mocked(envReadiness).mockResolvedValue(ready({ engine: "starting" }) as never);
    const s = useEnvironmentStore();
    await s.startDocker();
    expect(s.installing).toBe(false);
    expect(s.dockerStarting).toBe(true); // spinner shown
    expect(typeof s.dockerStartedAt).toBe("number");

    // Auto-poll refresh with the engine still starting: progress persists.
    await s.refresh();
    expect(s.dockerStarting).toBe(true);

    // Engine answers → progress cleared.
    vi.mocked(envReadiness).mockResolvedValue(ready() as never);
    await s.refresh();
    expect(s.dockerStarting).toBe(false);
    expect(s.dockerStartedAt).toBeNull();
  });

  it("a second startDocker while a wake-up is in flight is ignored", async () => {
    vi.mocked(startDocker).mockResolvedValue(undefined);
    const s = useEnvironmentStore();
    const callsBefore = vi.mocked(startDocker).mock.calls.length;
    await s.startDocker();
    await s.startDocker(); // re-entry guard: no re-spawn
    expect(vi.mocked(startDocker).mock.calls.length).toBe(callsBefore + 1);
    expect(s.dockerStarting).toBe(true);
  });

  it("progress state gives up after the deadline even if the engine never answers", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(startDocker).mockResolvedValue(undefined);
      vi.mocked(envReadiness).mockResolvedValue(
        ready({ docker: "installed", engine: "unavailable" }) as never,
      );
      const s = useEnvironmentStore();
      // Seed readiness first — the auto-poll self-stops while docker reads
      // "unknown" (dockerInstalling false), as it would already be loaded in
      // the wizard when the user clicks 启动.
      await s.refresh();
      await s.startDocker();
      expect(s.dockerStarting).toBe(true);
      // The deadline check lives in refresh(); the wizard's auto-poll drives it.
      s.startAutoPoll();
      await vi.advanceTimersByTimeAsync(180_000 + 5_000);
      // refresh ran on the auto-poll past the deadline → cleared.
      expect(s.dockerStarting).toBe(false);
      expect(s.dockerStartedAt).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("pollEngineReady returns after deadline and sets polling", async () => {
    vi.mocked(envPollEngine).mockResolvedValue(ready() as never);
    const s = useEnvironmentStore();
    const pollP = s.pollEngineReady(3000);
    expect(s.polling).toBe(true);
    const result = await pollP;
    expect(envPollEngine).toHaveBeenCalledWith(3000);
    expect(result.engine).toBe("ready");
    expect(s.polling).toBe(false);
  });

  it("auto-poll refreshes while Docker is starting and self-stops when ready", async () => {
    vi.useFakeTimers();
    try {
      // refresh #1 (manual, starting) · #2 (auto tick, starting) ·
      // #3 (auto tick, ready) → dockerInstalling flips false → next tick stops.
      let n = 0;
      vi.mocked(envReadiness).mockImplementation(async () => {
        n += 1;
        return ready({ engine: n >= 3 ? "ready" : "starting" }) as never;
      });
      const s = useEnvironmentStore();
      await s.refresh();
      expect(s.allReady).toBe(false);

      s.startAutoPoll();
      await vi.advanceTimersByTimeAsync(5000);
      await vi.advanceTimersByTimeAsync(5000);
      expect(s.allReady).toBe(true);

      // Engine ready → auto-poll self-stops; further ticks do nothing.
      const calls = n;
      await vi.advanceTimersByTimeAsync(5000 * 5);
      expect(n).toBe(calls);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stopAutoPoll clears the interval", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(envReadiness).mockResolvedValue(ready({ engine: "starting" }) as never);
      const s = useEnvironmentStore();
      await s.refresh();
      s.startAutoPoll();
      s.stopAutoPoll();
      const calls = vi.mocked(envReadiness).mock.calls.length;
      await vi.advanceTimersByTimeAsync(5000 * 3);
      expect(vi.mocked(envReadiness).mock.calls.length).toBe(calls);
    } finally {
      vi.useRealTimers();
    }
  });
});
