/**
 * svc-4 (web services): the per-workspace services cache — refresh, the
 * ids-only open path (backend owns URL generation/validation), the degraded
 * old-CLI path, and stop/remove clearing.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import * as ipc from "../../lib/ipc";
import type { RuntimeServicesResult } from "../../types";

vi.mock("../../lib/ipc", () => ({
  runtimeServices: vi.fn(),
  openRuntimeServiceUrl: vi.fn(),
  logUiEvent: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({}) }));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));

const RID = "11111111-1111-4111-8111-111111111111";

const PAYLOAD: RuntimeServicesResult = {
  schema_version: "aisc.runtime-services/v1",
  runtime_id: RID,
  gateway: { state: "ready", container_port: 45871, host_port: 47831, host: "127.0.0.1" },
  services: [
    {
      port: 3000,
      protocol: "http",
      name: "docs preview",
      state: "registered",
      url: "http://p3000.localhost:47831/",
    },
  ],
  observed_at: "2026-08-25T00:00:00Z",
};

function setup() {
  const store = useRuntimeStore();
  store.runtimeId = RID;
  store.workspace = "C:\\ws";
  return store;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.mocked(ipc.runtimeServices).mockReset();
  vi.mocked(ipc.openRuntimeServiceUrl).mockReset();
});

describe("svc-4 web services cache", () => {
  it("refreshWebServices stores the payload and clears prior errors", async () => {
    const store = setup();
    vi.mocked(ipc.runtimeServices).mockResolvedValue(PAYLOAD);
    await store.refreshWebServices();
    expect(ipc.runtimeServices).toHaveBeenCalledWith("C:\\ws", RID);
    expect(store.webServices?.gateway.state).toBe("ready");
    expect(store.webServices?.services[0]?.url).toBe("http://p3000.localhost:47831/");
    expect(store.webServicesError).toBeNull();
  });

  it("openWebService passes ids only — never a URL — then refreshes", async () => {
    const store = setup();
    const calls: unknown[][] = [];
    vi.mocked(ipc.openRuntimeServiceUrl).mockImplementation(async (...args: unknown[]) => {
      calls.push(args);
      return "http://p3000.localhost:47831/";
    });
    vi.mocked(ipc.runtimeServices).mockResolvedValue(PAYLOAD);
    await store.openWebService(3000);
    expect(calls).toEqual([["C:\\ws", RID, 3000]]);
    expect(store.webServicesError).toBeNull();
  });

  it("an open failure surfaces as webServicesError without crashing", async () => {
    const store = setup();
    vi.mocked(ipc.openRuntimeServiceUrl).mockRejectedValue({
      code: "WB_ERR_AISC",
      message: "boom",
      technical_detail: null,
      retryable: false,
      action: "retry",
    });
    await store.openWebService(3000);
    expect(store.webServicesError?.message).toBe("boom");
  });

  it("an old CLI (no runtime services) keeps the last payload and records the error", async () => {
    const store = setup();
    vi.mocked(ipc.runtimeServices).mockResolvedValue(PAYLOAD);
    await store.refreshWebServices();
    vi.mocked(ipc.runtimeServices).mockRejectedValue({
      code: "WB_ERR_AISC",
      message: "unrecognized command",
      technical_detail: null,
      retryable: false,
      action: "upgrade_cli",
    });
    await store.refreshWebServices();
    // degraded, not wiped: the panel gates on capability and keeps context
    expect(store.webServices?.gateway.state).toBe("ready");
    expect(store.webServicesError?.message).toBe("unrecognized command");
  });

  it("refresh is deduped while in flight", async () => {
    const store = setup();
    let resolve!: (v: RuntimeServicesResult) => void;
    vi.mocked(ipc.runtimeServices).mockImplementation(
      () => new Promise((r) => (resolve = r)),
    );
    const first = store.refreshWebServices();
    const second = store.refreshWebServices();
    resolve(PAYLOAD);
    await Promise.all([first, second]);
    expect(ipc.runtimeServices).toHaveBeenCalledTimes(1);
  });

  it("clearWebServices empties the openable state (stop/remove path)", () => {
    const store = setup();
    store.webServices = PAYLOAD;
    store.clearWebServices();
    expect(store.webServices).toBeNull();
    expect(store.webServicesError).toBeNull();
    expect(store.webServicesInFlight).toBe(false);
  });

  it("auto-polls every 8s while ready+running+capable, not otherwise", async () => {
    vi.useFakeTimers();
    try {
      const store = setup();
      store.capability = { runtime_services: true } as never;
      store.status = "ready";
      store.runtimeState = "running";
      vi.mocked(ipc.runtimeServices).mockResolvedValue(PAYLOAD);

      // not polled before the interval elapses
      expect(ipc.runtimeServices).toHaveBeenCalledTimes(0);
      await vi.advanceTimersByTimeAsync(8_000);
      expect(ipc.runtimeServices).toHaveBeenCalledTimes(1);

      // capability missing → the next tick is a no-op
      store.capability = { runtime_services: false } as never;
      await vi.advanceTimersByTimeAsync(16_000);
      expect(ipc.runtimeServices).toHaveBeenCalledTimes(1);

      // stopped runtime → still a no-op
      store.capability = { runtime_services: true } as never;
      store.runtimeState = "stopped";
      await vi.advanceTimersByTimeAsync(16_000);
      expect(ipc.runtimeServices).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
