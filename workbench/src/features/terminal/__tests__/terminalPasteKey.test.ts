/**
 * S8f (2026-08-28 VM retest, feedback #6): Ctrl+Shift+V pasted the clipboard
 * TWICE. xterm calls attachCustomKeyEventHandler for BOTH keydown and keyup,
 * and the handler is press-only — the keyup of "v" still carries ctrl/shift
 * (V is usually released first), so doPaste ran a second time. The fix filters
 * on e.type; this test pins the filter at the handler boundary.
 *
 * xterm is faked (jsdom has no canvas) with a mock that CAPTURES the custom
 * key handler, mirroring terminalResize.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspacesStore } from "../../../stores/workspaces";
import { useRuntimeStore } from "../../../stores/runtime";
import type { LaunchAgent, Tab } from "../../../types";
import Terminal from "../Terminal.vue";

const h = vi.hoisted(() => ({
  writeSession: vi.fn().mockResolvedValue(undefined),
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  readText: vi.fn().mockResolvedValue("pasted-content"),
  writeText: vi.fn().mockResolvedValue(undefined),
  keyHandler: null as ((e: KeyboardEvent) => boolean) | null,
  hasSelection: false,
}));

vi.mock("../../../lib/ipc", () => ({
  resizeSession: vi.fn().mockResolvedValue(undefined),
  writeSession: h.writeSession,
  logUiEvent: h.logUiEvent,
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 1, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  openSession: vi.fn().mockResolvedValue({}),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  stopRuntime: vi.fn().mockResolvedValue({ state: "stopped" }),
  runtimeInspect: vi.fn().mockResolvedValue({ state: "stopped" }),
  runtimeStatus: vi.fn().mockResolvedValue({ snapshot: { state: "stopped" }, services: null }),
}));

vi.mock("@tauri-apps/plugin-clipboard-manager", () => ({
  readText: h.readText,
  writeText: h.writeText,
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
    resize() {}
    open() {}
    write(_d: unknown, cb?: () => void) {
      cb?.();
    }
    writeln(_d: unknown, cb?: () => void) {
      cb?.();
    }
    onData() {}
    onSelectionChange() {}
    attachCustomKeyEventHandler(fn: (e: KeyboardEvent) => boolean) {
      h.keyHandler = fn;
    }
    dispose() {}
    refresh() {}
    focus() {}
    clear() {}
    getSelection() {
      return h.hasSelection ? "selected-text" : "";
    }
    hasSelection() {
      return h.hasSelection;
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
    fit() {}
    proposeDimensions() {
      return { cols: 118, rows: 30 };
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

async function mountRunningTerminal() {
  const ws = useWorkspacesStore();
  ws.launcher.workspace.value = "C:/ws";
  ws.launcher.runtimeId.value = "rid-1";
  await ws.launcher.initTabs([]);
  ws.runtimes[0].tabs.value = [bareTab("t1", "bash")];
  const runtime = useRuntimeStore();
  runtime.activeTabId = "t1";
  const tab = runtime.tabs[0];
  const paneId = tab.activePaneId;
  tab.panes[paneId].sessionState = "running";
  tab.panes[paneId].sessionId = "sid-1";
  tab.sessionState = "running";
  const wrapper = mount(Terminal, {
    props: { tabId: tab.tabId, paneId },
    global: { plugins: [i18n] },
  });
  return wrapper;
}

/** Synthetic key event at the handler boundary (no real DOM event needed). */
function keyEvent(type: "keydown" | "keyup", key: string, mods: { ctrl?: boolean; shift?: boolean } = {}): KeyboardEvent {
  return {
    type,
    key,
    ctrlKey: mods.ctrl ?? false,
    metaKey: false,
    shiftKey: mods.shift ?? false,
    altKey: false,
    preventDefault: vi.fn(),
  } as unknown as KeyboardEvent;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  h.keyHandler = null;
  h.hasSelection = false;
  h.readText.mockResolvedValue("pasted-content");
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Terminal custom key handler fires on keydown only (S8f)", () => {
  it("Ctrl+Shift+V pastes exactly once across a keydown+keyup pair", async () => {
    vi.useFakeTimers();
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.keyHandler).toBeTypeOf("function");
    const handler = h.keyHandler!;

    // keydown: swallow (returns false) and paste.
    expect(handler(keyEvent("keydown", "v", { ctrl: true, shift: true }))).toBe(false);
    expect(h.readText).toHaveBeenCalledTimes(1);
    // keyup: the V release still carries ctrl+shift — must NOT paste again.
    expect(handler(keyEvent("keyup", "v", { ctrl: true, shift: true }))).toBe(true);
    expect(h.readText).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("Ctrl+Shift+C / Ctrl+F also ignore their keyup (idempotent actions hid this)", async () => {
    vi.useFakeTimers();
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    const handler = h.keyHandler!;

    expect(handler(keyEvent("keyup", "c", { ctrl: true, shift: true }))).toBe(true);
    expect(handler(keyEvent("keydown", "c", { ctrl: true, shift: true }))).toBe(false);
    // Empty selection → doCopy is a no-op; writeText must stay untouched.
    expect(h.writeText).not.toHaveBeenCalled();

    expect(handler(keyEvent("keyup", "f", { ctrl: true }))).toBe(true);
    expect(handler(keyEvent("keydown", "f", { ctrl: true }))).toBe(false);
    wrapper.unmount();
  });

  it("plain keys still reach the PTY (handler returns true)", async () => {
    vi.useFakeTimers();
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    const handler = h.keyHandler!;

    expect(handler(keyEvent("keydown", "a"))).toBe(true);
    expect(handler(keyEvent("keyup", "a"))).toBe(true);
    expect(h.readText).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  // PP r8 (user request): bare Ctrl+C/V take over copy/paste — Windows
  // Terminal semantics.
  it("bare Ctrl+C with a selection copies (never reaches the PTY)", async () => {
    vi.useFakeTimers();
    h.hasSelection = true;
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    const handler = h.keyHandler!;

    expect(handler(keyEvent("keydown", "c", { ctrl: true }))).toBe(false);
    await Promise.resolve();
    expect(h.writeText).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("bare Ctrl+C WITHOUT a selection still reaches the PTY (SIGINT)", async () => {
    vi.useFakeTimers();
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    const handler = h.keyHandler!;

    expect(handler(keyEvent("keydown", "c", { ctrl: true }))).toBe(true);
    expect(h.writeText).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("bare Ctrl+V always pastes (the literal ^V echo is gone)", async () => {
    vi.useFakeTimers();
    const wrapper = await mountRunningTerminal();
    await vi.advanceTimersByTimeAsync(0);
    const handler = h.keyHandler!;

    expect(handler(keyEvent("keydown", "v", { ctrl: true }))).toBe(false);
    await Promise.resolve();
    expect(h.readText).toHaveBeenCalledTimes(1);
    // The keyup must not paste twice (S8f class of bug).
    expect(handler(keyEvent("keyup", "v", { ctrl: true }))).toBe(true);
    expect(h.readText).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
});
