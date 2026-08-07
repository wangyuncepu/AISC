import { defineStore } from "pinia";
import { ref } from "vue";
import { open } from "@tauri-apps/plugin-dialog";
import type {
  CapabilityReport,
  LaunchAgent,
  LaunchConfig,
  PreflightReport,
  RuntimeSnapshot,
  WorkbenchError,
} from "../types";
import * as ipc from "../lib/ipc";

/** S2.1.a startup state machine (02-startup-flow.md §三). */
export type WorkbenchStatus =
  | "idle"
  | "negotiating"
  | "blocked"
  | "picker"
  | "preflight"
  | "summary"
  | "starting"
  | "cancelled"
  | "ready"
  | "error";

const DEFAULT_LAUNCH: LaunchConfig = {
  agent: "claude",
  image: "super-claude:latest",
  network: "direct",
  scope: "project",
};

function uuid(): string {
  return crypto.randomUUID();
}

export const useRuntimeStore = defineStore("runtime", () => {
  const capability = ref<CapabilityReport | null>(null);
  const status = ref<WorkbenchStatus>("idle");
  const error = ref<WorkbenchError | null>(null);

  const workspace = ref("");
  const runtimeId = ref("");
  const sessionId = ref("");
  const runtimeReady = ref(false);

  const preflight = ref<PreflightReport | null>(null);
  const launch = ref<LaunchConfig>({ ...DEFAULT_LAUNCH });
  const showAdvanced = ref(false);
  const startElapsedMs = ref(0);
  const cancelInspect = ref<RuntimeSnapshot | null>(null);

  let startTimer: number | null = null;

  async function negotiate() {
    status.value = "negotiating";
    try {
      const report = await ipc.negotiateCapabilities();
      capability.value = report;
      if (report.required_ok) {
        status.value = "picker";
        error.value = null;
      } else {
        status.value = "blocked";
        error.value = report.error;
      }
    } catch (e) {
      status.value = "blocked";
      error.value = e as WorkbenchError;
    }
  }

  async function pickAndPinCli() {
    const picked = await open({
      multiple: false,
      directory: false,
      title: "选择 AISC CLI 可执行文件",
    });
    if (!picked || typeof picked !== "string") return;
    try {
      const report = await ipc.cliPin(picked);
      capability.value = report;
      status.value = report.required_ok ? "picker" : "blocked";
      error.value = report.required_ok ? null : report.error;
    } catch (e) {
      status.value = "blocked";
      error.value = e as WorkbenchError;
    }
  }

  async function pickWorkspace() {
    const picked = await open({ directory: true, multiple: false, title: "选择工作区目录" });
    if (typeof picked === "string") workspace.value = picked;
  }

  function backToPicker() {
    preflight.value = null;
    runtimeId.value = "";
    status.value = "picker";
  }

  async function runPreflight() {
    if (!workspace.value.trim()) return;
    if (!runtimeId.value) runtimeId.value = uuid();
    status.value = "preflight";
    error.value = null;
    try {
      const report = await ipc.runtimePreflight(
        workspace.value.trim(),
        runtimeId.value,
        launch.value.image,
        launch.value.network,
        launch.value.scope
      );
      preflight.value = report;
      status.value = "summary";
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
    }
  }

  function recomputePreflightNeeded() {
    // After changing launch config (image/network/scope), the old preflight is stale.
    preflight.value = null;
    status.value = "preflight";
    void runPreflight();
  }

  function startTimerTick() {
    startElapsedMs.value = 0;
    if (startTimer !== null) window.clearInterval(startTimer);
    const begun = Date.now();
    startTimer = window.setInterval(() => {
      startElapsedMs.value = Date.now() - begun;
    }, 200);
  }

  function stopTimer() {
    if (startTimer !== null) {
      window.clearInterval(startTimer);
      startTimer = null;
    }
  }

  async function openSessionForCurrent(agent: LaunchAgent) {
    sessionId.value = uuid();
    status.value = "ready";
    // Terminal.vue watches sessionId and opens the session with this agent.
    void agent; // agent consumed by Terminal via store.launch.agent
  }

  async function startFromSummary() {
    const report = preflight.value;
    if (!report) return;
    error.value = null;
    cancelInspect.value = null;
    startTimerTick();
    try {
      if (report.recommended_action === "start") {
        status.value = "starting";
        await ipc.startRuntime(workspace.value.trim(), runtimeId.value);
      } else if (report.recommended_action === "reuse" && report.matching_runtime_id) {
        runtimeId.value = report.matching_runtime_id;
        status.value = "starting";
      } else if (report.recommended_action === "restart" && report.matching_runtime_id) {
        runtimeId.value = report.matching_runtime_id;
        status.value = "starting";
        await ipc.runtimeRestart(runtimeId.value);
      } else {
        // resolve_conflict or missing matching_runtime_id
        stopTimer();
        status.value = "error";
        error.value = {
          code: "AISC_ERR_RUNTIME_CONFLICT",
          message: "工作区已有不兼容 Runtime，需先处理冲突",
          technical_detail: `recommended_action=${report.recommended_action}`,
          retryable: false,
          action: "none",
        };
        return;
      }
      stopTimer();
      runtimeReady.value = true;
      await openSessionForCurrent(launch.value.agent);
    } catch (e) {
      stopTimer();
      const err = e as WorkbenchError;
      if (err?.code === "WB_ERR_CLI_CANCELLED") {
        await handleCancelledStart();
      } else {
        status.value = "error";
        error.value = err;
      }
    }
  }

  async function handleCancelledStart() {
    // 02 §八: cancel -> inspect -> report real state + keep/stop.
    try {
      const snap = await ipc.runtimeInspect(runtimeId.value);
      cancelInspect.value = snap;
    } catch {
      cancelInspect.value = null;
    }
    status.value = "cancelled";
  }

  async function cancelStart() {
    try {
      await ipc.cancelRuntimeStart();
    } catch {
      /* swallow; startFromSummary will resolve with cancelled */
    }
  }

  async function keepCancelledRuntime() {
    // Keep the runtime, return to summary (it will show as reuse next preflight).
    cancelInspect.value = null;
    preflight.value = null;
    status.value = "preflight";
    void runPreflight();
  }

  async function stopCancelledRuntime() {
    if (!runtimeId.value) return;
    try {
      await ipc.stopRuntime(runtimeId.value);
    } catch {
      /* best-effort */
    }
    cancelInspect.value = null;
    runtimeId.value = "";
    preflight.value = null;
    status.value = "picker";
  }

  function onSessionExited() {
    sessionId.value = "";
  }

  async function stopRuntime() {
    status.value = "starting"; // reuse as a "stopping" indicator visually
    try {
      if (sessionId.value) {
        try {
          await ipc.closeSession(sessionId.value);
        } catch {
          /* best-effort */
        }
      }
      sessionId.value = "";
      if (runtimeId.value) {
        await ipc.stopRuntime(runtimeId.value);
      }
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
      return;
    }
    runtimeId.value = "";
    runtimeReady.value = false;
    preflight.value = null;
    status.value = "picker";
  }

  return {
    capability,
    status,
    error,
    workspace,
    runtimeId,
    sessionId,
    runtimeReady,
    preflight,
    launch,
    showAdvanced,
    startElapsedMs,
    cancelInspect,
    negotiate,
    pickAndPinCli,
    pickWorkspace,
    backToPicker,
    runPreflight,
    recomputePreflightNeeded,
    startFromSummary,
    cancelStart,
    keepCancelledRuntime,
    stopCancelledRuntime,
    onSessionExited,
    stopRuntime,
  };
});
