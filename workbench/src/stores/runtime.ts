import { defineStore } from "pinia";
import { ref } from "vue";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import { Channel } from "@tauri-apps/api/core";
import type {
  BuildEvent,
  BuildStatus,
  CapabilityReport,
  Freshness,
  LaunchAgent,
  LaunchConfig,
  PreflightReport,
  RuntimeSnapshot,
  RuntimeState,
  Tab,
  TabExit,
  TabSessionState,
  WorkbenchError,
} from "../types";
import * as ipc from "../lib/ipc";

/** S2.1.a/b startup state machine (02-startup-flow.md §三). S2.2.b adds `conflict`. */
export type WorkbenchStatus =
  | "idle"
  | "negotiating"
  | "blocked"
  | "picker"
  | "preflight"
  | "summary"
  | "starting"
  | "stopping"
  | "building"
  | "cancelled"
  | "conflict"
  | "ready"
  | "error";

const DEFAULT_LAUNCH: LaunchConfig = {
  agent: "claude",
  image: "super-claude:latest",
  network: "direct",
  scope: "project",
};

/** Fixed 4-agent tab order (03 §六; 06 §五 S2.2). */
const AGENT_ORDER: LaunchAgent[] = ["claude", "codex", "bash", "cc-switch"];

const AGENT_TITLE: Record<LaunchAgent, string> = {
  claude: "Claude",
  codex: "Codex",
  bash: "Bash",
  "cc-switch": "cc-switch",
};

/** Session states that have reached a terminal outcome (no live PTY). */
const TERMINAL_STATES: TabSessionState[] = ["exited", "failed", "disconnected"];

function uuid(): string {
  return crypto.randomUUID();
}

export const useRuntimeStore = defineStore("runtime", () => {
  const capability = ref<CapabilityReport | null>(null);
  const status = ref<WorkbenchStatus>("idle");
  const error = ref<WorkbenchError | null>(null);

  const workspace = ref("");
  const runtimeId = ref("");
  const runtimeReady = ref(false);

  // S2.2.b: runtime observation (op-driven; polling lands in S2.3). 03 §四.
  const runtimeState = ref<RuntimeState>("unknown");
  const runtimeSnapshot = ref<RuntimeSnapshot | null>(null);
  const conflicts = ref<RuntimeSnapshot[]>([]);
  const conflictError = ref<WorkbenchError | null>(null);

  // S2.3.a: freshness + in-flight inspect dedupe (04 §六.1, §五 dedupe).
  const freshness = ref<Freshness>("unknown");
  const inspectInFlight = ref(false);

  const preflight = ref<PreflightReport | null>(null);
  const launch = ref<LaunchConfig>({ ...DEFAULT_LAUNCH });
  const showAdvanced = ref(false);
  const startElapsedMs = ref(0);
  const cancelInspect = ref<RuntimeSnapshot | null>(null);

  // S2.1.b build state (in-memory only, 05 §4.1.5)
  const buildStatus = ref<BuildStatus>("idle");
  const buildLog = ref("");
  const buildTag = ref("");
  const buildError = ref<WorkbenchError | null>(null);

  // S2.2.a: multi-tab. One tab per agent, sharing the runtime (03 §二.3/§六).
  const tabs = ref<Tab[]>([]);
  const activeTabId = ref<string | null>(null);

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

  function resetWorkspace() {
    tabs.value = [];
    activeTabId.value = null;
    preflight.value = null;
    runtimeId.value = "";
    runtimeState.value = "unknown";
    runtimeSnapshot.value = null;
    conflicts.value = [];
    conflictError.value = null;
    freshness.value = "unknown";
    inspectInFlight.value = false;
  }

  function backToPicker() {
    resetWorkspace();
    status.value = "picker";
  }

  // S2.1.b: build the image with `aisc build --events` (05 §4.1).
  async function startBuild(tag: string) {
    buildTag.value = tag;
    buildLog.value = "";
    buildError.value = null;
    buildStatus.value = "building";
    status.value = "building";
    // Channel only streams opaque build.output chunks for display. The terminal
    // outcome (complete/failed/cancelled) is authoritative from the command
    // return (try/catch below), avoiding any race with callback delivery.
    const ch = new Channel<BuildEvent>();
    ch.onmessage = (ev) => {
      if (ev.type === "build.output") {
        const chunk = ev.data?.chunk;
        if (typeof chunk === "string") buildLog.value += chunk;
      }
    };
    try {
      await ipc.buildImage(tag, ch);
      // Ok return == build.complete (05 §4.1.2). Stay on BuildProgress so the
      // user can review the log; "返回摘要" triggers re-preflight.
      buildStatus.value = "complete";
    } catch (e) {
      const err = e as WorkbenchError;
      buildError.value = err;
      buildStatus.value = err.code === "WB_ERR_CLI_CANCELLED" ? "cancelled" : "failed";
    }
  }

  async function cancelBuild() {
    try {
      await ipc.cancelBuild();
    } catch {
      /* best-effort */
    }
  }

  function backToSummaryFromBuild() {
    buildStatus.value = "idle";
    buildLog.value = "";
    buildError.value = null;
    status.value = preflight.value ? "summary" : "preflight";
    if (!preflight.value) void runPreflight();
  }

  async function runPreflight() {
    if (!workspace.value.trim()) return;
    if (!runtimeId.value) {
      // S2.2.b: discover an existing workbench project runtime in this
      // workspace so preflight can match it (reuse/restart) instead of always
      // generating a fresh id - a fresh id never matches an existing project
      // runtime and would spuriously report resolve_conflict. Full history
      // reconciliation (orphan detection, multi-window) lands in S2.4.
      try {
        const res = await ipc.listRuntimes(workspace.value.trim(), "workbench");
        const existing = res.runtimes.find((r) => r.config.scope === "project");
        if (existing) runtimeId.value = existing.runtime_id;
      } catch {
        /* Docker/CLI unavailable - preflight will report the real error */
      }
    }
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
      if (report.recommended_action === "resolve_conflict") {
        // Skip the summary (Start would be disabled by the config gate) and go
        // straight to conflict resolution (03 §三).
        status.value = "conflict";
        void loadConflicts();
      } else {
        status.value = "summary";
      }
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

  // --- S2.2.b: runtime observation + conflict resolution (03 §四/§十) ---

  /** Apply a fresh runtime observation with a simple stale guard (04 §六.2):
   * an older observation must not overwrite a newer one. ISO-UTC strings
   * compare lexicographically = chronologically. */
  function applyRuntimeSnapshot(snap: RuntimeSnapshot) {
    const cur = runtimeSnapshot.value;
    if (cur && cur.observed_at && snap.observed_at && snap.observed_at < cur.observed_at) {
      return; // stale observation - don't overwrite or mark fresh (04 §六.2)
    }
    runtimeSnapshot.value = snap;
    runtimeState.value = snap.state;
    freshness.value = "fresh";
  }

  /** Mark the current observation stale (failed request or app resume). Keeps
   * the last snapshot; P0 shows "Last known · stale" (04 §六.1). */
  function markStale() {
    if (runtimeSnapshot.value) freshness.value = "stale";
  }

  /** Inspect the active runtime now and apply (deduped). Drives the polling
   * loop and the manual Refresh button. */
  async function refreshRuntime() {
    if (!runtimeId.value || !workspace.value.trim()) return;
    if (inspectInFlight.value) return;
    inspectInFlight.value = true;
    try {
      const snap = await ipc.runtimeInspect(workspace.value.trim(), runtimeId.value);
      applyRuntimeSnapshot(snap);
    } catch {
      markStale();
    } finally {
      inspectInFlight.value = false;
    }
  }

  /** List workbench-owned runtimes in the workspace (conflict resolution). */
  async function loadConflicts() {
    conflictError.value = null;
    try {
      const res = await ipc.listRuntimes(workspace.value.trim(), "workbench");
      conflicts.value = res.runtimes;
    } catch (e) {
      conflictError.value = e as WorkbenchError;
      conflicts.value = [];
    }
  }

  async function stopConflictRuntime(id: string) {
    try {
      await ipc.stopRuntime(workspace.value.trim(), id);
    } catch (e) {
      conflictError.value = e as WorkbenchError;
    }
    await loadConflicts();
  }

  async function removeConflictRuntime(id: string, force = false) {
    try {
      await ipc.removeRuntime(workspace.value.trim(), id, force);
    } catch (e) {
      conflictError.value = e as WorkbenchError;
    }
    await loadConflicts();
  }

  function retryFromConflict() {
    conflicts.value = [];
    conflictError.value = null;
    preflight.value = null;
    runtimeId.value = ""; // re-discover (or fresh id) on the next preflight
    status.value = "preflight";
    void runPreflight();
  }

  /** Exit-Workbench gate (02 §七.3): confirm if any session is live, then end
   * owned sessions (keep the runtime running). Returns whether the window may
   * close. */
  async function confirmExit(): Promise<boolean> {
    const live = tabs.value.filter(
      (t) => t.sessionState === "running" || t.sessionState === "starting"
    );
    if (live.length === 0) return true;
    const ok = await confirm(
      `有 ${live.length} 个活动会话，退出将结束它们（Runtime 保留运行）。继续？`
    );
    if (!ok) return false;
    await Promise.all(
      live
        .filter((t) => t.sessionId)
        .map((t) => ipc.closeSession(t.sessionId!).catch(() => null))
    );
    return true;
  }

  // --- S2.2.a: multi-tab session lifecycle (03 §五/§六) ---

  /** Build the 4 fixed tabs and open the initial agent's tab (runtime ready). */
  function initTabs(initialAgent: LaunchAgent) {
    tabs.value = AGENT_ORDER.map((agent) => ({
      tabId: uuid(),
      agent,
      title: AGENT_TITLE[agent],
      sessionId: null,
      sessionState: "idle" as TabSessionState,
      exit: null,
    }));
    const initial = tabs.value.find((t) => t.agent === initialAgent);
    if (initial) {
      activeTabId.value = initial.tabId;
      void openTab(initial.tabId);
    }
    status.value = "ready";
  }

  function findTab(tabId: string): Tab | undefined {
    return tabs.value.find((t) => t.tabId === tabId);
  }

  /** Open (or reopen) a tab's session: assigns a fresh session_id and enters
   * `starting`. The mounted Terminal watches the session_id and calls
   * `open_session`; it reports back via onTabOpenOk/onTabOpenFail. */
  function openTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    if (tab.sessionState === "starting" || tab.sessionState === "running") return;
    tab.sessionId = uuid();
    tab.sessionState = "starting";
    tab.exit = null;
    activeTabId.value = tabId;
  }

  /** Activate a tab; idle tabs are opened on first activation. */
  function activateTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    activeTabId.value = tabId;
    if (tab.sessionState === "idle") openTab(tabId);
  }

  /** Reopen an exited/failed/disconnected tab with a fresh session. */
  function reopenTab(tabId: string) {
    openTab(tabId);
  }

  /** Close a running/starting tab: terminate the session. The PTY Exit event
   * (single authoritative signal, 03 §五.2) finalizes the state via
   * onTabSessionExit; close_session guarantees the child is reaped. */
  async function closeTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab || !tab.sessionId) return;
    if (TERMINAL_STATES.includes(tab.sessionState) || tab.sessionState === "closing") return;
    tab.sessionState = "closing";
    try {
      await ipc.closeSession(tab.sessionId);
    } catch {
      /* best-effort; Exit event still finalizes if the child is reaped */
    }
  }

  function onTabOpenOk(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    if (tab.sessionState === "starting") tab.sessionState = "running";
  }

  function onTabOpenFail(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    if (TERMINAL_STATES.includes(tab.sessionState)) return; // already finalized
    tab.sessionState = "failed";
    // exit stays null; the Terminal writes the open error inline.
  }

  /** PTY Exit event (process_exit / user_close / transport_error). Applied
   * once per tab (idempotent) - duplicate Exit/terminate results merge. */
  function onTabSessionExit(tabId: string, reason: string, exitCode: number | null) {
    const tab = findTab(tabId);
    if (!tab || tab.exit) return; // first writer wins (03 §五.2)
    const exit: TabExit = { reason, exitCode };
    tab.exit = exit;
    tab.sessionState = reason === "transport_error" ? "disconnected" : "exited";
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
        await ipc.startRuntime(
          workspace.value.trim(),
          runtimeId.value,
          launch.value.image,
          launch.value.network,
          launch.value.scope
        );
        runtimeState.value = "running";
      } else if (report.recommended_action === "reuse" && report.matching_runtime_id) {
        runtimeId.value = report.matching_runtime_id;
        status.value = "starting";
        runtimeState.value = "running";
      } else if (report.recommended_action === "restart" && report.matching_runtime_id) {
        runtimeId.value = report.matching_runtime_id;
        status.value = "starting";
        const snap = await ipc.runtimeRestart(workspace.value.trim(), runtimeId.value);
        applyRuntimeSnapshot(snap);
      } else {
        // resolve_conflict: list workbench runtimes so the user can stop/remove
        // the incompatible one, then re-preflight (03 §三).
        stopTimer();
        status.value = "conflict";
        void loadConflicts();
        return;
      }
      stopTimer();
      runtimeReady.value = true;
      initTabs(launch.value.agent);
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
      const snap = await ipc.runtimeInspect(workspace.value.trim(), runtimeId.value);
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
      await ipc.stopRuntime(workspace.value.trim(), runtimeId.value);
    } catch {
      /* best-effort */
    }
    cancelInspect.value = null;
    resetWorkspace();
    status.value = "picker";
  }

  async function stopRuntime() {
    status.value = "stopping";
    // Close every live session best-effort (03 §七.2), then stop the runtime.
    const live = tabs.value.filter(
      (t) => t.sessionId && !TERMINAL_STATES.includes(t.sessionState) && t.sessionState !== "closing"
    );
    await Promise.all(live.map((t) => ipc.closeSession(t.sessionId!).catch(() => null)));
    tabs.value = [];
    activeTabId.value = null;
    try {
      if (runtimeId.value) {
        await ipc.stopRuntime(workspace.value.trim(), runtimeId.value);
      }
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
      return;
    }
    runtimeId.value = "";
    runtimeReady.value = false;
    runtimeState.value = "unknown";
    runtimeSnapshot.value = null;
    freshness.value = "unknown";
    inspectInFlight.value = false;
    preflight.value = null;
    status.value = "picker";
  }

  return {
    capability,
    status,
    error,
    workspace,
    runtimeId,
    runtimeReady,
    preflight,
    launch,
    showAdvanced,
    startElapsedMs,
    cancelInspect,
    buildStatus,
    buildLog,
    buildTag,
    buildError,
    tabs,
    activeTabId,
    runtimeState,
    runtimeSnapshot,
    conflicts,
    conflictError,
    freshness,
    inspectInFlight,
    negotiate,
    pickAndPinCli,
    pickWorkspace,
    backToPicker,
    startBuild,
    cancelBuild,
    backToSummaryFromBuild,
    runPreflight,
    recomputePreflightNeeded,
    startFromSummary,
    cancelStart,
    keepCancelledRuntime,
    stopCancelledRuntime,
    stopRuntime,
    initTabs,
    openTab,
    activateTab,
    closeTab,
    reopenTab,
    onTabOpenOk,
    onTabOpenFail,
    onTabSessionExit,
    applyRuntimeSnapshot,
    markStale,
    refreshRuntime,
    loadConflicts,
    stopConflictRuntime,
    removeConflictRuntime,
    retryFromConflict,
    confirmExit,
  };
});
