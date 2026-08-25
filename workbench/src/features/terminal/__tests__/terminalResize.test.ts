/**
 * B-05 (terminal stability): xterm ↔ PTY size convergence — the component
 * behaviors behind fixes F1..F5 (see b05-terminal-stability/plan.md).
 *
 * xterm + addons are faked (jsdom has no canvas/RO); the runtime store is
 * driven through the REAL workspace birth path, then pane state is flipped
 * like the store does in production.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore } from "../../../stores/workspaces";
import { useRuntimeStore } from "../../../stores/runtime";
import type { Tab } from "../../../types";
import Terminal from "../Terminal.vue";

const h = vi.hoisted(() => ({
  fitSize: { cols: 118, rows: 30 },
  resizeSession: vi.fn().mockResolvedValue(undefined),
  writeSession: vi.fn().mockResolvedValue(undefined),
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
}));

vi.mock("../../../lib/ipc", () => ({
  resizeSession: h.resizeSession,
  writeSession: h.writeSession,
  logUiEvent: h.logUiEvent,
  loadHistory: h.loadHistory,
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  openSession: vi.fn().mockResolvedValue({}),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  stopRuntime: vi.fn().mockResolvedValue({ state: "stopped" }),
  runtimeInspect: vi.fn().mockResolvedValue({ state: "stopped" }),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn().mockResolvedValue(true), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
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

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    options: Record<string, unknown> = {};
    loadAddon(addon: { activate?: (t: unknown) => void }) {
      addon?.activate?.(this);
    }
    open() {}
    write(_d: unknown, cb?: () => void) {
      cb?.();
    }
    writeln(_d: unknown, cb?: () => void) {
      cb?.();
    }
    onData() {}
    onSelectionChange() {}
    attachCustomKeyEventHandler() {}
    dispose() {}
    refresh() {}
    focus() {}
    clear() {}
    getSelection() {
      return "";
    }
    paste() {}
  },
}));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    term: { cols: number; rows: number } | null = null;
    activate(t: { cols: number; rows: number }) {
      this.term = t;
    }
    dispose() {}
    fit() {
      if (this.term) {
        this.term.cols = h.fitSize.cols;
        this.term.rows = h.fitSize.rows;
      }
    }
    proposeDimensions() {
      return { cols: h.fitSize.cols, rows: h.fitSize.rows };
    }
  },
}));
vi.mock("@xterm/addon-webgl", () => ({
  WebglAddon: class {
    onContextLoss() {}
    dispose() {}
  },
}));
vi.mock("@xterm/addon-search", () => ({
  SearchAddon: class {
    onDidChangeResults() {}
    findNext() {}
    findPrevious() {}
    clearDecorations() {}
    dispose() {}
  },
}));

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function bareTab(id: string): Tab {
  const paneId = id;
  return {
    tabId: id,
    agent: "bash",
    title: "Bash",
    sessionId: null,
    sessionState: "idle",
    exit: null,
    savedTabId: null,
    tree: { kind: "pane", paneId, sessionType: "bash" },
    activePaneId: paneId,
    panes: { [paneId]: { sessionId: null, sessionState: "idle", exit: null } },
  };
}

async function birthWorkspace(): Promise<ReturnType<typeof useRuntimeStore>> {
  const ws = useWorkspacesStore();
  ws.launcher.workspace.value = "C:/ws";
  ws.launcher.runtimeId.value = "rid-1";
  await ws.launcher.initTabs([]);
  // initTabs([]) births the workspace with NO tabs; install one bash tab the
  // way the workspaces tests do (birth is real, tab seeding is direct).
  ws.runtimes[0].tabs.value = [bareTab("t1")];
  const runtime = useRuntimeStore();
  runtime.activeTabId = "t1";
  return runtime;
}

/** Mount Terminal on the active tab's active pane, with the pane in the
 *  given session state (the store owns sessionId from open time). */
async function mountTerminal(state: "starting" | "running") {
  const runtime = await birthWorkspace();
  const tab = runtime.tabs[0];
  const paneId = tab.activePaneId;
  tab.panes[paneId].sessionState = state;
  tab.panes[paneId].sessionId = "sid-1";
  if (state === "running") tab.sessionState = "running";
  const wrapper = mount(Terminal, {
    props: { tabId: tab.tabId, paneId },
    global: { plugins: [i18n] },
  });
  return { runtime, tab, paneId, wrapper };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  h.fitSize.cols = 118;
  h.fitSize.rows = 30;
  h.resizeSession.mockResolvedValue(undefined);
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Terminal PTY size convergence (B-05)", () => {
  it("F1: session becoming running immediately syncs the fitted size", async () => {
    vi.useFakeTimers();
    const { tab, paneId, wrapper } = await mountTerminal("starting");
    // Starting: fit runs xterm-side only — the backend entry would reject.
    expect(h.resizeSession).not.toHaveBeenCalled();

    tab.panes[paneId].sessionState = "running";
    await vi.advanceTimersByTimeAsync(0);

    expect(h.resizeSession).toHaveBeenCalledTimes(1);
    expect(h.resizeSession).toHaveBeenCalledWith("sid-1", 118, 30);
    wrapper.unmount();
  });

  it("F1: mounting onto an already-running pane syncs immediately", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledWith("sid-1", 118, 30);
    wrapper.unmount();
  });

  it("F5: the heal tick is a zero-IPC no-op once converged", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);
    // Three heal ticks later: same size, last send succeeded → no resend.
    await vi.advanceTimersByTimeAsync(6000);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("F2+F3: a failed resize is logged and retried by the heal tick", async () => {
    vi.useFakeTimers();
    h.resizeSession.mockRejectedValueOnce({ code: "AISC_ERR_SESSION_NOT_FOUND" });
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);
    // Observability: the failure lands on the shared timeline.
    expect(h.logUiEvent).toHaveBeenCalledWith(
      "terminal_resize",
      "error",
      "AISC_ERR_SESSION_NOT_FOUND",
    );
    // Heal tick retries; the retry succeeds and converges (no third call).
    await vi.advanceTimersByTimeAsync(2100);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("F4: a resize event follows immediately (leading) and only sends on change", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);

    // Layout changed (drag): the fake fit now proposes a narrower grid.
    h.fitSize.cols = 100;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(0);
    // Leading fire: the new size went out in the same tick — no waiting for
    // the drag to end (the old pure-trailing debounce froze during drags).
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    expect(h.resizeSession).toHaveBeenLastCalledWith("sid-1", 100, 30);

    // Trailing catch-up fires 150ms later but the size is already confirmed.
    await vi.advanceTimersByTimeAsync(200);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
