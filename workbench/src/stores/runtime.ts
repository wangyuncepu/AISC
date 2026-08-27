import { defineStore } from "pinia";
import { computed, ref, type Ref } from "vue";
import { open } from "@tauri-apps/plugin-dialog";
import type { CapabilityReport, WorkbenchError } from "../types";
import * as ipc from "../lib/ipc";
import { i18n } from "../i18n";
import { useWorkspacesStore } from "./workspaces";
import type { WorkspaceRuntime } from "./workspaceRuntime";

// IDEA-3 (3a): the sentinel ids + status domain live with the per-workspace
// state machine now; re-exported here so existing consumers keep their import
// paths (App.vue, TabBar.vue, tests).
export { CC_SWITCH_UI_TAB_ID, SETTINGS_TAB_ID, NETWORK_USAGE_TAB_ID } from "./workspaceRuntime";
export type { WorkbenchStatus } from "./workspaceRuntime";

/** Unwrap `Ref<V>` for the forwarding helpers below. */
type RefValue<T> = T extends Ref<infer V> ? V : never;

/**
 * IDEA-3 (3c): the runtime store is a FACADE over the workspaces layer
 * (`stores/workspaces.ts`). Everything workspace-shaped (status machine,
 * tabs, panes, streams, launch flow) lives in `createWorkspaceRuntime`
 * instances owned by the workspaces store; this facade forwards to the
 * ACTIVE one — switching workspace tabs re-targets every existing consumer
 * (TabBar, sidebar, title, terminals) with zero per-component changes.
 *
 * Forwarding semantics (the contract locked by `runtimeFacade.test.ts`):
 * - state keys are WRITABLE computeds — `s.tabs = [...]`, deep mutation and
 *   `watch(() => store.x)` all behave exactly as they did on a plain store;
 * - methods re-look up the active instance at CALL time, so an async caller
 *   can never reach a workspace that was switched away mid-flight;
 * - shell-owned keys (capability negotiation, shared history, exit gate)
 *   stay here / delegate to the workspaces store.
 */
export const useRuntimeStore = defineStore("runtime", () => {
  const ws = useWorkspacesStore();
  const inst = computed<WorkspaceRuntime>(() => ws.activeRuntime);

  // --- shell-owned: capability negotiation (app-level, one CLI pin) ---
  const capability = ref<CapabilityReport | null>(null);

  // --- forwarding helpers (see class comment for the semantics) ---

  function fwdRef<K extends keyof WorkspaceRuntime>(key: K) {
    type V = RefValue<WorkspaceRuntime[K]>;
    return computed<V>({
      get: () => (inst.value[key] as unknown as Ref<V>).value,
      set: (v) => {
        (inst.value[key] as unknown as Ref<V>).value = v;
      },
    });
  }

  function fwdFn<K extends keyof WorkspaceRuntime>(key: K): WorkspaceRuntime[K] {
    return ((...args: unknown[]) =>
      (inst.value[key] as (...a: unknown[]) => unknown)(...args)) as unknown as WorkspaceRuntime[K];
  }

  // --- shell-owned: negotiate + exit (write the ACTIVE instance) ---

  async function negotiate() {
    void ws.loadHistory(); // parallel, best-effort (02 §九)
    inst.value.status.value = "negotiating";
    try {
      const report = await ipc.negotiateCapabilities();
      capability.value = report;
      if (report.required_ok) {
        inst.value.status.value = "picker";
        inst.value.error.value = null;
      } else {
        inst.value.status.value = "blocked";
        inst.value.error.value = report.error;
      }
    } catch (e) {
      inst.value.status.value = "blocked";
      inst.value.error.value = e as WorkbenchError;
    }
  }

  async function pickAndPinCli() {
    const picked = await open({
      multiple: false,
      directory: false,
      title: i18n.global.t("runtime.pickCli"),
    });
    if (!picked || typeof picked !== "string") return;
    try {
      const report = await ipc.cliPin(picked);
      capability.value = report;
      inst.value.status.value = report.required_ok ? "picker" : "blocked";
      inst.value.error.value = report.required_ok ? null : report.error;
    } catch (e) {
      inst.value.status.value = "blocked";
      inst.value.error.value = e as WorkbenchError;
    }
  }

  /** Surface a shutdown/exit failure as a recoverable error view (03 §4.3). */
  function setExitError(message: string) {
    inst.value.error.value = {
      code: "WB_ERR_REAP_TIMEOUT",
      message,
      technical_detail: null,
      retryable: true,
      action: "retry",
    };
    inst.value.status.value = "error";
  }

  return {
    // shell-owned
    capability,
    negotiate,
    pickAndPinCli,
    setExitError,
    confirmExit: () => ws.confirmExit(),
    /** runtime-lifecycle-ux Stage 3 (02 §4): structured-shutdown runtime
     * targets for the App exit flow. */
    shutdownTargets: () => ws.shutdownTargets(),
    flushSave: () => ws.flushSave(),
    loadHistory: () => ws.loadHistory(),
    // IDEA-3 (3d): Settings is a WORKSPACE-layer sentinel now — forwarded
    // from the workspaces store (it survives workspace switches/closes).
    settingsTabOpen: computed({
      get: () => ws.settingsTabOpen,
      set: (v: boolean) => {
        ws.settingsTabOpen = v;
      },
    }),
    openSettingsTab: () => ws.openSettingsTab(),
    closeSettingsTab: () => ws.closeSettingsTab(),
    // IDEA-2 (2d): the「网络与用量」sentinel, forwarded like Settings.
    networkUsageTabOpen: computed({
      get: () => ws.networkUsageTabOpen,
      set: (v: boolean) => {
        ws.networkUsageTabOpen = v;
      },
    }),
    openNetworkUsageTab: () => ws.openNetworkUsageTab(),
    closeNetworkUsageTab: () => ws.closeNetworkUsageTab(),
    // shared history (workspaces-owned). Through the pinia proxy `ws.history`
    // is ALREADY the unwrapped value — no `.value` here, or everything reads
    // undefined. Value semantics match the original plain-ref store
    // (`s.history?.workspaces`, `s.historyRevision`).
    history: computed(() => ws.history),
    historyRevision: computed(() => ws.historyRevision),
    recentWorkspaces: computed(() => ws.recentWorkspaces),

    // instance state (writable computeds -> ACTIVE workspace)
    id: fwdRef("id"),
    status: fwdRef("status"),
    error: fwdRef("error"),
    workspace: fwdRef("workspace"),
    runtimeId: fwdRef("runtimeId"),
    runtimeReady: fwdRef("runtimeReady"),
    preflight: fwdRef("preflight"),
    launch: fwdRef("launch"),
    showAdvanced: fwdRef("showAdvanced"),
    startElapsedMs: fwdRef("startElapsedMs"),
    cancelInspect: fwdRef("cancelInspect"),
    buildStatus: fwdRef("buildStatus"),
    buildLog: fwdRef("buildLog"),
    buildProgress: fwdRef("buildProgress"),
    buildLogPath: fwdRef("buildLogPath"),
    buildTag: fwdRef("buildTag"),
    buildError: fwdRef("buildError"),
    buildStartedAt: fwdRef("buildStartedAt"),
    buildFinishedAt: fwdRef("buildFinishedAt"),
    buildDurationMs: fwdRef("buildDurationMs"),
    tabs: fwdRef("tabs"),
    activeTabId: fwdRef("activeTabId"),
    ccSwitchUiTabOpen: fwdRef("ccSwitchUiTabOpen"),
    runtimeState: fwdRef("runtimeState"),
    runtimeSnapshot: fwdRef("runtimeSnapshot"),
    conflicts: fwdRef("conflicts"),
    conflictError: fwdRef("conflictError"),
    freshness: fwdRef("freshness"),
    inspectInFlight: fwdRef("inspectInFlight"),
    providerStatuses: fwdRef("providerStatuses"),
    providerError: fwdRef("providerError"),
    providerInFlight: fwdRef("providerInFlight"),
    webServices: fwdRef("webServices"),
    webServicesError: fwdRef("webServicesError"),
    webServicesInFlight: fwdRef("webServicesInFlight"),
    paneStreams: fwdRef("paneStreams"),
    paneStreamMeta: fwdRef("paneStreamMeta"),
    streamCursor: fwdRef("streamCursor"),
    userRefreshInFlight: fwdRef("userRefreshInFlight"),
    dockerStarting: fwdRef("dockerStarting"),
    dockerStartedAt: fwdRef("dockerStartedAt"),

    // instance computed (read-only forward)
    reconcile: fwdRef("reconcile"),

    // instance methods (call-time re-lookup -> ACTIVE workspace)
    buildPatch: fwdFn("buildPatch"),
    pickWorkspace: fwdFn("pickWorkspace"),
    backToPicker: fwdFn("backToPicker"),
    startBuild: fwdFn("startBuild"),
    cancelBuild: fwdFn("cancelBuild"),
    revealBuildLog: fwdFn("revealBuildLog"),
    backToSummaryFromBuild: fwdFn("backToSummaryFromBuild"),
    runPreflight: fwdFn("runPreflight"),
    recomputePreflightNeeded: fwdFn("recomputePreflightNeeded"),
    startDockerAndRepreflight: fwdFn("startDockerAndRepreflight"),
    startFromSummary: fwdFn("startFromSummary"),
    cancelStart: fwdFn("cancelStart"),
    keepCancelledRuntime: fwdFn("keepCancelledRuntime"),
    stopCancelledRuntime: fwdFn("stopCancelledRuntime"),
    stopRuntime: fwdFn("stopRuntime"),
    initTabs: fwdFn("initTabs"),
    openTab: fwdFn("openTab"),
    splitTabPane: fwdFn("splitTabPane"),
    closePane: fwdFn("closePane"),
    setActivePane: fwdFn("setActivePane"),
    navigatePane: fwdFn("navigatePane"),
    setSplitRatio: fwdFn("setSplitRatio"),
    activateTab: fwdFn("activateTab"),
    closeTab: fwdFn("closeTab"),
    reopenTab: fwdFn("reopenTab"),
    createTab: fwdFn("createTab"),
    removeTab: fwdFn("removeTab"),
    openCcSwitch: fwdFn("openCcSwitch"),
    onTabOpenOk: fwdFn("onTabOpenOk"),
    onTabOpenFail: fwdFn("onTabOpenFail"),
    onTabSessionExit: fwdFn("onTabSessionExit"),
    applyRuntimeSnapshot: fwdFn("applyRuntimeSnapshot"),
    markStale: fwdFn("markStale"),
    refreshRuntime: fwdFn("refreshRuntime"),
    loadProviderStatus: fwdFn("loadProviderStatus"),
    clearProviderStatuses: fwdFn("clearProviderStatuses"),
    refreshWebServices: fwdFn("refreshWebServices"),
    openWebService: fwdFn("openWebService"),
    clearWebServices: fwdFn("clearWebServices"),
    selectRecentWorkspace: fwdFn("selectRecentWorkspace"),
    loadConflicts: fwdFn("loadConflicts"),
    retryFromConflict: fwdFn("retryFromConflict"),
    openCcSwitchUiTab: fwdFn("openCcSwitchUiTab"),
    closeCcSwitchUiTab: fwdFn("closeCcSwitchUiTab"),
    logTerminalResizeError: fwdFn("logTerminalResizeError"),
    dispose: fwdFn("dispose"),
  };
});
