/**
 * O2 (opt-batch, D-11): "load earlier output" — the truncation corner chip is
 * a recovery button paging the on-disk spool backwards.
 *
 * Click path: session_read_spool(head-step..head) -> clear -> write the spool
 * page -> replay the full window -> consumed resets to the cursor (live
 * streaming continues at the tail). eof / a failed read disables the button.
 * xterm + addons are faked (jsdom has no canvas/RO); the writes/clears are
 * recorded for ordering assertions.
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
  writes: [] as Uint8Array[],
  cleared: 0,
  sessionReadSpool: vi.fn(),
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  resizeSession: vi.fn().mockResolvedValue(undefined),
  writeSession: vi.fn().mockResolvedValue(undefined),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 2, revision: 0, workspaces: [] }),
}));

vi.mock("../../../lib/ipc", () => ({
  resizeSession: h.resizeSession,
  writeSession: h.writeSession,
  sessionReadSpool: h.sessionReadSpool,
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
  runtimeStatus: vi.fn().mockResolvedValue({ snapshot: { state: "stopped" }, services: null }),
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
    write(d: unknown) {
      h.writes.push(d as Uint8Array);
    }
    writeln() {}
    onData() {}
    onSelectionChange() {}
    attachCustomKeyEventHandler() {}
    dispose() {}
    refresh() {}
    focus() {}
    clear() {
      h.cleared += 1;
    }
    getSelection() {
      return "";
    }
    paste() {}
  },
}));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
    proposeDimensions() {
      return { cols: 118, rows: 30 };
    }
    dispose() {}
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
    sessionId: "sid-1",
    sessionState: "running",
    exit: null,
    savedTabId: null,
    tree: { kind: "pane", paneId, sessionType: agent },
    activePaneId: paneId,
    panes: { [paneId]: { sessionId: "sid-1", sessionState: "running", exit: null } },
  };
}

/** Decoded concatenation of everything written to the terminal so far.
 * Writes arrive mixed: typed arrays (chunk path) and plain strings (the
 * in-stream truncation note / exit hints). */
function writtenText(): string {
  let out = "";
  for (const w of h.writes) {
    out += typeof w === "string" ? w : new TextDecoder().decode(w);
  }
  return out;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  h.writes.length = 0;
  h.cleared = 0;
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
});
afterEach(() => {
  vi.useRealTimers();
});

describe("load earlier output (O2, D-11)", () => {
  /** A running pane whose window holds only "window" (offset 6) — 6 raw
   * bytes were dropped ("early!"), the spool head anchor is 6. */
  async function mountTruncated() {
    const ws = useWorkspacesStore();
    ws.launcher.workspace.value = "C:/ws";
    ws.launcher.runtimeId.value = "rid-1";
    await ws.launcher.initTabs([]);
    const inst = ws.runtimes[0]!;
    const tab = bareTab("t1");
    inst.tabs.value = [tab];
    const runtime = useRuntimeStore();
    runtime.activeTabId = "t1";
    const paneId = tab.activePaneId;
    // Seed the window through the instance refs (the store's real shape).
    inst.paneStreams.value[paneId] = ["d2luZG93"]; // b64("window"), offset 6
    inst.streamCursor.value[paneId] = 1;
    inst.paneStreamMeta.value[paneId] = {
      truncated: true,
      truncatedBytes: 6,
      headOffset: 6,
    };
    const wrapper = mount(Terminal, {
      props: { tabId: "t1", paneId },
      global: { plugins: [i18n] },
    });
    return { runtime, wrapper, paneId };
  }

  it("renders the truncation chip as a load-earlier button while live", async () => {
    const { wrapper } = await mountTruncated();
    const btn = wrapper.find(".truncation-banner");
    expect(btn.exists()).toBe(true);
    expect(btn.text()).toContain("加载更早的输出");
    wrapper.unmount();
  });

  it("click pages the spool, rebuilds scrollback as [page|window], disables at eof", async () => {
    h.sessionReadSpool.mockResolvedValue({
      start: 0,
      length: 6,
      bytes: "ZWFybHkh", // b64("early!")
      eof: true,
    });
    const { wrapper } = await mountTruncated();
    const beforeText = writtenText(); // initial replay + in-stream note
    await wrapper.find(".truncation-banner").trigger("click");
    await Promise.resolve();

    // Paged [0, 6) of the raw stream from the window head anchor.
    expect(h.sessionReadSpool).toHaveBeenCalledWith("sid-1", 0, 6);
    // Scrollback rebuilt: clear, then the spool page, then the full window.
    expect(h.cleared).toBe(1);
    const rebuilt = writtenText().slice(beforeText.length);
    expect(rebuilt.startsWith("early!")).toBe(true);
    expect(rebuilt.endsWith("window")).toBe(true);
    // eof latched: the button reads "已到最早输出" and is disabled.
    const btn = wrapper.find(".truncation-banner");
    expect((btn.element as HTMLButtonElement).disabled).toBe(true);
    expect(btn.text()).toContain("已到最早输出");
    wrapper.unmount();
  });

  it("a failed read disables further attempts (spool degraded / entry gone)", async () => {
    h.sessionReadSpool.mockRejectedValue(new Error("spool degraded"));
    const { wrapper } = await mountTruncated();
    await wrapper.find(".truncation-banner").trigger("click");
    await Promise.resolve();
    const btn = wrapper.find(".truncation-banner");
    expect((btn.element as HTMLButtonElement).disabled).toBe(true);
    wrapper.unmount();
  });
});
