/**
 * One-click diagnosis store (G-13, Step 12; 02 §五 F-4, A-G13-3).
 *
 * Standalone: opening/closing the diagnosis never touches the runtime/settings
 * stores (A-G13-3 "返回/关闭诊断不改变 startup state"). All entry points
 * (blocked / error / ready sidebar) drive the SAME `run_doctor` command through
 * `run()`, which is guarded so an in-flight run cannot be started twice.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as ipc from "../lib/ipc";
import type { DoctorReport, OpTrace, WorkbenchError } from "../types";

export type DoctorRunState = "idle" | "running" | "done" | "error";

export const useDoctorStore = defineStore("doctor", () => {
  /** Dialog visibility (owned here so blocked/error/ready views share it). */
  const open = ref(false);
  const status = ref<DoctorRunState>("idle");
  const report = ref<DoctorReport | null>(null);
  const error = ref<WorkbenchError | null>(null);
  /** Stage 6 (REL-01): recent operation traces (Doctor dialog dev layer). */
  const traces = ref<OpTrace[]>([]);

  const running = computed(() => status.value === "running");
  /** Non-zero failed checks / any warning - drives the summary styling. */
  const hasFailures = computed(() => (report.value?.summary.failures ?? 0) > 0);
  const hasWarnings = computed(() => (report.value?.summary.warnings ?? 0) > 0);

  /** Run `aisc doctor --format json`. A-G13-3: never starts a second doctor
   * while one is in flight; repeated clicks are no-ops. */
  async function run(): Promise<void> {
    if (status.value === "running") return;
    status.value = "running";
    error.value = null;
    report.value = null;
    try {
      report.value = await ipc.runDoctor();
      status.value = "done";
    } catch (e) {
      error.value = (e as WorkbenchError) ?? {
        code: "WB_ERR_UNKNOWN",
        message: String(e),
        technical_detail: null,
        retryable: true,
        action: "retry",
      };
      status.value = "error";
    }
  }

  /** Open the dialog and start a fresh diagnosis. */
  function openDialog(): void {
    open.value = true;
    void run();
  }

  /** Close the dialog. Does not alter startup state (A-G13-3). */
  function closeDialog(): void {
    open.value = false;
  }

  /** Stage 6 (REL-01): refresh the recent-operation trace ring. */
  async function loadTraces(): Promise<void> {
    traces.value = await ipc.opTraces().catch(() => []);
  }

  /** Stage 6 (REL-01): export the redacted diagnostic bundle to `path`.
   *  Returns the final path (null on failure); the UI builds the message. */
  async function exportDiagnostic(path: string): Promise<string | null> {
    try {
      const bundle = await ipc.diagnosticBundle(path);
      return bundle.path;
    } catch {
      return null;
    }
  }

  return {
    open,
    status,
    report,
    error,
    traces,
    running,
    hasFailures,
    hasWarnings,
    run,
    openDialog,
    closeDialog,
    loadTraces,
    exportDiagnostic,
  };
});
