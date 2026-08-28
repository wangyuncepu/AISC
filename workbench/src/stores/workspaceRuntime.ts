import { ref } from "vue";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import { Channel } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import type {
  BuildEvent,
  BuildProgressData,
  BuildStatus,
  Freshness,
  HistoryPatch,
  LaunchAgent,
  LaunchConfig,
  Layout,
  PaneRuntime,
  PreflightReport,
  PtyEvent,
  ProviderStatus,
  RuntimeRef,
  RuntimeServicesResult,
  ReconcilePayload,
  RuntimeSnapshot,
  RuntimeState,
  SplitAxis,
  Tab,
  TabExit,
  TabRecord,
  TabSessionState,
  WorkbenchError,
  WorkbenchHistory,
  WorkspaceRecord,
} from "../types";
import * as ipc from "../lib/ipc";
import { i18n } from "../i18n";
import {
  AGENT_TITLE,
  internalToPersisted,
  newPaneTab,
  normalizePath,
  resolveActiveTabId,
  sameWorkspace,
  tabsFromRecords,
} from "./tabLayout";
import {
  DEFAULT_RATIO,
  MAX_LEAVES as MAX_PANES,
  findLeaf,
  firstLeaf,
  leafCount,
  listLeaves,
  navigateLeaf,
  removeLeaf,
  setRatioBySplitKey,
  singleLeaf,
  splitLeaf,
} from "./paneTree";
import type { NavDir } from "./paneTree";
import { appendWithBudget } from "../domain/streamBuffer";

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
  image: "super-claude:latest",
  network: "direct",
  scope: "project",
};

/** G-08 (Step 5): per-Runtime leaf cap - the 9th concurrent tab is refused
 * (A-G08-8). History saves truncate defensively at the same bound. */
const MAX_TABS = 8;

/** IDEA-1: sentinel id of the virtual Settings tab. Real tab ids are UUIDs,
 * so this never collides. The settings tab is NOT a session tab: it lives
 * outside `tabs` (never persisted, never counted toward MAX_TABS, owns no
 * PTY); `activeTabId` may hold this id while it is open. */
export const SETTINGS_TAB_ID = "settings-tab";

/** Stage 8e (CS-05): the virtual cc-switch Provider UI tab — same contract
 * as the settings tab (no session, never persisted, closes with the tab ×).
 * Coexists with the `cc-switch` TUI tab (advanced diagnostics). */
export const CC_SWITCH_UI_TAB_ID = "cc-switch-ui-tab";

/** IDEA-2 (2d): sentinel id of the workspace-layer「网络与用量」panel —
 * same contract as the Settings sentinel (never persisted, owns no PTY,
 * survives workspace switches/closes; the strip chip and the + ▾ menu are
 * its only entries — no shortcut in v1, WebView2 swallow risk unprobed). */
export const NETWORK_USAGE_TAB_ID = "network-usage-tab";

/** Session states that have reached a terminal outcome (no live PTY). */
export const TERMINAL_STATES: TabSessionState[] = ["exited", "failed", "disconnected"];

function uuid(): string {
  return crypto.randomUUID();
}

/** IDEA-3 (3a): shell-owned coordination the instance delegates to. In 3c the
 * workspaces store implements both against the shared history + merged saver;
 * in 3a the runtime facade provides them for exactly one instance. */
export interface WorkspaceRuntimeDeps {
  /** Debounced history-save trigger (the shell owns the save timer + patch). */
  markDirty(): void;
  /** The current shared workbench history (owned by the shell). */
  getHistory(): WorkbenchHistory | null;
  /** Flush pending saves NOW (stopRuntime must persist the layout before it
   * clears tabs - G-07 2026-08-10). */
  flushSave(): Promise<void>;
  /** IDEA-3 (3c): fired once when this instance reaches status "ready"
   * (initTabs settle). The launcher instance materializes into a workspace. */
  onReady?(): void;
  /** runtime-lifecycle-ux (01 §1.3): when reconcile reports the SAME process
   * already materialized this workspace, the shell focuses that instance and
   * returns true (the launcher then resets silently). */
  focusExistingWorkspace?(path: string): boolean;
}

/** IDEA-3 (3a): one workspace's runtime state machine — status, tabs, panes,
 * streams, launch flow. Extracted verbatim from `stores/runtime.ts` (which
 * becomes a facade over instances) so multiple workspaces can coexist in 3c.
 * A plain factory (NOT a pinia store): instances live inside the workspaces
 * store's list; the runtime facade forwards the active one. */
export function createWorkspaceRuntime(deps: WorkspaceRuntimeDeps) {
  /** Stable instance id (never the workspace path — paths change mid-preflight). */
  const id = uuid();
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

  // svc-4: runtime web services (aisc.runtime-services/v1). Refreshed with
  // the runtime snapshot while running; cleared on stop/reset. The gateway
  // payload carries the canonical URLs — the store never builds them.
  const webServices = ref<RuntimeServicesResult | null>(null);
  const webServicesError = ref<WorkbenchError | null>(null);
  const webServicesInFlight = ref(false);

  // S2.4.a: workbench history (02 §九) is SHELL-owned (IDEA-3 3a): the shared
  // doc + revision + recents live in the facade; the instance keeps only its
  // own runtime ref and reads the shared doc through `deps.getHistory()`.
  /** Last runtime started for this workspace; remembered across stops so S2.4.b
   * resume can find it (not cleared on stop). */
  const lastRuntimeRef = ref<RuntimeRef | null>(null);
  const preflight = ref<PreflightReport | null>(null);
  // runtime-lifecycle-ux Stage 3: the reconcile pass that precedes preflight
  // (02 §3). Null while never run / transport-failed; a blocked
  // classification parks here for the (Stage 4) block page.
  const reconcile = ref<ReconcilePayload | null>(null);
  const launch = ref<LaunchConfig>({ ...DEFAULT_LAUNCH });
  const showAdvanced = ref(false);
  const startElapsedMs = ref(0);
  const dockerStarting = ref(false);
  /** When the current Docker wake-up began (ms epoch); drives the summary
   * progress banner's elapsed counter. Null while not starting. */
  const dockerStartedAt = ref<number | null>(null);
  const cancelInspect = ref<RuntimeSnapshot | null>(null);

  // S2.1.b build state (in-memory only, 05 §4.1.5). G-14 (Step 13) adds
  // store-owned timing: startBuild stamps buildStartedAt; the FIRST Promise
  // settle freezes buildFinishedAt/buildDurationMs once (A-G14-1/2/4). The
  // ticking display lives in BuildProgress while building; after settle the
  // frozen duration is shown and never grows.
  const buildStatus = ref<BuildStatus>("idle");
  const buildLog = ref("");
  // v2.1.7 S4 (Gate-S4): structured progress + the full-log path. buildLog
  // is a BOUNDED tail ring — the complete raw output lives in the file the
  // backend names in build.start (A-21748: no unbounded Vue string).
  const buildProgress = ref<BuildProgressData | null>(null);
  const buildLogPath = ref<string | null>(null);
  const BUILD_LOG_RING_CHARS = 64 * 1024;
  const buildTag = ref("");
  const buildError = ref<WorkbenchError | null>(null);
  // S8b: backend-emitted build.warning messages (e.g. the offline unpinned
  // cc-switch fallback) — bounded to the last 5, cleared per build op.
  const buildWarnings = ref<string[]>([]);
  /** G-17: per-pane PTY output buffer (base64 chunks). The store owns the
   * session channel; Terminals replay + stream from here, so remounts never
   * drop output or re-open the session. */
  const paneStreams = ref<Record<string, string[]>>({});
  // S1.3 (F-03): non-reactive pending queue + per-pane byte counters. Chunks
  // land in `pendingChunks` and are flushed once per animation frame through
  // appendWithBudget (bounded, truncation observable) into `paneStreams` as a
  // single array replacement - high-frequency writes never hit the reactive
  // tree per chunk.
  const pendingChunks: Record<string, string[]> = {};
  const paneByteCounts: Record<string, number> = {};
  const paneStreamMeta = ref<Record<string, { truncated: boolean; truncatedBytes: number }>>({});
  // Monotonic per-pane count of chunks ever appended to the buffer. The rolling
  // window drops the HEAD, so Terminal cannot advance by array length (it never
  // changes once full); it advances by this cursor instead (S1.3 hand-test fix).
  const streamCursor = ref<Record<string, number>>({});
  let flushFrame: number | null = null;
  function scheduleStreamFlush(): void {
    if (flushFrame !== null) return;
    flushFrame = window.requestAnimationFrame(() => {
      flushFrame = null;
      const ids = Object.keys(pendingChunks);
      for (const id of ids) {
        const incoming = pendingChunks[id];
        if (!incoming || incoming.length === 0) continue;
        pendingChunks[id] = [];
        const meta = paneStreamMeta.value[id] ?? { truncated: false, truncatedBytes: 0 };
        const state = appendWithBudget(
          {
            chunks: paneStreams.value[id] ?? [],
            bytes: paneByteCounts[id] ?? 0,
            truncated: meta.truncated,
            truncatedBytes: meta.truncatedBytes,
          },
          incoming,
        );
        paneStreams.value[id] = state.chunks;
        paneByteCounts[id] = state.bytes;
        streamCursor.value[id] = (streamCursor.value[id] ?? 0) + incoming.length;
        paneStreamMeta.value[id] = {
          truncated: state.truncated,
          truncatedBytes: state.truncatedBytes,
        };
      }
    });
  }
  const buildStartedAt = ref<number | null>(null);
  const buildFinishedAt = ref<number | null>(null);
  const buildDurationMs = ref<number | null>(null);
  /** Monotonic per-build op id (A-G14-2): a superseded build's late settle is
   * ignored so duration/status/notification are never double-written. */
  let buildOpId = 0;
  /** Session-scoped: at most one permission request per launch (A-G14-3). */
  let notificationPermissionRequested = false;

  // S2.2.a: multi-tab. One tab per agent, sharing the runtime (03 §二.3/§六).
  const tabs = ref<Tab[]>([]);
  const activeTabId = ref<string | null>(null);
  /** Stage 8e: the virtual cc-switch Provider UI tab is open. (The Settings
   * tab moved to the WORKSPACE layer in IDEA-3 3d — see stores/workspaces.) */
  const ccSwitchUiTabOpen = ref(false);

  let startTimer: number | null = null;

  async function pickWorkspace() {
    const picked = await open({ directory: true, multiple: false, title: i18n.global.t("runtime.pickWorkspace") });
    if (typeof picked === "string") workspace.value = picked;
  }

  function resetWorkspace() {
    tabs.value = [];
    activeTabId.value = null;
    ccSwitchUiTabOpen.value = false;
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
    dockerStartedAt.value = null;
    requestSeq.value = 0;
    lastAppliedSeq.value = 0;
    revision.value = 0;
    clearProviderStatuses();
    clearWebServices();
  }

  function backToPicker() {
    resetWorkspace();
    status.value = "picker";
  }

  /** IDEA-3 (3c): final teardown for a CLOSED workspace (closeWorkspace in
   * the workspaces store). Releases the per-pane stream buffers — the only
   * writer that ever did — and stops the instance-scoped timers, so removing
   * a workspace bounds the memory it held (buffers were never GC'd before).
   * The instance itself is dropped from the workspaces list right after. */
  function dispose(): void {
    stopTimer();
    if (dockerRetryTimer !== null) {
      window.clearTimeout(dockerRetryTimer);
      dockerRetryTimer = null;
    }
    if (flushFrame !== null) {
      window.cancelAnimationFrame(flushFrame);
      flushFrame = null;
    }
    paneStreams.value = {};
    paneStreamMeta.value = {};
    streamCursor.value = {};
    for (const k of Object.keys(pendingChunks)) delete pendingChunks[k];
    for (const k of Object.keys(paneByteCounts)) delete paneByteCounts[k];
  }

  // S2.1.b: build the image with `aisc build --events` (05 §4.1).
  // G-14 (Step 13): the terminal outcome is authoritative from the Promise
  // settle only - the Channel never writes terminal state (A-G14-2). The FIRST
  // settle for the current op freezes buildFinishedAt/buildDurationMs once and
  // triggers the background notification (A-G14-1/3).
  async function startBuild(tag: string) {
    const op = ++buildOpId;
    buildTag.value = tag;
    buildLog.value = "";
    buildProgress.value = null;
    buildLogPath.value = null;
    buildError.value = null;
    buildWarnings.value = [];
    buildStatus.value = "building";
    buildStartedAt.value = Date.now();
    buildFinishedAt.value = null;
    buildDurationMs.value = null;
    status.value = "building";
    // Channel streams opaque build.output chunks for the tail log AND the
    // structured build.progress facts (S4: the emitter is the only parser).
    const ch = new Channel<BuildEvent>();
    ch.onmessage = (ev) => {
      if (ev.type === "build.output") {
        const chunk = ev.data?.chunk;
        if (typeof chunk === "string") {
          buildLog.value += chunk;
          if (buildLog.value.length > BUILD_LOG_RING_CHARS) {
            buildLog.value = buildLog.value.slice(-BUILD_LOG_RING_CHARS);
          }
        }
      } else if (ev.type === "build.start") {
        const p = ev.data?.log_path;
        if (typeof p === "string" && p) buildLogPath.value = p;
      } else if (ev.type === "build.progress") {
        buildProgress.value = ev.data as unknown as BuildProgressData;
      } else if (ev.type === "build.warning") {
        // S8b: additive event — backend warns about degraded-but-continuing
        // builds (e.g. offline unpinned cc-switch). Unknown to older CLIs,
        // so absence is normal.
        const m = ev.data?.message;
        if (typeof m === "string" && m) {
          buildWarnings.value = [...buildWarnings.value.slice(-4), m];
        }
      }
    };
    try {
      await ipc.buildImage(tag, ch);
      // Ok return == build.complete (05 §4.1.2). Stay on BuildProgress so the
      // user can review the log; "返回摘要" triggers re-preflight.
      if (op !== buildOpId) return; // superseded build: ignore late settle
      buildStatus.value = "complete";
      void ipc.logUiEvent?.("build", "ok");
    } catch (e) {
      if (op !== buildOpId) return; // superseded build: ignore late settle
      const err = e as WorkbenchError;
      buildError.value = err;
      buildStatus.value = err.code === "WB_ERR_CLI_CANCELLED" ? "cancelled" : "failed";
      void ipc.logUiEvent?.("build", "error", err.code ?? undefined);
    }
    freezeBuildDuration();
    if (buildStatus.value === "complete" || buildStatus.value === "failed") {
      await maybeNotifyBuildFinished();
    }
  }

  /** S4: open the complete build log in the OS file manager (the store keeps
   *  only the bounded tail; the file is the full story). */
  async function revealBuildLog(): Promise<void> {
    const p = buildLogPath.value;
    if (!p) return;
    try {
      await ipc.workspaceRevealDataFile(p);
    } catch {
      /* best-effort UI affordance */
    }
  }

  /** Freeze the final duration on the first settle of the current op. */
  function freezeBuildDuration(): void {
    const started = buildStartedAt.value;
    if (started === null) return;
    const finished = Date.now();
    buildFinishedAt.value = finished;
    buildDurationMs.value = finished - started;
  }

  /** Background system notification, once per build, complete/failed only
   * (A-G14-1: foreground -> 0 notifications; A-G14-3: permission denied /
   * unavailable never changes the build facts - degrade silently, request
   * permission at most once per launch). */
  async function maybeNotifyBuildFinished(): Promise<void> {
    let background: boolean;
    try {
      const win = getCurrentWindow();
      const [focused, minimized] = await Promise.all([win.isFocused(), win.isMinimized()]);
      background = !focused || minimized;
    } catch {
      return; // cannot determine focus -> no notification (degrade)
    }
    if (!background) return;

    let granted = false;
    try {
      granted = await isPermissionGranted();
      if (!granted && !notificationPermissionRequested) {
        notificationPermissionRequested = true;
        granted = (await requestPermission()) === "granted";
      }
    } catch {
      granted = false;
    }
    if (!granted) return; // denied/default/error: no loop, no re-request

    const duration = ((buildDurationMs.value ?? 0) / 1000).toFixed(1);
    const t = i18n.global.t.bind(i18n.global);
    const body =
      buildStatus.value === "complete"
        ? t("notification.buildComplete", { duration })
        : t("notification.buildFailed");
    try {
      await sendNotification({ title: t("notification.title"), body });
    } catch {
      /* degrade: notification failure never affects build state (A-G14-3) */
    }
  }

  async function cancelBuild() {
    try {
      const hit = await ipc.cancelBuild(buildTag.value);
      if (!hit) {
        // 2026-08-27 manual test (cancel no-op): make a MISSING op visible —
        // previously both transport errors and key misses vanished here.
        void ipc.logUiEvent?.("build", "error", "WB_ERR_BUILD_CANCEL_MISSED");
        console.warn("[build] cancel missed: no active op for", buildTag.value);
      }
    } catch (e) {
      void ipc.logUiEvent?.("build", "error", "WB_ERR_BUILD_CANCEL_FAILED");
      console.error("[build] cancel transport failed:", e);
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
    // runtime-lifecycle-ux Stage 3 (01 §1.1, 02 §3/§5): reconcile FIRST —
    // stale Workbench runtimes auto-recycle; the conflict page stops being
    // the normal launch path. Every launch uses a FRESH runtime id (history
    // runtime refs never drive reuse; the old listRuntimes discovery would
    // re-couple us to the recycled container).
    runtimeId.value = uuid();
    reconcile.value = null;
    status.value = "preflight";
    error.value = null;
    try {
      const payload = await ipc.runtimeReconcile(workspace.value.trim());
      reconcile.value = payload;
      if (!payload.can_proceed) {
        if (payload.classification === "docker_unavailable") {
          // S8a (VM retest feedback #1): "cannot verify — docker is down" is
          // NOT a workspace conflict. Falling through lets preflight own the
          // gate: the summary page shows the failing docker check with the
          // actionable 启动 Docker button + auto wake-up (and, since S8h, the
          // structured not-installed error). The old route parked on the
          // generic 「启动已被阻断」 block page with the reason behind 诊断.
          void ipc.logUiEvent?.("reconcile_docker_unavailable", "error", payload.error_code ?? undefined);
        } else {
          if (
            payload.classification === "active_same_instance" &&
            deps.focusExistingWorkspace?.(workspace.value.trim())
          ) {
            // Same process already materialized this workspace: it got focused
            // — this launcher resets silently (01 §1.3).
            resetWorkspace();
            status.value = "picker";
            return;
          }
          // active_other_instance / unknown_owner: the (Stage 4) block page;
          // the conflict status renders it until then.
          status.value = "conflict";
          void loadConflicts();
          void ipc.logUiEvent?.("reconcile_block", "error", payload.error_code ?? undefined);
          return;
        }
      }
    } catch {
      // Reconcile transport failure: fall through to preflight — its docker
      // gate surfaces the real problem (the reconcile CLI shares it).
      reconcile.value = null;
    }
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
   * by `dockerStarting`.
   *
   * KI-1 UX (user feedback 2026-08-17): the boot loop probes QUIETLY —
   * `preflight` updates in place on the summary page; the global `status` is
   * never flipped (summary→preflight→summary every 3s was a full-view flash),
   * so the page reads as one continuous progress instead of flicker-then-
   * silence-then-suddenly-ready. */
  let dockerRetryTimer: number | null = null;
  async function startDockerAndRepreflight() {
    if (dockerStarting.value) return; // one polling loop at a time
    error.value = null;
    dockerStarting.value = true;
    dockerStartedAt.value = Date.now();
    const stop = () => {
      dockerStarting.value = false;
      dockerStartedAt.value = null;
      if (dockerRetryTimer !== null) {
        window.clearTimeout(dockerRetryTimer);
        dockerRetryTimer = null;
      }
    };
    try {
      await ipc.startDocker();
      // Docker Desktop takes a while to boot the engine (first run: license
      // dialog + WSL init, ~30-60s); probe every 3s for up to ~2 min
      // instead of one-shot.
      const deadline = Date.now() + 120_000;
      const attempt = async (): Promise<void> => {
        if (await probeDockerPreflight()) {
          stop();
          return;
        }
        if (Date.now() < deadline) {
          dockerRetryTimer = window.setTimeout(attempt, 3_000);
        } else {
          stop();
          error.value = {
            code: "WB_ERR_DOCKER_START_TIMEOUT",
            message: i18n.global.t("runtime.dockerTimeout"),
            technical_detail: null,
            retryable: true,
            action: "start_docker",
          };
        }
      };
      await attempt();
    } catch (e) {
      stop();
      error.value = e as WorkbenchError;
    }
  }

  /** One docker-boot probe: run the preflight CLI WITHOUT the status churn of
   * `runPreflight` (no summary→preflight→summary view swap, no scheduleSave).
   * Returns whether the docker check passes; routes a discovered runtime
   * conflict to the conflict manager exactly like runPreflight. */
  async function probeDockerPreflight(): Promise<boolean> {
    if (!runtimeId.value || !workspace.value.trim()) return false;
    try {
      const report = await ipc.runtimePreflight(
        workspace.value.trim(),
        runtimeId.value,
        launch.value.image,
        launch.value.network,
        launch.value.scope
      );
      preflight.value = report;
      const dockerOk = report.checks.some(
        (c) => c.id === "docker" && c.status === "pass"
      );
      if (dockerOk) {
        const runtimeConflictFailed = report.checks.some(
          (c) => c.id === "runtime_conflict" && c.status === "fail"
        );
        if (runtimeConflictFailed) {
          status.value = "conflict";
          void loadConflicts();
        }
        return true;
      }
      return false;
    } catch {
      return false; // engine still starting - the loop retries
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
  /** S5/#28: semantic snapshot equality. `observed_at` changes on every poll
   *  by construction — everything ELSE must match for "nothing happened". */
  function snapshotSemanticallyEqual(a: RuntimeSnapshot, b: RuntimeSnapshot): boolean {
    const { observed_at: _ao, ...ra } = a;
    const { observed_at: _bo, ...rb } = b;
    return JSON.stringify(ra) === JSON.stringify(rb);
  }

  function applyRuntimeSnapshot(snap: RuntimeSnapshot, seq: number) {
    if (seq < lastAppliedSeq.value) return; // stale response
    // v2.1.7 S5/#28: an observation with IDENTICAL content must not re-enter
    // reactivity. The 5s poll assigned a fresh object identity every tick,
    // invalidating every consumer that touches the snapshot — on low-GPU
    // (nested-VM) renderers that read as whole-window flicker. serde structs
    // serialize deterministically, so the (observed_at-stripped) JSON compare
    // is a reliable value gate; identity + revision only change when
    // something actually did.
    const prev = runtimeSnapshot.value;
    if (prev !== null && snapshotSemanticallyEqual(prev, snap)) {
      freshness.value = "fresh";
      lastAppliedSeq.value = seq;
      return;
    }
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
  /** G-05 (Step 8): only user-initiated refreshes surface the 刷新中 label -
   * background poll cycles must not flip the button every 5s (user report
   * 2026-08-10). */
  const userRefreshInFlight = ref(false);

  async function refreshRuntime(userInitiated = false) {
    if (!runtimeId.value || !workspace.value.trim()) return;
    if (inspectInFlight.value) return;
    if (userInitiated) userRefreshInFlight.value = true;
    inspectInFlight.value = true;
    const seq = ++requestSeq.value;
    try {
      const snap = await ipc.runtimeInspect(workspace.value.trim(), runtimeId.value);
      applyRuntimeSnapshot(snap, seq);
    } catch {
      markStale();
    } finally {
      inspectInFlight.value = false;
      if (userInitiated) userRefreshInFlight.value = false;
    }
    // svc-4: keep the Services panel in step with the snapshot (best-effort,
    // never blocks the inspect path). Stopped/cleared runtimes clear below.
    void refreshWebServices();
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

  // --- svc-4: runtime web services (aisc.runtime-services/v1) ---

  /** Fetch gateway + service list. A stopped/removed runtime is a valid
   * (non-error) observation: the payload reports the unavailable gateway
   * and an empty list, which is exactly what the panel should show. */
  async function refreshWebServices() {
    if (!runtimeId.value || !workspace.value.trim()) return;
    if (webServicesInFlight.value) return;
    webServicesInFlight.value = true;
    try {
      const result = await ipc.runtimeServices(workspace.value.trim(), runtimeId.value);
      // S5/#28: same value-gate as applyRuntimeSnapshot (observed_at
      // stripped) — the services poll also rides the 5s tick and must not
      // hand consumers a fresh object identity when nothing changed.
      const stripTs = (r: RuntimeServicesResult) => {
        const { observed_at: _t, ...rest } = r;
        return JSON.stringify(rest);
      };
      if (
        webServices.value === null ||
        stripTs(webServices.value) !== stripTs(result)
      ) {
        webServices.value = result;
      }
      webServicesError.value = null;
    } catch (e) {
      // Old CLI (no runtime services capability) or transport failure — keep
      // the last good payload; the panel gates on the capability anyway.
      webServicesError.value = e as WorkbenchError;
    } finally {
      webServicesInFlight.value = false;
    }
  }

  /** Open one registered service's canonical URL. Ids only — the backend
   * re-resolves, validates and hands the URL to the OS opener. */
  async function openWebService(port: number): Promise<void> {
    if (!runtimeId.value || !workspace.value.trim()) return;
    try {
      await ipc.openRuntimeServiceUrl(workspace.value.trim(), runtimeId.value, port);
      await refreshWebServices();
    } catch (e) {
      webServicesError.value = e as WorkbenchError;
    }
  }

  function clearWebServices() {
    webServices.value = null;
    webServicesError.value = null;
    webServicesInFlight.value = false;
  }

  // --- S2.4.a: history persistence (02 §九) ---
  // IDEA-3 (3a): the load/debounce/save cycle is shell-owned; the instance
  // only builds its own patch record and reports dirtiness through deps.

  /** Build a patch for the active workspace (runtime ref + open-tab layout).
   * Only non-idle (open) tabs are recorded so the layout reflects what was
   * actually open and S2.4.b resume can restore those agents. Other workspaces
   * on disk are preserved by the backend merge (02 §九). */
  function buildPatch(hist: WorkbenchHistory | null): HistoryPatch {
    const openTabs = tabs.value.filter((t) => t.sessionState !== "idle");
    // A-G08-3: saved layout records are truncated at the per-Runtime leaf cap
    // (defensive - createTab already refuses the 9th) with a warning.
    const overCap = openTabs.length - MAX_TABS;
    if (overCap > 0) console.warn(`[g08] ${overCap} tab(s) beyond the ${MAX_TABS} cap truncated from history`);
    const savedTabs = openTabs.slice(0, MAX_TABS);
    const tabsRecord = savedTabs.map((t, i) => ({
      tab_id: t.tabId,
      agent: t.agent,
      title: t.title,
      position: i,
      // G-17: persist the split tree; `agent` stays as the flat fallback
      // (03 §6.3 - the v2 writer keeps it in sync via syncProjection).
      ...(t.tree
        ? {
            split_layout: {
              version: 1,
              active_pane_id: t.activePaneId,
              root: internalToPersisted(t.tree),
            },
          }
        : {}),
    }));
    const activeAgent =
      tabs.value.find((t) => t.tabId === activeTabId.value)?.agent ?? tabs.value[0]?.agent ?? "bash";
    const activeTabIdRec = openTabs.some((t) => t.tabId === activeTabId.value)
      ? activeTabId.value
      : null;
    const pathKey = normalizePath(workspace.value);
    // G-07 refinement: stop/start resets empty `tabs` (as does a fresh app
    // start), but the last open layout must survive so 恢复布局 can re-open
    // those sessions. Individual tab closes never empty the array - the only
    // writers are the resets - so an empty array here means "nothing open
    // because of a reset", and the previous layout is preserved.
    const layout: Layout | null =
      tabsRecord.length > 0
        ? { active_tab_id: activeTabIdRec, tabs: tabsRecord }
        : (hist?.workspaces.find((w) => sameWorkspace(w.path, pathKey))?.layout ?? null);
    const rec: WorkspaceRecord = {
      path: pathKey,
      last_used_at: new Date().toISOString(),
      pinned: false,
      last_agent: activeAgent,
      runtime: lastRuntimeRef.value,
      layout,
    };
    return { workspaces: [rec] };
  }

  /** Debounce saves so rapid tab/layout changes coalesce. IDEA-3 (3a): the
   * instance no longer owns the save cycle - dirtiness goes to the shell,
   * which guards on the workspace path and debounces the merged patch. */
  function scheduleSave() {
    deps.markDirty();
  }

  /** Select a recent workspace from history: restore its last launch config
   * (image/network/scope/agent) + runtime ref (02 §六 priority: the workspace's
   * last confirmed config beats the built-in default), then preflight. This
   * makes preflight match the existing runtime (reuse/restart) instead of
   * spurious-conflicting with the default image. */
  function selectRecentWorkspace(path: string) {
    const rec = (deps.getHistory()?.workspaces ?? []).find((w) => w.path === path);
    if (rec) {
      if (rec.runtime) {
        launch.value.image = rec.runtime.image;
        launch.value.network = rec.runtime.network as LaunchConfig["network"];
        launch.value.scope = rec.runtime.scope as LaunchConfig["scope"];
        lastRuntimeRef.value = rec.runtime;
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

  function retryFromConflict() {
    conflicts.value = [];
    conflictError.value = null;
    preflight.value = null;
    runtimeId.value = ""; // re-discover (or fresh id) on the next preflight
    status.value = "preflight";
    void runPreflight();
  }

  // --- S2.2.a: multi-tab session lifecycle (03 §五/§六) ---

  /** Build tabs from TabRecords and open fresh sessions (new id, never
   * reattaching a PTY - 03 §六). Fresh start passes the fixed 4 records and
   * opens only the requested agents; Stage 5 lazy restore passes the history
   * records with `lazy: true` — only the ACTIVE tab opens sessions, the rest
   * become dormant placeholders that wake on activation (01 §4.2). */
  async function initTabs(
    records: TabRecord[],
    opts: {
      activeSavedId?: string | null;
      activeAgent?: LaunchAgent | null;
      openAgents?: LaunchAgent[];
      lazy?: boolean;
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
    ccSwitchUiTabOpen.value = false; // fresh tab set; the virtual tab never restores
    // G-17: open EVERY pane leaf (a restored split tab has several), each
    // through the same provider gate as + menu tabs - unconfigured claude/
    // codex restore as guide without a session (A-G08-3). `openAgents`
    // filters the pane types to open (fresh start opens only the requested).
    activeTabId.value = resolveActiveTabId(created, bySavedId, {
      activeSavedId: opts.activeSavedId,
      activeAgent: opts.activeAgent,
    });
    const gates: Promise<void>[] = [];
    for (const tab of created) {
      if (opts.lazy && tab.tabId !== activeTabId.value) {
        // Stage 5 (01 §4.2): dormant placeholder — no session until the tab
        // is activated; closing it only touches history (never terminate).
        for (const pane of Object.values(tab.panes)) {
          pane.sessionState = "dormant";
        }
        syncProjection(tab);
        continue;
      }
      for (const leaf of listLeaves(tab.tree)) {
        if (opts.openAgents && !opts.openAgents.includes(leaf.sessionType)) continue;
        // bash/cc-switch open synchronously ("starting"); claude/codex await a
        // provider query. Wait for the latter so a restored claude/codex pane
        // resolves to guide/session BEFORE "ready" - never a dormant flash
        // (G-17 feedback 2026-08-10). Bounded so a hung query can't block start.
        if (leaf.sessionType === "claude" || leaf.sessionType === "codex") {
          gates.push(maybeOpenPaneCreated(tab, leaf.paneId, leaf.sessionType));
        } else {
          void maybeOpenPaneCreated(tab, leaf.paneId, leaf.sessionType);
        }
      }
      syncProjection(tab);
    }
    if (gates.length > 0) {
      await Promise.race([
        Promise.all(gates),
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]);
    }
    status.value = "ready";
    scheduleSave();
    deps.onReady?.(); // 3c: the launcher materializes into a workspace here
  }

  /** Stage 5 (01 §4.2): activating a dormant tab wakes its placeholder
   * panes — fresh sessions through the same provider gates as a + menu tab.
   * Re-activation is a no-op (starting/running panes bail inside the gate). */
  function wakeDormantTab(tab: Tab): void {
    for (const leaf of listLeaves(tab.tree)) {
      const p = tab.panes[leaf.paneId];
      if (!p || p.sessionState !== "dormant") continue;
      p.sessionState = "idle";
      void maybeOpenPaneCreated(tab, leaf.paneId, leaf.sessionType);
    }
    syncProjection(tab);
  }

  function findTab(tabId: string): Tab | undefined {
    return tabs.value.find((t) => t.tabId === tabId);
  }

  // --- G-17 (Step 16): pane-aware session ops ---

  /** The active pane's live runtime (created on demand). */
  function activePane(tab: Tab): PaneRuntime {
    let p = tab.panes[tab.activePaneId];
    if (!p) {
      p = { sessionId: null, sessionState: "idle", exit: null };
      tab.panes[tab.activePaneId] = p;
    }
    return p;
  }

  /** Mirror the active pane onto the tab-level projection (sessionId/state/exit
   * + agent from the active leaf), so TabBar/sidebar/title/Terminal keep working
   * unchanged. Single-pane tabs are exact; split tabs show the active pane. */
  function syncProjection(tab: Tab) {
    const leaf = findLeaf(tab.tree, tab.activePaneId) ?? firstLeaf(tab.tree);
    if (leaf) {
      tab.agent = leaf.sessionType;
      // Tab-bar label follows the active leaf too: closing the bash pane off a
      // bash|claude split leaves a claude tab labelled Claude, not the stale
      // Bash set at creation time (03 §6.3 keeps agent + title in sync).
      tab.title = AGENT_TITLE[leaf.sessionType] ?? tab.title;
    }
    const p = tab.panes[tab.activePaneId];
    if (p) {
      tab.sessionId = p.sessionId;
      tab.sessionState = p.sessionState;
      tab.exit = p.exit;
    }
  }

  /** Set the active pane's session state and re-sync the projection. */
  function setActivePaneState(tab: Tab, patch: Partial<PaneRuntime>): void {
    Object.assign(activePane(tab), patch);
    syncProjection(tab);
  }

  /** The tab that owns a pane (pane id -> tab). */
  function tabForPane(paneId: string): Tab | undefined {
    return tabs.value.find((t) => t.panes[paneId]);
  }

  /** Total leaf count across all tabs (A-G17-6: <=8 per Runtime/Workbench). */
  function totalLeaves(): number {
    return tabs.value.reduce((n, t) => n + leafCount(t.tree), 0);
  }

  /** Total resource-holding panes (starting/running/closing; A-G17-6). */
  function totalResources(): number {
    return tabs.value.reduce(
      (n, t) =>
        n +
        Object.values(t.panes).filter((p) =>
          ["starting", "running", "closing"].includes(p.sessionState)
        ).length,
      0
    );
  }

  // --- G-17 (Step 16): split / close-pane / ratio ---

  /** Open a pane's session by id (fresh session_id, `starting`). The STORE owns
   * the session channel + output buffer so a Terminal remount (e.g. a split
   * restructuring the tree) never re-opens or drops the session (A-G17-2:
   * open failure keeps a failed pane). */
  async function openPane(tab: Tab, paneId: string) {
    const p = tab.panes[paneId];
    if (!p || p.sessionState === "starting" || p.sessionState === "running") return;
    const agent = findLeaf(tab.tree, paneId)?.sessionType;
    if (!agent || !runtimeId.value) return;
    const sid = uuid();
    p.sessionId = sid;
    p.sessionState = "starting";
    p.exit = null;
    paneStreams.value[paneId] = []; // reset the per-pane output buffer
    paneByteCounts[paneId] = 0;
    streamCursor.value[paneId] = 0;
    paneStreamMeta.value[paneId] = { truncated: false, truncatedBytes: 0 };
    pendingChunks[paneId] = [];
    syncProjection(tab);
    const ch = new Channel<PtyEvent>();
    ch.onmessage = (ev) => {
      // S1.4 (F-R04): a stale channel from a closed/reopened session must not
      // mutate the current pane. The pane's sessionId moves on reopen; events
      // belonging to an older session are dropped (and not counted as output
      // proving liveness).
      if (p.sessionId !== sid) return;
      if (ev.type === "output") {
        // First output proves the PTY is live: promote a `starting` pane to
        // running. The invoke response can lag the channel delivery, leaving
        // the tab bar on 启动中 while bash is already showing output
        // (G-17 feedback 2026-08-10).
        onTabOpenOk(paneId);
        // S1.3: buffer into the non-reactive pending queue; a single rAF flush
        // applies budget + emits one reactive replacement.
        (pendingChunks[paneId] ??= []).push(ev.bytes);
        scheduleStreamFlush();
      } else if (ev.type === "exit") {
        if (!p.exit) {
          p.exit = { reason: ev.reason, exitCode: ev.exitCode };
          p.sessionState = ev.reason === "transport_error" ? "disconnected" : "exited";
          syncProjection(tab);
          void ipc.ackSessionExit(sid).catch(() => null);
        }
      } else if (ev.type === "error") {
        if (!TERMINAL_STATES.includes(p.sessionState)) {
          p.sessionState = "failed";
          syncProjection(tab);
        }
      }
    };
    try {
      await ipc.openSession(runtimeId.value, sid, agent, workspace.value.trim(), ch);
      if (p.sessionState === "starting") {
        p.sessionState = "running";
        syncProjection(tab);
      }
    } catch {
      if (p.sessionState === "starting") {
        p.sessionState = "failed";
        syncProjection(tab);
      }
    }
  }

  /** Split the tab's active pane, activating + opening the new pane. Refused
   * (tree unchanged) when the global leaf cap or the tree depth cap is hit
   * (A-G17-2/6); `sizeOk` is the pane's measured minimum size check (240x160,
   * evaluated by the UI before calling). */
  function splitTabPane(
    tabId: string,
    axis: SplitAxis,
    sessionType: LaunchAgent,
    sizeOk = true,
    targetPaneId?: string
  ): string | null {
    const tab = findTab(tabId);
    if (!tab || !sizeOk) return null;
    // A-G17-6: leaf cap + resource cap (the new pane will hold a session).
    if (totalLeaves() >= MAX_PANES || totalResources() >= MAX_PANES) return null;
    const target = targetPaneId ?? tab.activePaneId;
    const newPaneId = uuid();
    const tree = splitLeaf(tab.tree, target, newPaneId, axis, sessionType, DEFAULT_RATIO);
    if (!tree) return null;
    tab.tree = tree;
    tab.panes[newPaneId] = { sessionId: null, sessionState: "idle", exit: null };
    tab.activePaneId = newPaneId;
    syncProjection(tab);
    scheduleSave();
    void maybeOpenPaneCreated(tab, newPaneId, sessionType);
    return newPaneId;
  }

  /** G-12 gate for a freshly created/split pane (claude/codex may route to
   * guide before any session is opened). */
  async function maybeOpenPaneCreated(tab: Tab, paneId: string, agent: LaunchAgent) {
    if (agent === "claude" || agent === "codex") {
      await loadProviderStatus(agent);
      const st = providerStatuses.value[agent];
      const p = tab.panes[paneId];
      if (!p || p.sessionState === "starting" || p.sessionState === "running") return;
      if (!st || ["not_configured", "login_required", "unknown"].includes(st.auth_status)) {
        p.sessionState = "guide";
        p.sessionId = null;
        syncProjection(tab);
        return;
      }
    }
    void openPane(tab, paneId);
  }

  /** Set the tab's active pane and sync the projection (A-G17-5). */
  function setActivePane(tabId: string, paneId: string) {
    const tab = findTab(tabId);
    if (!tab || !tab.panes[paneId]) return;
    tab.activePaneId = paneId;
    syncProjection(tab);
    scheduleSave();
  }

  /** G-17: move keyboard focus to the spatial neighbor (Ctrl+arrows/hjkl).
   * Returns whether focus moved (no move = the caller lets the key fall through
   * to the terminal, e.g. Ctrl+h stays a backspace at a pane edge). */
  function navigatePane(tabId: string, dir: NavDir): boolean {
    const tab = findTab(tabId);
    if (!tab) return false;
    const target = navigateLeaf(tab.tree, tab.activePaneId, dir);
    if (!target) return false;
    setActivePane(tabId, target);
    return true;
  }

  /** Set a split's ratio by its key (divider drag/keyboard, A-G17-4). */
  function setSplitRatio(tabId: string, splitKeyId: string, ratio: number) {
    const tab = findTab(tabId);
    if (!tab) return;
    tab.tree = setRatioBySplitKey(tab.tree, splitKeyId, ratio);
    scheduleSave();
  }

  /** Close a pane: terminate its session, remove the leaf and compress the
   * parent split (A-G17-5). Closing the LAST pane keeps the tab with a single
   * dormant leaf of the same type (03 §6.1) instead of deleting the tab. */
  async function closePane(tabId: string, paneId: string) {
    const tab = findTab(tabId);
    if (!tab || !tab.panes[paneId]) return;
    const p = tab.panes[paneId];
    if (
      p.sessionId &&
      !TERMINAL_STATES.includes(p.sessionState) &&
      p.sessionState !== "closing"
    ) {
      p.sessionState = "closing";
      void ipc.closeSession(p.sessionId).catch(() => null);
    }
    const removed = removeLeaf(tab.tree, paneId);
    delete tab.panes[paneId];
    if (removed === null) {
      // Last pane: keep the tab as a single dormant leaf (same session type).
      const type = (findLeaf(tab.tree, paneId) ?? firstLeaf(tab.tree))?.sessionType ?? tab.agent;
      const newPaneId = uuid();
      tab.tree = singleLeaf(newPaneId, type);
      tab.panes[newPaneId] = { sessionId: null, sessionState: "idle", exit: null };
      tab.activePaneId = newPaneId;
    } else {
      tab.tree = removed;
      // Active pane may have been removed; fall back to the first leaf.
      if (!tab.panes[tab.activePaneId]) {
        tab.activePaneId = firstLeaf(tab.tree)?.paneId ?? "";
      }
    }
    syncProjection(tab);
    scheduleSave();
  }

  /** Open (or reopen) a tab's session: binds the tab's ACTIVE pane via the
   * store-owned session channel (openPane). G-17. */
  function openTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    activeTabId.value = tabId;
    void openPane(tab, tab.activePaneId);
    scheduleSave();
  }

  /** Activate a tab; idle tabs are opened on first activation. */
  function activateTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    activeTabId.value = tabId;
    // Stage 5: first activation of a dormant placeholder opens its sessions.
    if (Object.values(tab.panes).some((p) => p.sessionState === "dormant")) {
      wakeDormantTab(tab);
      scheduleSave();
      return;
    }
    if (activePane(tab).sessionState === "idle") openTab(tabId);
    scheduleSave();
  }

  /** Reopen an exited/failed/disconnected tab with a fresh session. */
  function reopenTab(tabId: string) {
    openTab(tabId);
  }

  /** G-08 (Step 5): create a dynamic tab (A-G08-1/8). Refused beyond the
   * per-Runtime leaf cap. The tab opens immediately (Step 5c routes
   * unconfigured claude/codex to the guide state instead). */
  function createTab(agent: LaunchAgent): string | null {
    // G-17 (A-G17-6): the global leaf cap governs (a split tab holds >1 leaf).
    if (totalLeaves() >= MAX_PANES) return null;
    const tabId = uuid();
    tabs.value.push(newPaneTab(tabId, agent, AGENT_TITLE[agent], null));
    activeTabId.value = tabId;
    void maybeOpenCreated(tabId, agent);
    scheduleSave();
    return tabId;
  }

  /** G-08 (A-G08-2): claude/codex tabs first query their provider (deduped by
   * type). Unconfigured providers route the tab to the guide state without
   * calling open_session; bash/cc-switch open immediately.
   *
   * Step 8 (04 §三 rule table): login_required and unknown ALSO route to the
   * guide state (supersedes the 2026-08-10 decision that login_required opened
   * directly - the spec now requires the conservative flow). */
  async function maybeOpenCreated(tabId: string, agent: LaunchAgent) {
    if (agent === "claude" || agent === "codex") {
      await loadProviderStatus(agent);
      const st = providerStatuses.value[agent];
      const tab = findTab(tabId);
      if (!tab || activePane(tab).sessionState !== "idle") return;
      if (!st || ["not_configured", "login_required", "unknown"].includes(st.auth_status)) {
        setActivePaneState(tab, { sessionState: "guide" });
        return;
      }
    }
    openTab(tabId);
  }

  /** G-12 (Step 8): activate an existing cc-switch tab or create one -
   * shared by the sidebar auth action and the guide banner. */
  function openCcSwitch() {
    const existing = tabs.value.find((t) => t.agent === "cc-switch");
    if (existing) activateTab(existing.tabId);
    else createTab("cc-switch");
  }

  /** G-08: remove a tab entirely (× button). Live sessions are closed
   * best-effort (the PTY Exit event finalizes; Rust reaps); guide/idle tabs
   * have nothing to terminate. Active-tab focus falls to the right neighbor,
   * then the left, then the empty state (A-G08-6). */
  /** Close every live session in a tab's tree (tab × button; A-G17-6 full-path
   * recycle). Best-effort: the PTY Exit event finalizes; Rust reaps. */
  function closeTabSessions(tab: Tab) {
    for (const p of Object.values(tab.panes)) {
      if (
        p.sessionId &&
        !TERMINAL_STATES.includes(p.sessionState) &&
        p.sessionState !== "closing"
      ) {
        p.sessionState = "closing";
        void ipc.closeSession(p.sessionId).catch(() => null);
      }
    }
    syncProjection(tab);
  }

  async function removeTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    closeTabSessions(tab);
    const idx = tabs.value.indexOf(tab);
    tabs.value.splice(idx, 1);
    if (activeTabId.value === tabId) {
      activeTabId.value = tabs.value[Math.min(idx, tabs.value.length - 1)]?.tabId ?? null;
    }
    scheduleSave();
  }

  // --- Stage 8e: the virtual cc-switch Provider UI tab (no session, never
  // persisted). The IDEA-1 Settings tab moved to the WORKSPACE layer (3d). ---

  function openCcSwitchUiTab() {
    ccSwitchUiTabOpen.value = true;
    activeTabId.value = CC_SWITCH_UI_TAB_ID;
  }

  function closeCcSwitchUiTab() {
    ccSwitchUiTabOpen.value = false;
    if (activeTabId.value === CC_SWITCH_UI_TAB_ID) {
      activeTabId.value = tabs.value[tabs.value.length - 1]?.tabId ?? null;
    }
  }

  /** Close a running/starting tab: terminate the active pane's session. The PTY
   * Exit event (single authoritative signal, 03 §五.2) finalizes the state via
   * onTabSessionExit; close_session guarantees the child is reaped. */
  async function closeTab(tabId: string) {
    const tab = findTab(tabId);
    if (!tab) return;
    const p = activePane(tab);
    if (!p.sessionId) return;
    if (TERMINAL_STATES.includes(p.sessionState) || p.sessionState === "closing") return;
    p.sessionState = "closing";
    syncProjection(tab);
    try {
      await ipc.closeSession(p.sessionId);
    } catch {
      /* best-effort; Exit event still finalizes if the child is reaped */
    }
  }

  /** Pane-aware session callbacks: for a single-pane tab paneId === tabId, so
   * callers may pass either. */
  function onTabOpenOk(paneId: string) {
    const tab = tabForPane(paneId);
    if (!tab) return;
    const p = tab.panes[paneId];
    if (p && p.sessionState === "starting") {
      p.sessionState = "running";
      syncProjection(tab);
    }
  }

  function onTabOpenFail(paneId: string) {
    const tab = tabForPane(paneId);
    if (!tab) return;
    const p = tab.panes[paneId];
    if (!p || TERMINAL_STATES.includes(p.sessionState)) return; // already finalized
    p.sessionState = "failed";
    syncProjection(tab);
    // exit stays null; the Terminal writes the open error inline.
  }

  /** PTY Exit event (process_exit / user_close / transport_error). Applied
   * once per pane (idempotent) - duplicate Exit/terminate results merge. After
   * the pane state is committed, ack the backend so the terminal registry
   * entry can be evicted (03 §3.3.2; idempotent on both sides). */
  function onTabSessionExit(paneId: string, reason: string, exitCode: number | null) {
    const tab = tabForPane(paneId);
    if (!tab) return;
    const p = tab.panes[paneId];
    if (!p || p.exit) return; // first writer wins (03 §五.2)
    const exit: TabExit = { reason, exitCode };
    p.exit = exit;
    p.sessionState = reason === "transport_error" ? "disconnected" : "exited";
    syncProjection(tab);
    if (p.sessionId) {
      void ipc.ackSessionExit(p.sessionId).catch(() => null); // TTL sweeps if lost
    }
  }

  /** Ensure the runtime is ready per preflight's recommended_action (start /
   * reuse / restart). Returns false for resolve_conflict (Start is disabled by
   * the config gate; defensive). Used by startFromSummary.
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
      lazy?: boolean;
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
        void ipc.logUiEvent?.("launch", "error", "WB_ERR_RUNTIME_CONFLICT");
        void loadConflicts();
        return;
      }
      stopTimer();
      runtimeReady.value = true;
      // runtime-lifecycle-ux Stage 3 (01 §2.1): materialize = claim the
      // workspace lease; the Rust supervisor starts heartbeating (never JS
      // timers — they throttle under tray-hide). A claim loss after this
      // surfaces via the workspace-lease-conflict event; failure here is
      // logged, not fatal (the next reconcile short-circuits us out).
      try {
        await ipc.leaseClaim(workspace.value.trim());
      } catch (e) {
        void ipc.logUiEvent?.("lease_claim", "error", (e as WorkbenchError)?.code ?? undefined);
      }
      await initTabs(records, opts);
      void ipc.logUiEvent?.("launch", "ok");
    } catch (e) {
      stopTimer();
      const err = e as WorkbenchError;
      void ipc.logUiEvent?.("launch", "error", err?.code ?? undefined);
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
    // Stage 5 (01 §4.2): the saved layout restores as dormant placeholders —
    // only the active tab opens a session now; the rest wake on activation.
    // No layout (first open / cleared) falls back to the G-08 single Bash
    // tab; more tabs come from the + menu.
    const rec = (deps.getHistory()?.workspaces ?? []).find((w) =>
      sameWorkspace(w.path, workspace.value)
    );
    const histTabs = rec?.layout?.tabs ?? [];
    if (histTabs.length > 0) {
      const records = [...histTabs]
        .sort((a, b) => a.position - b.position)
        .slice(0, MAX_TABS);
      await launchRuntime(records, {
        activeSavedId: rec?.layout?.active_tab_id ?? null,
        lazy: true,
      });
      return;
    }
    const records: TabRecord[] = [
      { tab_id: uuid(), agent: "bash", title: AGENT_TITLE["bash"], position: 0 },
    ];
    await launchRuntime(records, { openAgents: ["bash"], activeAgent: "bash" });
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
      await ipc.cancelRuntimeStart(runtimeId.value);
    } catch {
      /* swallow; startFromSummary will resolve with cancelled */
    }
  }

  /** runtime-lifecycle-ux Stage 3 (01 §2.2/§7): the ephemeral teardown —
   * stop -> inspect-verify -> REMOVE (container + registry) -> release the
   * workspace lease. Idempotent (not_found is success); failures throw for
   * the caller to log — a leftover is auto-recycled by the next reconcile,
   * never re-surfaced as a user-facing conflict. */
  async function teardownRuntimeAndRelease(wsPath: string, rid: string): Promise<void> {
    if (!rid) {
      void ipc.leaseRelease(wsPath).catch(() => null);
      return;
    }
    const snap = await ipc.stopRuntime(wsPath, rid);
    // Only trust an observation: inspect until stopped/not_found.
    if (["running", "stopping", "unknown"].includes(snap.state)) {
      const insp = await ipc.runtimeInspect(wsPath, rid);
      if (!["stopped", "not_found"].includes(insp.state)) {
        throw {
          code: "WB_ERR_RUNTIME_NOT_STOPPED",
          message: i18n.global.t("runtime.notStopped", { state: insp.state }),
          technical_detail: null,
          retryable: true,
          action: "retry",
        } as WorkbenchError;
      }
    }
    // remove is idempotent (not_found -> success); force covers a racing
    // start between the stop above and here.
    await ipc.removeRuntime(wsPath, rid, true);
    void ipc.leaseRelease(wsPath).catch(() => null);
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
      await teardownRuntimeAndRelease(workspace.value.trim(), runtimeId.value);
    } catch {
      /* best-effort: next reconcile auto-recycles the leftover */
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
        ? i18n.global.t("runtime.stopWithSessions", { count: live.length })
        : i18n.global.t("runtime.stopPlain")
    );
    if (!ok) return;
    status.value = "stopping";
    // G-07 (2026-08-10): persist the CURRENT tab layout before it is cleared
    // below - if the 300ms debounce had not fired yet, clearing tabs would lose
    // this session's layout and 恢复布局 would fall back to a previous one.
    await deps.flushSave();
    // Staged concurrent stop (03 §4.2): start every session close in
    // parallel, but do not wait for all of them - wait at most 400ms for the
    // terminate CLI spawns, then stop the runtime (container-side sessions
    // are considered terminated once stop confirms; Rust keeps reaping the
    // local PTY children). Stop is confirmed by a follow-up inspect.
    const closing = tabs.value.filter(
      (t) => t.sessionId && !TERMINAL_STATES.includes(t.sessionState) && t.sessionState !== "closing"
    );
    const closePromises = closing.map((t) => ipc.closeSession(t.sessionId!).catch(() => null));
    await Promise.race([
      Promise.all(closePromises),
      new Promise((resolve) => setTimeout(resolve, 400)),
    ]);
    tabs.value = [];
    activeTabId.value = null;
    ccSwitchUiTabOpen.value = false;
    try {
      // runtime-lifecycle-ux Stage 3: stop-only became the ephemeral teardown
      // (stop -> verify -> remove -> lease release) — a manually stopped
      // workspace leaves nothing behind to conflict with the next launch.
      await teardownRuntimeAndRelease(workspace.value.trim(), runtimeId.value);
    } catch (e) {
      status.value = "error";
      error.value = e as WorkbenchError;
      void ipc.logUiEvent?.("stop", "error", (e as WorkbenchError)?.code ?? undefined);
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
    // svc-4: stop/remove immediately clears any openable service state.
    clearWebServices();
    preflight.value = null;
    status.value = "picker";
    void ipc.logUiEvent?.("stop", "ok");
  }

  /** B-05 (terminal stability): a rejected resize_session on the shared
   *  timeline. Store choke point per the P4.5 layer contract — components
   *  never import logUiEvent directly. */
  function logTerminalResizeError(code?: string): void {
    void ipc.logUiEvent?.("terminal_resize", "error", code);
  }

  return {
    id,
    status,
    error,
    workspace,
    runtimeId,
    runtimeReady,
    preflight,
    reconcile,
    logTerminalResizeError,
    launch,
    showAdvanced,
    startElapsedMs,
    cancelInspect,
    buildStatus,
    buildLog,
  buildProgress,
  buildLogPath,
  revealBuildLog,
    buildTag,
    buildError,
    buildWarnings,
    buildStartedAt,
    buildFinishedAt,
    buildDurationMs,
    tabs,
    activeTabId,
    ccSwitchUiTabOpen,
    openCcSwitchUiTab,
    closeCcSwitchUiTab,
    runtimeState,
    runtimeSnapshot,
    conflicts,
    conflictError,
    freshness,
    inspectInFlight,
    providerStatuses,
    providerError,
    providerInFlight,
    webServices,
    webServicesError,
    webServicesInFlight,
    refreshWebServices,
    openWebService,
    clearWebServices,
    buildPatch,
    pickWorkspace,
    backToPicker,
    startBuild,
    cancelBuild,
    backToSummaryFromBuild,
    runPreflight,
    recomputePreflightNeeded,
    startDockerAndRepreflight,
    dockerStarting,
    dockerStartedAt,
    startFromSummary,
    cancelStart,
    keepCancelledRuntime,
    stopCancelledRuntime,
    stopRuntime,
    teardownRuntimeAndRelease,
    initTabs,
    openTab,
    splitTabPane,
    closePane,
    setActivePane,
    navigatePane,
    setSplitRatio,
    paneStreams,
    paneStreamMeta,
    streamCursor,
    activateTab,
    closeTab,
    reopenTab,
    createTab,
    removeTab,
    openCcSwitch,
    onTabOpenOk,
    onTabOpenFail,
    onTabSessionExit,
    applyRuntimeSnapshot,
    markStale,
    refreshRuntime,
    userRefreshInFlight,
    loadProviderStatus,
    clearProviderStatuses,
    selectRecentWorkspace,
    loadConflicts,
    retryFromConflict,
    resetWorkspace,
    dispose,
  };
}

/** One workspace instance's full runtime surface (state refs + actions). */
export type WorkspaceRuntime = ReturnType<typeof createWorkspaceRuntime>;
