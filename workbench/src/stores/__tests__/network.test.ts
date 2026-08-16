/**
 * Stage 5 (A-ONB05): network store — choice, probe, confirm, revoke.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useNetworkStore } from "../network";
import { envReadiness } from "../../lib/ipc";

vi.mock("../../lib/ipc", () => ({
  envReadiness: vi.fn(),
}));

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("network store (A-ONB05)", () => {
  it("defaults to direct and unconfirmed", () => {
    const s = useNetworkStore();
    expect(s.choice).toBe("direct");
    expect(s.confirmed).toBe(false);
  });

  it("changing choice resets confirm and probe result", () => {
    const s = useNetworkStore();
    s.confirm();
    expect(s.confirmed).toBe(true);
    s.setChoice("container_tun");
    expect(s.confirmed).toBe(false);
    expect(s.probeResult).toBeNull();
  });

  it("probe reports ok when engine ready", async () => {
    vi.mocked(envReadiness).mockResolvedValue({
      cli: "ready",
      docker: "installed",
      engine: "ready",
      webview2: "ready",
      dockerDesktopPath: "",
      cliPath: "",
    } as never);
    const s = useNetworkStore();
    await s.probe();
    expect(s.probeResult).toBe("ok");
    expect(s.probing).toBe(false);
  });

  it("probe reports failed when engine not ready", async () => {
    vi.mocked(envReadiness).mockResolvedValue({
      cli: "ready",
      docker: "installed",
      engine: "starting",
      webview2: "ready",
      dockerDesktopPath: "",
      cliPath: "",
    } as never);
    const s = useNetworkStore();
    await s.probe();
    expect(s.probeResult).toBe("failed");
  });

  it("revoke resets to direct and un-confirms", () => {
    const s = useNetworkStore();
    s.setChoice("host_proxy");
    s.confirm();
    expect(s.choice).toBe("host_proxy");
    expect(s.confirmed).toBe(true);
    s.revoke();
    expect(s.choice).toBe("direct");
    expect(s.confirmed).toBe(false);
    expect(s.probeResult).toBeNull();
  });
});
