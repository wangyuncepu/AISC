/**
 * DoctorDialog (lifecycle-logging P3): the「最近日志」collapsed section —
 * renders the store's log tail as text lines and copies them via the
 * clipboard plugin. Data plane lives in the doctor store (F-A01); the
 * dialog only renders.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useDoctorStore } from "../../../stores/doctor";
import type { DoctorReport } from "../../../types";
import DoctorDialog from "../DoctorDialog.vue";

const mockIpc = vi.hoisted(() => ({
  runDoctor: vi.fn(),
  opTraces: vi.fn(),
  logsTail: vi.fn(),
  diagnosticBundle: vi.fn(),
}));
const mockClipboard = vi.hoisted(() => ({ writeText: vi.fn() }));

vi.mock("../../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn().mockResolvedValue(true),
  save: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-clipboard-manager", () => mockClipboard);

const report: DoctorReport = {
  checks: [
    { name: "docker-cli", status: "pass", message: "found", detail: null, hint: null },
  ],
  summary: { passed: 1, warnings: 0, failures: 0, skipped: 0 },
};

const LOGS = [
  { ts: "2026-08-20T05:00:00.123Z", level: "info", source: "app", event: "op",
    run_id: "11111111-2222-4333-8444-555555555555", phase: "network", outcome: "ok", duration_ms: 45 },
  { ts: "2026-08-20T05:00:00.456Z", level: "error", source: "cli", event: "cli_exit",
    command: "network subscription show", exit_code: 1, error_code: "AISC_ERR_X" },
];

async function mounted() {
  const store = useDoctorStore();
  store.status = "done";
  store.report = report;
  store.logs = LOGS as never;
  const tab = mount(DoctorDialog, { global: { plugins: [i18n] } });
  await flushPromises();
  return tab;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  // onMounted's loadLogs() refills the tail — keep the fixture flowing so
  // the store assignment in mounted() survives the refresh.
  mockIpc.logsTail.mockResolvedValue({ path: "x", lines: LOGS as never });
  mockIpc.opTraces.mockResolvedValue([]);
});

describe("DoctorDialog recent-log section (P3)", () => {
  it("renders the collapsed log section with one line per event", async () => {
    const tab = await mounted();
    const details = tab.find("details.logs");
    expect(details.exists()).toBe(true);
    const text = details.text();
    expect(text).toContain("最近日志");
    expect(text).toContain("op");
    expect(text).toContain("run=11111111-2222");
    expect(text).toContain("cli_exit");
    expect(text).toContain("error_code=AISC_ERR_X");
    // collapsed by default (no open attribute)
    expect(details.attributes("open")).toBeUndefined();
    tab.unmount();
  });

  it("hides the section when there are no events", async () => {
    mockIpc.logsTail.mockResolvedValue({ path: "x", lines: [] });
    const store = useDoctorStore();
    store.status = "done";
    store.report = report;
    store.logs = [];
    const tab = mount(DoctorDialog, { global: { plugins: [i18n] } });
    await flushPromises();
    expect(tab.find("details.logs").exists()).toBe(false);
    tab.unmount();
  });

  it("copies the rendered lines via the clipboard plugin", async () => {
    mockClipboard.writeText.mockResolvedValue(undefined);
    const tab = await mounted();
    await tab.find(".copy-logs").trigger("click");
    await flushPromises();
    expect(mockClipboard.writeText).toHaveBeenCalledTimes(1);
    const copied = mockClipboard.writeText.mock.calls[0]?.[0] as string;
    expect(copied).toContain("op");
    expect(copied).toContain("cli_exit");
    tab.unmount();
  });

  it("loads the tail through the store on mount (logs_tail(100))", async () => {
    await mounted();
    expect(mockIpc.logsTail).toHaveBeenCalledWith(100);
  });
});
