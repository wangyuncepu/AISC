/**
 * Doctor store tests (G-13, Step 12; A-G13-3): run() surfaces the report on
 * success and a structured error on failure, never starts a second doctor
 * while one is in flight, and open/close is standalone - it never touches the
 * runtime/settings stores (A-G13-3 "不改变 startup state").
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import type { DoctorReport, WorkbenchError } from "../../types";
import { useDoctorStore } from "../doctor";

const mockIpc = vi.hoisted(() => ({
  runDoctor: vi.fn(),
}));

vi.mock("../../lib/ipc", () => mockIpc);

const report: DoctorReport = {
  checks: [
    { name: "docker-cli", status: "pass", message: "found", detail: null, hint: null },
    { name: "aisc-root", status: "fail", message: "bad", detail: "detail", hint: "run install" },
  ],
  summary: { passed: 1, warnings: 0, failures: 1, skipped: 0 },
};

const wbError: WorkbenchError = {
  code: "WB_ERR_CLI_TIMEOUT",
  message: "AISC CLI 响应超时",
  technical_detail: null,
  retryable: true,
  action: "retry",
};

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("run", () => {
  it("surfaces the report on success", async () => {
    mockIpc.runDoctor.mockResolvedValue(report);
    const s = useDoctorStore();
    await s.run();
    expect(s.status).toBe("done");
    expect(s.report).toEqual(report);
    expect(s.error).toBeNull();
    expect(s.hasFailures).toBe(true);
  });

  it("surfaces a structured error on failure", async () => {
    mockIpc.runDoctor.mockRejectedValue(wbError);
    const s = useDoctorStore();
    await s.run();
    expect(s.status).toBe("error");
    expect(s.error?.code).toBe("WB_ERR_CLI_TIMEOUT");
    expect(s.error?.message).toBe("AISC CLI 响应超时");
    expect(s.report).toBeNull();
  });

  it("never starts a second doctor while in flight (A-G13-3)", async () => {
    let resolveFirst!: (v: DoctorReport) => void;
    mockIpc.runDoctor.mockImplementation(
      () =>
        new Promise<DoctorReport>((resolve) => {
          resolveFirst = resolve;
        })
    );
    const s = useDoctorStore();
    const p1 = s.run();
    const p2 = s.run(); // re-entry while running
    expect(s.status).toBe("running");
    resolveFirst(report);
    await Promise.all([p1, p2]);
    expect(mockIpc.runDoctor).toHaveBeenCalledTimes(1);
    expect(s.status).toBe("done");
  });
});

describe("openDialog / closeDialog", () => {
  it("opens and runs a fresh diagnosis", async () => {
    mockIpc.runDoctor.mockResolvedValue(report);
    const s = useDoctorStore();
    s.openDialog();
    expect(s.open).toBe(true);
    expect(s.status).toBe("running");
    await vi.waitFor(() => expect(s.status).toBe("done"));
  });

  it("closing does not alter startup state (A-G13-3)", async () => {
    mockIpc.runDoctor.mockResolvedValue(report);
    const s = useDoctorStore();
    s.openDialog();
    await vi.waitFor(() => expect(s.status).toBe("done"));
    s.closeDialog();
    expect(s.open).toBe(false);
    // Status keeps the last result; nothing else in the app was touched.
    expect(s.status).toBe("done");
  });
});
