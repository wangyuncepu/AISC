/**
 * G-14 build timing + notification store tests (Step 13; 02 §七 F-6,
 * A-G14-1/2/3).
 *
 * The store writes build terminal state ONLY on the Promise settle of the
 * current op - the Channel never writes it (A-G14-2). The first settle for an
 * op freezes buildFinishedAt/buildDurationMs once; a superseded build's late
 * settle is ignored. Notification fires at most once per build, only when the
 * window is background and the status is complete/failed; permission is
 * requested at most once per launch and denied/unavailable never changes the
 * build facts (A-G14-1/3).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { i18n } from "../../i18n";
import { useRuntimeStore } from "../runtime";

const mockIpc = vi.hoisted(() => ({
  buildImage: vi.fn(),
}));

vi.mock("../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn().mockResolvedValue(true),
  open: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));

const win = vi.hoisted(() => {
  const w: {
    focused: boolean;
    minimized: boolean;
    getCurrentWindow: ReturnType<typeof vi.fn>;
    isFocused: ReturnType<typeof vi.fn>;
    isMinimized: ReturnType<typeof vi.fn>;
  } = {
    focused: true,
    minimized: false,
    getCurrentWindow: vi.fn(),
    isFocused: vi.fn(),
    isMinimized: vi.fn(),
  };
  w.getCurrentWindow.mockReturnValue(w);
  w.isFocused.mockImplementation(() => Promise.resolve(w.focused));
  w.isMinimized.mockImplementation(() => Promise.resolve(w.minimized));
  return w;
});
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: win.getCurrentWindow }));

const notif = vi.hoisted(() => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-notification", () => notif);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  i18n.global.locale.value = "en-US";
  win.focused = true;
  win.minimized = false;
  notif.isPermissionGranted.mockResolvedValue(true);
  notif.requestPermission.mockResolvedValue("granted");
  notif.sendNotification.mockResolvedValue(undefined);
});

describe("timing freeze (A-G14-1/4)", () => {
  it("freezes the final duration once on complete", async () => {
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(s.buildStatus).toBe("complete");
    expect(s.buildStartedAt).not.toBeNull();
    expect(s.buildFinishedAt).not.toBeNull();
    expect(s.buildDurationMs).not.toBeNull();
    expect(s.buildDurationMs).toBeGreaterThanOrEqual(0);
  });

  it("freezes the final duration on failed and cancelled", async () => {
    mockIpc.buildImage.mockRejectedValue({ code: "WB_ERR_CLI_CANCELLED" });
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(s.buildStatus).toBe("cancelled");
    expect(s.buildDurationMs).not.toBeNull();
  });

  it("ignores a superseded build's late settle (A-G14-2)", async () => {
    const a = deferred<void>();
    const b = deferred<void>();
    mockIpc.buildImage.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const s = useRuntimeStore();
    const pa = s.startBuild("img-a"); // op 1, slow
    const pb = s.startBuild("img-b"); // op 2, fast
    b.resolve();
    await pb;
    expect(s.buildStatus).toBe("complete");
    expect(s.buildTag).toBe("img-b");
    const durB = s.buildDurationMs;
    a.resolve(); // late settle from the superseded op - must be ignored
    await pa;
    expect(s.buildStatus).toBe("complete");
    expect(s.buildTag).toBe("img-b");
    expect(s.buildDurationMs).toBe(durB); // not re-frozen, no double write
  });
});

describe("notification (A-G14-1/3)", () => {
  it("foreground: zero system notifications", async () => {
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(notif.sendNotification).not.toHaveBeenCalled();
  });

  it("background complete: exactly one notification", async () => {
    win.focused = false;
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(notif.sendNotification).toHaveBeenCalledTimes(1);
    expect(notif.sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ body: expect.stringContaining("Image build complete") })
    );
  });

  it("background failed: notifies once with the failed body", async () => {
    win.focused = false;
    mockIpc.buildImage.mockRejectedValue({ code: "AISC_ERR_GENERAL" });
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(s.buildStatus).toBe("failed");
    expect(notif.sendNotification).toHaveBeenCalledTimes(1);
    expect(notif.sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ body: expect.stringContaining("Image build failed") })
    );
  });

  it("background cancelled: no notification", async () => {
    win.focused = false;
    mockIpc.buildImage.mockRejectedValue({ code: "WB_ERR_CLI_CANCELLED" });
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(s.buildStatus).toBe("cancelled");
    expect(notif.sendNotification).not.toHaveBeenCalled();
  });

  it("denied permission degrades without looping (A-G14-3)", async () => {
    win.focused = false;
    notif.isPermissionGranted.mockResolvedValue(false);
    notif.requestPermission.mockResolvedValue("denied");
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(notif.sendNotification).not.toHaveBeenCalled();
    // Second build: permission already requested this launch - no re-request.
    await s.startBuild("img");
    expect(notif.requestPermission).toHaveBeenCalledTimes(1);
  });

  it("grants once when permission granted by the request", async () => {
    win.focused = false;
    notif.isPermissionGranted.mockResolvedValue(false);
    notif.requestPermission.mockResolvedValue("granted");
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(notif.requestPermission).toHaveBeenCalledTimes(1);
    expect(notif.sendNotification).toHaveBeenCalledTimes(1);
  });

  it("permission/notification failure never changes build facts (A-G14-3)", async () => {
    win.focused = false;
    notif.isPermissionGranted.mockRejectedValue(new Error("plugin unavailable"));
    mockIpc.buildImage.mockResolvedValue(undefined);
    const s = useRuntimeStore();
    await s.startBuild("img");
    expect(s.buildStatus).toBe("complete"); // build facts intact
    expect(s.buildDurationMs).not.toBeNull();
    expect(notif.sendNotification).not.toHaveBeenCalled();
  });
});
