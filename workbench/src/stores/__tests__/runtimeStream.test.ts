/**
 * Stage 1 (S1.8, F-A10): IPC fake — Channel events drive the store buffer.
 *
 * A fake Tauri Channel (manual `emit`) feeds PTY output events through
 * openSession's handler; the store buffers them in the non-reactive pending
 * queue and a single rAF flush lands them in paneStreams. This proves the
 * front-end data plane works against a controlled IPC fake without a real
 * PTY.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import { AGENT_TITLE, newPaneTab } from "../tabLayout";

type EventLike = { type: string; bytes?: string; reason?: string; exitCode?: number | null };

const channelInstances: Array<{ onmessage: (ev: EventLike) => void }> = [];

vi.mock("@tauri-apps/api/core", () => ({
  Channel: class {
    onmessage: (ev: EventLike) => void = () => {};
    constructor() {
      channelInstances.push(this as never);
    }
  },
}));

vi.mock("../../lib/ipc", () => ({
  openSession: vi.fn().mockResolvedValue({}),
  ackSessionExit: vi.fn().mockResolvedValue(null),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  runtimeInspect: vi.fn(),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  stopRuntime: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: vi.fn(() => ({
    isFocused: vi.fn().mockResolvedValue(true),
    isMinimized: vi.fn().mockResolvedValue(false),
  })),
}));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(false),
  requestPermission: vi.fn().mockResolvedValue("denied"),
  sendNotification: vi.fn().mockResolvedValue(undefined),
}));

function flushFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

beforeEach(() => {
  setActivePinia(createPinia());
  channelInstances.length = 0;
});

describe("S1.8 IPC fake → store buffer", () => {
  it("buffers PTY output chunks into paneStreams via a fake Channel", async () => {
    const s = useRuntimeStore();
    s.runtimeId = "11111111-1111-4111-8111-111111111111";
    s.workspace = "/ws";
    const tab = newPaneTab("t1", "bash", AGENT_TITLE.bash, null);
    s.tabs = [tab];
    s.activeTabId = "t1";

    await s.openTab("t1");
    const channel = channelInstances[0];
    expect(channel).toBeDefined();

    channel.onmessage({ type: "output", bytes: "aGVsbG8=" }); // "hello"
    await flushFrame();

    const paneId = tab.activePaneId;
    expect(s.paneStreams[paneId]).toContain("aGVsbG8=");
    expect(s.streamCursor[paneId]).toBe(1);
    // Batching: two more chunks in one flush land together, order preserved.
    channel.onmessage({ type: "output", bytes: "IHdvcmxk" }); // " world"
    channel.onmessage({ type: "output", bytes: "IQ==" }); // "!"
    await flushFrame();
    expect(s.paneStreams[paneId]).toEqual(["aGVsbG8=", "IHdvcmxk", "IQ=="]);
    expect(s.streamCursor[paneId]).toBe(3);
  });

  it("drops events from a stale session after the pane sessionId moves", async () => {
    const s = useRuntimeStore();
    s.runtimeId = "11111111-1111-4111-8111-111111111111";
    s.workspace = "/ws";
    const tab = newPaneTab("t1", "bash", AGENT_TITLE.bash, null);
    s.tabs = [tab];
    s.activeTabId = "t1";

    await s.openTab("t1");
    const first = channelInstances[0]!;
    first.onmessage({ type: "output", bytes: "aGVsbG8=" });
    await flushFrame();
    expect(s.paneStreams[tab.activePaneId]).toHaveLength(1);

    // A reopen moves the pane to a NEW session id; the old channel's late
    // events must be dropped (F-R04) and never count as liveness proof.
    tab.panes[tab.activePaneId]!.sessionId = "new-session-id";
    first.onmessage({ type: "output", bytes: "b2xk" }); // stale "old"
    await flushFrame();
    expect(s.paneStreams[tab.activePaneId]).toEqual(["aGVsbG8="]); // unchanged
  });
});
