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
import { nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore } from "../../../stores/workspaces";
import { useRuntimeStore } from "../../../stores/runtime";
import type { LaunchAgent, Tab } from "../../../types";
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
    resize(cols: number, rows: number) {
      this.cols = cols;
      this.rows = rows;
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

function bareTab(id: string, agent: LaunchAgent = "bash"): Tab {
  const paneId = id;
  return {
    tabId: id,
    agent,
    title: agent,
    sessionId: null,
    sessionState: "idle",
    exit: null,
    savedTabId: null,
    tree: { kind: "pane", paneId, sessionType: agent },
    activePaneId: paneId,
    panes: { [paneId]: { sessionId: null, sessionState: "idle", exit: null } },
  };
}

async function birthWorkspace(agent: LaunchAgent = "bash"): Promise<ReturnType<typeof useRuntimeStore>> {
  const ws = useWorkspacesStore();
  ws.launcher.workspace.value = "C:/ws";
  ws.launcher.runtimeId.value = "rid-1";
  await ws.launcher.initTabs([]);
  // initTabs([]) births the workspace with NO tabs; install one tab the
  // way the workspaces tests do (birth is real, tab seeding is direct).
  ws.runtimes[0].tabs.value = [bareTab("t1", agent)];
  const runtime = useRuntimeStore();
  runtime.activeTabId = "t1";
  return runtime;
}

/** Mount Terminal on the active tab's active pane, with the pane in the
 *  given session state (the store owns sessionId from open time). */
async function mountTerminal(state: "starting" | "running", agent: LaunchAgent = "bash") {
  const runtime = await birthWorkspace(agent);
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

  it("F4: resize events settle once after 150ms of quiet (no mid-burst steps)", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1); // initial running-sync

    // Layout changed (drag / restore animation burst): every event resets
    // the settle timer — nothing fires mid-burst (each intermediate step
    // used to reflow the whole scrollback and flicker, 手测三轮).
    h.fitSize.cols = 100;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(100);
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(100);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);

    // 150ms of quiet → ONE settle fire with the resting size.
    await vi.advanceTimersByTimeAsync(200);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    expect(h.resizeSession).toHaveBeenLastCalledWith("sid-1", 100, 30);
    wrapper.unmount();
  });

  it("narrow-TUI guard: both grids hold at the floor; widening forces a repaint send", async () => {
    vi.useFakeTimers();
    h.fitSize.cols = 40;
    const { wrapper } = await mountTerminal("running", "claude");
    await vi.advanceTimersByTimeAsync(0);
    const overlay = wrapper.find('[data-testid="narrow-tui-overlay"]');
    expect(overlay.exists()).toBe(true);
    expect(overlay.text()).toContain("claude");
    // Floor: xterm AND the PTY hold at the readable minimum (the TUI never
    // sees 40 cols, and its 60-col output is not shredded by a 40-col xterm).
    expect(h.resizeSession).toHaveBeenCalledTimes(1);
    expect(h.resizeSession).toHaveBeenLastCalledWith("sid-1", 60, 30);

    // Widen: the grid leaves the floor → a DIFFERENT size must be sent
    // (same-size would be idempotently skipped and the TUI would never get
    // its WINCH repaint — 手测四轮) → overlay lifts.
    h.fitSize.cols = 118;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(200);
    expect(wrapper.find('[data-testid="narrow-tui-overlay"]').exists()).toBe(false);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    expect(h.resizeSession).toHaveBeenLastCalledWith("sid-1", 118, 30);
    wrapper.unmount();
  });

  it("concurrent resizes serialize: the queued LATEST size lands after the in-flight one", async () => {
    // 手测九轮回归: show-sync and a settle raced, both resize_session
    // invokes landed and the FILE ended at the OLDER size while the
    // frontend recorded the newer one — a permanent, unhealed mismatch.
    vi.useFakeTimers();
    let release1!: (v: undefined) => void;
    h.resizeSession.mockImplementationOnce(
      () => new Promise<void>((res) => { release1 = res; })
    );
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1); // initial sync in flight

    // A second size change while the first is still in flight: queued only.
    h.fitSize.cols = 100;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(200);
    expect(h.resizeSession).toHaveBeenCalledTimes(1);

    release1(undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(2);
    expect(h.resizeSession).toHaveBeenLastCalledWith("sid-1", 100, 30);
    wrapper.unmount();
  });

  it("narrow-TUI guard: bash wraps fine and never shows the hint", async () => {
    vi.useFakeTimers();
    h.fitSize.cols = 40;
    const { wrapper } = await mountTerminal("running", "bash");
    await vi.advanceTimersByTimeAsync(0);
    expect(wrapper.find('[data-testid="narrow-tui-overlay"]').exists()).toBe(false);
    wrapper.unmount();
  });
});

/** Review P0/P1 (terminal-render-review.md 方案 D): the veil must be a
 *  DECLARATIVE node (scoped CSS applies), pinned before term.resize(), and
 *  stale async releases must not expose a newer hold. */
describe("resize veil (review P0/P1)", () => {
  it("appears on a grid change and clears after confirm+grace", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);

    h.fitSize.cols = 100;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(200); // settle fit + send + ok
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(true);

    // ok landed; grace (160ms) + fade/instant release clears it.
    await vi.advanceTimersByTimeAsync(600);
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("pins on tab show BEFORE the show doResize runs (stale-grid frame covered)", async () => {
    vi.useFakeTimers();
    const { runtime, wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);

    // Hide the tab, then re-show with a DIFFERENT fitted size waiting: the
    // watcher pins pre-paint; doResize("show") sits in a setTimeout(0)
    // that fake timers have NOT advanced yet.
    h.fitSize.cols = 100;
    runtime.activeTabId = "other";
    await vi.advanceTimersByTimeAsync(10);
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(false);

    runtime.activeTabId = "t1";
    await nextTick();
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(true);
    // The show fit (grid changes 118→100) keeps it held until ok+grace.
    await vi.advanceTimersByTimeAsync(0);
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("a stale ok-grace cannot release a newer hold (review P1)", async () => {
    vi.useFakeTimers();
    let releaseA!: (v: undefined) => void;
    h.resizeSession.mockImplementationOnce(
      () => new Promise<void>((res) => { releaseA = res; })
    );
    const { wrapper } = await mountTerminal("running");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(1); // A (mount sync) in flight

    // New size while A is in flight: the settle PINS a newer veil (gen2)
    // and queues send B behind A.
    h.fitSize.cols = 100;
    window.dispatchEvent(new Event("resize"));
    await vi.advanceTimersByTimeAsync(200);
    releaseA(undefined); // A lands: its ok-grace carries A's send-time gen
    await vi.advanceTimersByTimeAsync(0);
    expect(h.resizeSession).toHaveBeenCalledTimes(2); // B sent after A

    // A's grace window elapses — it must NOT expose B's veil.
    await vi.advanceTimersByTimeAsync(170);
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(true);

    // B's own ok-grace elapses — now the veil clears.
    await vi.advanceTimersByTimeAsync(600);
    expect(wrapper.find('[data-testid="resize-veil"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
