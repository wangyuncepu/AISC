/**
 * Settings store tests (Step 3 / A-G01-1): load applies the backend document,
 * save sends the full GUI patch and applies the outcome, dirty tracking never
 * conflates memory with disk, save failure is recoverable (values retained),
 * reset keeps aisc_cli_path (backend contract; frontend reloads defaults).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import type { SettingsDocument } from "../../types";
import { useSettingsStore } from "../settings";

const mockIpc = vi.hoisted(() => ({
  loadSettings: vi.fn(),
  saveSettings: vi.fn(),
  resetGuiSettings: vi.fn(),
  resolveLocale: vi.fn().mockResolvedValue("zh-CN"),
}));

vi.mock("../../lib/ipc", () => mockIpc);

const doc: SettingsDocument = {
  schemaVersion: 1,
  revision: 3,
  aiscCliPath: "C:\\aisc.exe",
  ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: [], default_tab_agent: "bash" },
  terminal: {
    font_family: "Cascadia Mono, Consolas, monospace",
    font_size: 14,
    line_height: 1.2,
    letter_spacing: 0,
    scrollback: 5000,
    renderer: "auto",
    smooth_scroll_duration: 100,
  },
  window: { remember_geometry: true, close_behavior: "quit", geometry: null },
  issues: [],
  corrupted: false,
  readOnly: false,
};

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mockIpc.loadSettings.mockResolvedValue(JSON.parse(JSON.stringify(doc)));
});

describe("load", () => {
  it("applies the backend document as the last-saved baseline", async () => {
    const s = useSettingsStore();
    await s.load();
    expect(s.loaded).toBe(true);
    expect(s.doc?.revision).toBe(3);
    expect(s.doc?.ui.language).toBe("auto");
    expect(s.dirty).toBe(false);
    expect(s.readOnly).toBe(false);
    expect(s.corrupted).toBe(false);
  });

  it("surfaces load failure without fabricating a document", async () => {
    mockIpc.loadSettings.mockRejectedValue({ message: "io error" });
    const s = useSettingsStore();
    await s.load();
    expect(s.loaded).toBe(false);
    expect(s.saveState).toBe("error");
    expect(s.error).toContain("io error");
  });
});

describe("patch / cancel (memory vs disk, A-G01-5)", () => {
  it("edits mark dirty; cancel reverts to the saved baseline", async () => {
    const s = useSettingsStore();
    await s.load();
    s.patch({ terminal: { ...doc.terminal, font_size: 20 } });
    expect(s.doc?.terminal.font_size).toBe(20);
    expect(s.dirty).toBe(true);
    s.cancel();
    expect(s.doc?.terminal.font_size).toBe(14);
    expect(s.dirty).toBe(false);
  });

  it("partial section patches merge, not replace", async () => {
    const s = useSettingsStore();
    await s.load();
    s.patch({ ui: { ...doc.ui, language: "en-US" } });
    expect(s.doc?.ui.language).toBe("en-US");
    expect(s.doc?.ui.font_scale).toBe(1.0); // untouched field survives
  });
});

describe("save", () => {
  it("sends the full GUI patch with the current revision and applies the outcome", async () => {
    mockIpc.saveSettings.mockResolvedValue({ revision: 4, issues: [] });
    const s = useSettingsStore();
    await s.load();
    s.patch({ terminal: { ...doc.terminal, scrollback: 20000 } });
    const outcome = await s.save();
    expect(outcome?.revision).toBe(4);
    expect(mockIpc.saveSettings).toHaveBeenCalledWith(3, {
      ui: doc.ui,
      terminal: expect.objectContaining({ scrollback: 20000 }),
      window: doc.window,
    });
    expect(s.doc?.revision).toBe(4);
    expect(s.dirty).toBe(false);
    expect(s.saveState).toBe("saved");
  });

  it("applies validation issues from the backend", async () => {
    mockIpc.saveSettings.mockResolvedValue({
      revision: 4,
      issues: [{ field: "terminal.font_size", reason: "非法" }],
    });
    const s = useSettingsStore();
    await s.load();
    s.patch({ terminal: { ...doc.terminal, font_size: 99 } });
    await s.save();
    expect(s.doc?.issues).toHaveLength(1);
    expect(s.doc?.issues[0].field).toBe("terminal.font_size");
  });

  it("failure is recoverable: error state, values retained, retry possible", async () => {
    mockIpc.saveSettings.mockRejectedValue({ message: "lock timeout" });
    const s = useSettingsStore();
    await s.load();
    s.patch({ ui: { ...doc.ui, language: "zh-CN" } });
    const outcome = await s.save();
    expect(outcome).toBeNull();
    expect(s.saveState).toBe("error");
    expect(s.error).toContain("lock timeout");
    expect(s.doc?.ui.language).toBe("zh-CN"); // memory not conflated with disk
    expect(s.dirty).toBe(true);
    // Retry succeeds.
    mockIpc.saveSettings.mockResolvedValue({ revision: 4, issues: [] });
    expect((await s.save())?.revision).toBe(4);
    expect(s.dirty).toBe(false);
  });
});

describe("reset (A-G01-4 isolation)", () => {
  it("resets via the backend then reloads defaults; pin/history untouched by contract", async () => {
    mockIpc.resetGuiSettings.mockResolvedValue({ revision: 5, issues: [] });
    const s = useSettingsStore();
    await s.load(); // before-each doc (revision 3)
    s.patch({ ui: { ...doc.ui, language: "zh-CN" }, terminal: { ...doc.terminal, font_size: 20 } });
    // After reset the backend serves fresh defaults; the store must not
    // hardcode them (single source of truth stays in Rust).
    const defaults = JSON.parse(JSON.stringify(doc));
    defaults.revision = 5;
    mockIpc.loadSettings.mockResolvedValue(defaults);
    const outcome = await s.reset();
    expect(outcome?.revision).toBe(5);
    expect(mockIpc.resetGuiSettings).toHaveBeenCalledWith(3);
    expect(s.doc?.ui.language).toBe("auto");
    expect(s.doc?.terminal.font_size).toBe(14);
    expect(s.doc?.aiscCliPath).toBe("C:\\aisc.exe"); // survives reset
    expect(s.dirty).toBe(false);
  });

  it("reset failure keeps the working copy", async () => {
    mockIpc.resetGuiSettings.mockRejectedValue({ message: "read-only" });
    const s = useSettingsStore();
    await s.load();
    s.patch({ ui: { ...doc.ui, theme: "dark" } });
    expect(await s.reset()).toBeNull();
    expect(s.saveState).toBe("error");
    expect(s.doc?.ui.theme).toBe("dark");
  });
});
