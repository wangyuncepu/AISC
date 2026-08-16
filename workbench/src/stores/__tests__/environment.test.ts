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

  it("startDocker delegates and surfacing errors", async () => {
    vi.mocked(startDocker).mockResolvedValue(undefined);
    const s = useEnvironmentStore();
    await s.startDocker();
    expect(startDocker).toHaveBeenCalledTimes(1);
    expect(s.error).toBeNull();
  });

  it("startDocker failure sets error without throwing", async () => {
    vi.mocked(startDocker).mockRejectedValue(new Error("not found"));
    const s = useEnvironmentStore();
    await s.startDocker();
    expect(s.error).toMatch(/not found/i);
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
});
