import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import { Channel } from "@tauri-apps/api/core";
import type {
  BuildEvent,
  BuildStatus,
  CapabilityReport,
  Freshness,
  HistoryPatch,
  LaunchAgent,
  LaunchConfig,
  PreflightReport,
  ProviderStatus,
  RuntimeRef,
  RuntimeSnapshot,
  RuntimeState,
  Tab,
  TabExit,
  TabRecord,
  TabSessionState,
  WorkbenchError,
  WorkbenchHistory,
  WorkspaceRecord,
} from "../types";
import * as ipc from "../lib/ipc";
import { AGENT_TITLE, resolveActiveTabId, tabsFromRecords } from "./tabLayout";

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

/** Fixed 4-agent tab order for fresh starts (03 §六; Step 5 replaces with the
 * dynamic createTab model). */
const AGENT_ORDER: LaunchAgent[] = ["claude", "codex", "bash", "cc-switch"];

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

  // S3.1: request_seq / revision anti-revert (04 §六.2). Each observation
  // request gets a monotonic seq; stale (low-seq) responses never overwrite
  // newer state, replacing the S2.2.b observed_at ordering guard.
  const requestSeq = ref(0);
  const lastAppliedSeq = ref(0);
  const revision = ref(0);

  // S2.3.b: per-agent provider cache (claude/codex only; 04 §四.2 "no global
  // provider"). bash/cc-switch are not applicable.
  const providerStatuses = ref<Record<"claude" | "codex", ProviderStatus | null>>({
    claude: null,
    codex: null,
  });
  const providerError = ref<WorkbenchError | null>(null);
  const providerInFlight = ref<"claude" | "codex" | null>(null);

  // S2.4.a: workbench history (02 §九). Persisted workspace/runtime/layout.
  const history = ref<WorkbenchHistory | null>(null);
  const historyRevision = ref(0);
  /** Last runtime started for this workspace; remembered across stops so S2.4.b
   * resume can find it (not cleared on stop). */
  const lastRuntimeRef = ref<RuntimeRef | null>(null);
  const recentWorkspaces = computed<WorkspaceRecord[]>(() => {
    const ws = history.value?.workspaces ?? [];
    return [...ws]
      .filter((w) => w.path)
      .sort((a, b) => (b.last_used_at || "").localeCompare(a.last_used_at || ""));
  });
  /** S2.4.b: a restorable tab layout for the current workspace - non-null only
   * when preflight says the runtime exists (reuse/restart) and history has open
   * tabs. Drives the 恢复布局 button in LaunchSummary (02 §2.3). The input is
   * the complete TabRecord list (position-sorted), not an agent list; the
   * active tab is mapped by saved tab_id (A-INFRA-1). */
  const restorableLayout = computed<{ records: TabRecord[]; activeSavedId: string | null } | null>(() => {
    const report = preflight.value;
    if (!report || !["reuse", "restart"].includes(report.recommended_action)) return null;
    const rec = (history.value?.workspaces ?? []).find((w) => w.path === workspace.value.trim());
    const histTabs = rec?.layout?.tabs ?? [];
    if (histTabs.length === 0) return null;
    const records = [...histTabs].sort((a, b) => a.position - b.position);
    return { records, activeSavedId: rec?.layout?.active_tab_id ?? null };
  });
  let saveTimer: number | null = null;

  const preflight = ref<PreflightReport | null>(null);
  const launch = ref<LaunchConfig>({ ...DEFAULT_LAUNCH });
  const showAdvanced = ref(false);
  const startElapsedMs = ref(0);
  const dockerStarting = ref(false);
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
    void loadHistory(); // parallel, best-effort (02 §九)
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
    if (dockerRetryTimer !== null) {
      window.clearTimeout(dockerRetryTimer);
      dockerRetryTimer = null;
    }
    dockerStarting.value = false;
    requestSeq.value = 0;
    lastAppliedSeq.value = 0;
    revision.value = 0;
    clearProviderStatuses();
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
    // The image was just (re)built; drop the stale preflight and re-run so the
    // image check picks up the new image (otherwise the old "missing" result
    // is shown and Start stays disabled).
    preflight.value = null;
    status.value = "preflight";
    void runPreflight();
  }

  async function runPreflight() {
    if (!workspace.value.trim()) return;
    scheduleSave(); // record workspace selection (path/last_used/last_agent)
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
      // Route to conflict resolution only when the runtime_conflict check
      // itself failed. `recommended_action=resolve_conflict` is returned for
      // ANY failed check (workspace/image/docker too), so routing on it alone
      // deadlocks when the failure isn't a runtime conflict (no runtimes to
      // list). Other failures go to the summary, which shows the real gate.
      const runtimeConflictFailed = report.checks.some(
        (c) => c.id === "runtime_conflict" && c.status === "fail"
      );
      if (runtimeConflictFailed) {
        status.value = "conflict";
        void loadConflicts();
      } else {
        status.value = "summary";
        // S4.1.b (TODO 20260806 line 76): the installer finish page starts
        // Docker Desktop then immediately opens Workbench, but the engine
        // takes ~30-60s to boot. Auto-retry the docker gate on entry so the
        // finish-page chain resolves without user interaction; the manual
        // 「启动 Docker」 button stays as a fallback. startDockerAndRepreflight
        // is reentrancy-guarded (dockerStarting) so the polling loop's own
        // runPreflight calls never re-trigger it.
        const dockerFailed = report.checks.some(
          (c) => c.id === "docker" && c.status === "fail"
        );
        if (dockerFailed && !dockerStarting.value) {
          void startDockerAndRepreflight();
        }
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

  /** Start the Docker engine (Docker Desktop) and re-run preflight once the
   * daemon is reachable. Used from the summary when the docker gate is red
   * (auto on entry, or via the 「启动 Docker」 button). Reentrant-call guarded
   * by `dockerStarting`. */
  let dockerRetryTimer: number | null = null;
  async function startDockerAndRepreflight() {
    if (dockerStarting.value) return; // one polling loop at a time
    error.value = null;
    dockerStarting.value = true;
    try {
      await ipc.startDocker();
      // Docker Desktop takes a while to boot the engine (first run: license
      // dialog + WSL init, ~30-60s); poll preflight every 3s for up to ~2 min
      // instead of one-shot.
      const deadline = Date.now() + 120_000;
      const attempt = async (): Promise<void> => {
        try {
          await runPreflight();
          const dockerOk = preflight.value?.checks.some(
            (c) => c.id === "docker" && c.status === "pass"
          );
          if (dockerOk) {
            dockerStarting.value = false;
            return;
          }
        } catch {
          /* engine still starting - retry */
        }
        if (Date.now() < deadline) {
          dockerRetryTimer = window.setTimeout(attempt, 3_000);
        } else {
          dockerStarting.value = false;
          error.value = {
            code: "WB_ERR_DOCKER_START_TIMEOUT",
            message: "Docker 引擎启动超时，请手动打开 Docker Desktop",
            technical_detail: null,
            retryable: true,
            action: "start_docker",
          };
        }
      };
      await attempt();
    } catch (e) {
      dockerStarting.value = false;
      error.value = e as WorkbenchError;
    }
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
  /** Apply an observation with its request seq (04 §六.2). A response whose
   * seq is lower than the last applied one is stale (slow poll or superseded
   * control op) and is dropped - it must never overwrite newer state. */
  function applyRuntimeSnapshot(snap: RuntimeSnapshot, seq: number) {
    if (seq < lastAppliedSeq.value) return; // stale response
    runtimeSnapshot.value = snap;
    runtimeState.value = snap.state;
    freshness.value = "fresh";
    // Canonical workspace write-back (05 §4.1 / A-INFRA-3): the CLI returns the
    // canonicalized config.workspace; store/history key on that value, never
    // on the raw frontend string.
    if (snap.config?.workspace) {
      workspace.value = snap.config.workspace;
      scheduleSave();
    }
    lastAppliedSeq.value = seq;
    revision.value += 1;
  }

  /** Mark the current observation stale (failed request or app resume). Keeps
   * the last snapshot; P0 shows "Last known · stale" (04 §六.1). */
  function markStale() {
    if (runtimeSnapshot.value) freshness.value = "stale";
  }

  /** Inspect the active runtime now and apply (deduped). Drives the polling
   * loop and the manual Refresh button. Assigns a request seq so a stale
   * response can never overwrite newer state (04 §六.2). */
  async function refreshRuntime() {
    if (!runtimeId.value || !workspace.value.trim()) return;
    if (inspectInFlight.value) return;
    inspectInFlight.value = true;
    const seq = ++requestSeq.value;
    try {
      const snap = await ipc.runtimeInspect(workspace.value.trim(), runtimeId.value);
      applyRuntimeSnapshot(snap, seq);
    } catch {
      markStale();
    } finally {
      inspectInFlight.value = false;
    }
  }

  // --- S2.3.b: provider status (per-agent, claude/codex only; 04 §四.2/§五) ---

  /** Query + cache the provider status for one agent. Only when the runtime is
   * running (04 §五). Per-agent cache, never cross-applied. */
  async function loadProviderStatus(agent: "claude" | "codex") {
    if (runtimeState.value !== "running") return;
    if (!runtimeId.value || !workspace.value.trim()) return;
    if (providerInFlight.value === agent) return;
    providerInFlight.value = agent;
    providerError.value = null;
    try {
      const status = await ipc.getProviderStatus(workspace.value.trim(), runtimeId.value, agent);
      providerStatuses.value = { ...providerStatuses.value, [agent]: status };
    } catch (e) {
      providerError.value = e as WorkbenchError;
    } finally {
      providerInFlight.value = null;
    }
  }

  function clearProviderStatuses() {
    providerStatuses.value = { claude: null, codex: null };
    providerError.value = null;
    providerInFlight.value = null;
  }

  // --- S2.4.a: history persistence (02 §九) ---

  async function loadHistory() {
    try {
      const h = await ipc.loadHistory();
      history.value = h;
      historyRevision.value = h.revision;
    } catch {
      history.value = { schema_version: 1, revision: 0, workspaces: [] };
      historyRevision.value = 0;
    }
  }

  /** Build a patch for the active workspace (runtime ref + open-tab layout).
   * Only non-idle (open) tabs are recorded so the layout reflects what was
   * actually open and S2.4.b resume can restore those agents. Other workspaces
   * on disk are preserved by the backend merge (02 §九). */
  function buildPatch(): HistoryPatch {
    const openTabs = tabs.value.filter((t) => t.sessionState !== "idle");
    const tabsRecord = openTabs.map((t, i) => ({
      tab_id: t.tabId,
      agent: t.agent,
      title: t.title,
      position: i,
    }));
    const activeAgent =
      tabs.value.find((t) => t.tabId === activeTabId.value)?.agent ?? launch.value.agent;
    const activeTabIdRec = openTabs.some((t) => t.tabId === activeTabId.value)
      ? activeTabId.value
      : null;
    const rec: WorkspaceRecord = {
      path: workspace.value.trim(),
      last_used_at: new Date().toISOString(),
      pinned: false,
      last_agent: activeAgent,
      runtime: lastRuntimeRef.value,
      layout: { active_tab_id: activeTabIdRec, tabs: tabsRecord },
    };
    return { workspaces: [rec] };
  }

  /** Debounce saves so rapid tab/layout changes coalesce. */
  function scheduleSave() {
    if (!workspace.value.trim()) return;
    if (saveTimer !== null) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      void doSave(3);
    }, 300);
  }

  async function doSave(retries: number) {
    if (!workspace.value.trim()) return;
    const patch = buildPatch();
    try {
      const newRev = await ipc.saveHistory(historyRevision.value, patch);
      historyRevision.value = newRev;
    } catch (e) {
      const err = e as WorkbenchError;
      if (err?.code === "WB_ERR_HISTORY_CONFLICT" && retries > 0) {
        // Another window wrote first: reload, adopt the new revision, retry.
        try {
          const fresh = await ipc.loadHistory();
          history.value = fresh;
          historyRevision.value = fresh.revision;
        } catch {
          return; // reload failed; best-effort, drop this save
        }
        void doSave(retries - 1);
      }
      // other error: best-effort, give up this save
    }
  }

  /** Select a recent workspace from history: restore its last launch config
   * (image/network/scope/agent) + runtime ref (02 §六 priority: the workspace's
   * last confirmed config beats the built-in default), then preflight. This
   * makes preflight match the existing runtime (reuse/restart) instead of
   * spurious-conflicting with the default image. */
  function selectRecentWorkspace(path: string) {
    const rec = (history.value?.workspaces ?? []).find((w) => w.path === path);
    if (rec) {
      if (rec.runtime) {
        launch.value.image = rec.runtime.image;
        launch.value.network = rec.runtime.network as LaunchConfig["network"];
        launch.value.scope = rec.runtime.scope as LaunchConfig["scope"];
        lastRuntimeRef.value = rec.runtime;
      }
      if (rec.last_agent) {
        launch.value.agent = rec.last_agent as LaunchAgent;
      }
    }
    workspace.value = path;
    void runPreflight();
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
    const ok = await confirm(`停止 Runtime ${id.slice(0, 8)}？容器将停止但保留。`);
    if (!ok) return;
    try {
      await ipc.stopRuntime(workspace.value.trim(), id);
    } catch (e) {
      conflictError.value = e as WorkbenchError;
    }
    await loadConflicts();
  }

  async function removeConflictRuntime(id: string, force = false) {
    const ok = await confirm(
      force
        ? `强制移除运行中的 Runtime ${id.slice(0, 8)}？容器与元数据将永久删除。`
        : `移除 Runtime ${id.slice(0, 8)}？容器与元数据将永久删除。`
    );
    if (!ok) return;
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
  /** Surface a shutdown/exit failure as a recoverable error view (03 §4.3). */
  function setExitError(message: string) {
    error.value = {
      code: "WB_ERR_REAP_TIMEOUT",
      message,
      technical_detail: null,
      retryable: true,
      action: "retry",
    };
    status.value = "error";
  }

  async function confirmExit(): Promise<boolean> {
    const live = tabs.value.filter(
      (t) => t.sessionState === "running" || t.sessionState === "starting"
    );
    if (live.length === 0) return true;
    const ok = await confirm(
      `有 ${live.length} 个活动会话，退出将结束它们（Runtime 保留运行）。继续？`
    );
    if (!ok) return false;
    // Cleanup is owned by shutdown_workbench (03 §4.3); no fire-and-forget here.
    return true;
  }

  // --- S2.2.a: multi-tab session lifecycle (03 §五/§六) ---

  /** Build tabs from TabRecords and open fresh sessions (new id, never
   * reattaching a PTY - 03 §六). Fresh start passes the fixed 4 records and
   * opens only the requested agents; resume (S2.4.b) passes the history
   * records (duplicates preserved, A-INFRA-1) and opens all. */
  function initTabs(
    records: TabRecord[],
    opts: {
      activeSavedId?: string | null;
      activeAgent?: LaunchAgent | null;
      openAgents?: LaunchAgent[];
    } = {}
  ) {
    lastRuntimeRef.value = {
      runtime_id: runtimeId.value,
      image: launch.value.image,
      network: launch.value.network,
      scope: launch.value.scope,
    };
    const { tabs: created, bySavedId } = tabsFromRecords(records);
    tabs.value = created;
    for (const tab of created) {
      if (!opts.openAgents || opts.openAgents.includes(tab.agent)) void openTab(tab.tabId);
    }
    activeTabId.value = resolveActiveTabId(created, bySavedId, {
      activeSavedId: opts.activeSavedId,
      activeAgent: opts.activeAgent,
    });
    status.value = "ready";
    scheduleSave();
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
    scheduleSave();
  }

  /** Activate a tab; idle tabs are opened on first activation. */
  function activateTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    activeTabId.value = tabId;
    if (tab.sessionState === "idle") openTab(tabId);
    scheduleSave();
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
   * once per tab (idempotent) - duplicate Exit/terminate results merge. After
   * the pane state is committed, ack the backend so the terminal registry
   * entry can be evicted (03 §3.3.2; idempotent on both sides). */
  function onTabSessionExit(tabId: string, reason: string, exitCode: number | null) {
    const tab = findTab(tabId);
    if (!tab || tab.exit) return; // first writer wins (03 §五.2)
    const exit: TabExit = { reason, exitCode };
    tab.exit = exit;
    tab.sessionState = reason === "transport_error" ? "disconnected" : "exited";
    if (tab.sessionId) {
      void ipc.ackSessionExit(tab.sessionId).catch(() => null); // TTL sweeps if lost
    }
  }

  /** Ensure the runtime is ready per preflight's recommended_action (start /
   * reuse / restart). Returns false for resolve_conflict (Start is disabled by
   * the config gate; defensive). Shared by startFromSummary + resumeLayout.
   * Control ops bump the request seq so in-flight stale polls are superseded
   * (04 §六.2). */
  async function ensureRuntime(): Promise<boolean> {
    const report = preflight.value;
    if (!report) return false;
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
      // Generation boundary: supersede any in-flight poll observations.
      lastAppliedSeq.value = ++requestSeq.value;
      revision.value += 1;
    } else if (report.recommended_action === "reuse" && report.matching_runtime_id) {
      runtimeId.value = report.matching_runtime_id;
      status.value = "starting";
      runtimeState.value = "running";
      lastAppliedSeq.value = ++requestSeq.value;
      revision.value += 1;
    } else if (report.recommended_action === "restart" && report.matching_runtime_id) {
      runtimeId.value = report.matching_runtime_id;
      status.value = "starting";
      const seq = ++requestSeq.value;
      const snap = await ipc.runtimeRestart(workspace.value.trim(), runtimeId.value);
      applyRuntimeSnapshot(snap, seq);
    } else {
      return false; // resolve_conflict - Start disabled, defensive
    }
    return true;
  }

  /** Start/reuse/restart the runtime then open tabs. Shared by the normal
   * Start (one tab) and 恢复布局 (history tabs, 02 §2.3). */
  async function launchRuntime(
    records: TabRecord[],
    opts: {
      activeSavedId?: string | null;
      activeAgent?: LaunchAgent | null;
      openAgents?: LaunchAgent[];
    } = {}
  ) {
    error.value = null;
    cancelInspect.value = null;
    startTimerTick();
    try {
      const ok = await ensureRuntime();
      if (!ok) {
        stopTimer();
        status.value = "conflict";
        void loadConflicts();
        return;
      }
      stopTimer();
      runtimeReady.value = true;
      initTabs(records, opts);
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

  async function startFromSummary() {
    if (!preflight.value) return;
    const records: TabRecord[] = AGENT_ORDER.map((agent, position) => ({
      tab_id: uuid(),
      agent,
      title: AGENT_TITLE[agent],
      position,
    }));
    await launchRuntime(records, {
      openAgents: [launch.value.agent],
      activeAgent: launch.value.agent,
    });
  }

  /** S2.4.b: restore the history layout's open tabs with fresh sessions
   * (02 §2.3). Per-record restore (A-INFRA-1); each tab gets a new session_id;
   * PTY content is not reattached. */
  async function resumeLayout() {
    const layout = restorableLayout.value;
    if (!layout) return;
    await launchRuntime(layout.records, { activeSavedId: layout.activeSavedId });
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
    const live = tabs.value.filter(
      (t) => t.sessionState === "running" || t.sessionState === "starting"
    );
    const ok = await confirm(
      live.length > 0
        ? `有 ${live.length} 个活动会话，停止将结束它们并停止 Runtime。继续？`
        : "停止 Runtime？容器将停止但保留。"
    );
    if (!ok) return;
    status.value = "stopping";
    // Close every live session best-effort (03 §七.2), then stop the runtime.
    const closing = tabs.value.filter(
      (t) => t.sessionId && !TERMINAL_STATES.includes(t.sessionState) && t.sessionState !== "closing"
    );
    await Promise.all(closing.map((t) => ipc.closeSession(t.sessionId!).catch(() => null)));
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
    requestSeq.value = 0;
    lastAppliedSeq.value = 0;
    revision.value = 0;
    clearProviderStatuses();
    preflight.value = null;
    status.value = "picker";
  }

  return {
    capability,
    status,
    error,
    setExitError,
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
    providerStatuses,
    providerError,
    providerInFlight,
    history,
    historyRevision,
    recentWorkspaces,
    restorableLayout,
    negotiate,
    pickAndPinCli,
    pickWorkspace,
    backToPicker,
    startBuild,
    cancelBuild,
    backToSummaryFromBuild,
    runPreflight,
    recomputePreflightNeeded,
    startDockerAndRepreflight,
    dockerStarting,
    startFromSummary,
    resumeLayout,
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
    loadProviderStatus,
    clearProviderStatuses,
    loadHistory,
    selectRecentWorkspace,
    loadConflicts,
    stopConflictRuntime,
    removeConflictRuntime,
    retryFromConflict,
    confirmExit,
  };
});
