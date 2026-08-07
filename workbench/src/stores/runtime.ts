import { defineStore } from "pinia";
import { ref } from "vue";
import { open } from "@tauri-apps/plugin-dialog";
import type { CapabilityReport, WorkbenchError } from "../types";
import * as ipc from "../lib/ipc";

/** S1.4 minimal lifecycle: negotiate -> start runtime -> open bash session -> stop runtime. */
export type WorkbenchStatus =
  | "idle"
  | "negotiating"
  | "blocked"
  | "ready"
  | "starting"
  | "running"
  | "stopping"
  | "error";

export const useRuntimeStore = defineStore("runtime", () => {
  const capability = ref<CapabilityReport | null>(null);
  const status = ref<WorkbenchStatus>("idle");
  const error = ref<WorkbenchError | null>(null);

  const workspace = ref("");
  const runtimeId = ref("");
  const sessionId = ref("");
  const runtimeReady = ref(false);

  const canStart = () =>
    capability.value?.required_ok === true &&
    workspace.value.trim() !== "" &&
    status.value === "ready";

  async function negotiate() {
    status.value = "negotiating";
    try {
      const report = await ipc.negotiateCapabilities();
      capability.value = report;
      if (report.required_ok) {
        status.value = "ready";
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
      status.value = report.required_ok ? "ready" : "blocked";
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

  async function startBash() {
    if (!workspace.value.trim()) return;
    runtimeId.value = crypto.randomUUID();
    sessionId.value = "";
    status.value = "starting";
    error.value = null;
    try {
      const result = await ipc.startRuntime(workspace.value.trim(), runtimeId.value);
      runtimeReady.value = result.ready;
      // Terminal.vue watches sessionId and opens the bash session.
      sessionId.value = crypto.randomUUID();
      status.value = "running";
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
    }
  }

  function onSessionExited() {
    sessionId.value = "";
  }

  async function stopRuntime() {
    status.value = "stopping";
    try {
      if (sessionId.value) {
        try {
          await ipc.closeSession(sessionId.value);
        } catch {
          /* best-effort; session may already be gone */
        }
      }
      sessionId.value = "";
      if (runtimeId.value) {
        await ipc.stopRuntime(runtimeId.value);
      }
      runtimeId.value = "";
      runtimeReady.value = false;
      status.value = "ready";
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
    }
  }

  return {
    capability,
    status,
    error,
    workspace,
    runtimeId,
    sessionId,
    runtimeReady,
    canStart,
    negotiate,
    pickAndPinCli,
    pickWorkspace,
    startBash,
    onSessionExited,
    stopRuntime,
  };
});
