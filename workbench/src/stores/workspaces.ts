import { defineStore } from "pinia";
import { computed, markRaw, ref, shallowRef } from "vue";
import { confirm } from "@tauri-apps/plugin-dialog";
import type {
  ForgetResult,
  ForgetPreview,
  WorkbenchError,
  WorkbenchHistory,
  WorkspaceRecord,
} from "../types";
import * as ipc from "../lib/ipc";
import { i18n } from "../i18n";
import { sameWorkspace } from "./tabLayout";
import {
  TERMINAL_STATES,
  createWorkspaceRuntime,
  SETTINGS_TAB_ID,
  NETWORK_USAGE_TAB_ID,
  type WorkspaceRuntime,
} from "./workspaceRuntime";

/** IDEA-3 (3c, user decision 2026-08-18): at most this many concurrent
 * workspaces (each = one live container + its terminals). A constant for v1;
 * a settings field is an explicit non-goal of this iteration. */
export const MAX_WORKSPACES = 3;

/**
 * IDEA-3 (3c): the workspace LAYER above the session tab bar.
 *
 * Holds the ordered list of ready workspaces (真并行: background containers
 * and agents keep running), the single-flight "new workspace" LAUNCHER (a
 * WorkspaceRuntime instance whose picker→preflight→summary→build→conflict
 * flow materializes into a workspace tab on ready), the active pointer, and
 * the shell-owned shared concerns: workbench history (merged save cycle) and
 * the aggregated exit gate.
 *
 * The `runtime` store stays the facade every component talks to — it
 * forwards to THIS store's active instance, so switching workspaces
 * re-targets TabBar/sidebar/title/terminal with zero per-component changes.
 */
export const useWorkspacesStore = defineStore("workspaces", () => {
  // --- shared workbench history (moved from the 3a facade; merged saves) ---

  const history = ref<WorkbenchHistory | null>(null);
  const historyRevision = ref(0);
  const recentWorkspaces = computed<WorkspaceRecord[]>(() => {
    const ws = history.value?.workspaces ?? [];
    return [...ws]
      .filter((w) => w.path)
      .sort((a, b) => (b.last_used_at || "").localeCompare(a.last_used_at || ""));
  });

  /** Workspace ids with unsaved changes (non-reactive bookkeeping). */
  const dirtyIds = new Set<string>();
  /** ONE debounce timer for ALL workspaces: the window opens on the first
   * dirty mark and flushes a single merged HistoryPatch (N records, one CAS
   * + revision bump — per-instance debounce loops would multiply lock/IO
   * cycles; the backend upserts by path, 02 §九). */
  let saveTimer: number | null = null;

  // --- instances ---

  // shallowRef (NOT ref): Vue's `ref()` deep-unwraps the element TYPE (and
  // pinia would deep-proxy instances through the store), both of which strip
  // the instance's ref shape. Instances are markRaw'd; list changes go
  // through whole-value replacement so shallow reactivity is sufficient.
  const runtimes = shallowRef<WorkspaceRuntime[]>([]);
  const launcher = shallowRef<WorkspaceRuntime>(mint());
  const activeId = ref<string>(launcher.value.id);
  /** The last non-launcher active id: what to fall back to when a
   * workspace-layer sentinel (settings) closes. */
  const lastWorkspaceId = ref<string>(launcher.value.id);

  // --- IDEA-3 (3d): the Settings tab at WORKSPACE level (the strip's
  // sentinel). Same contract as the session-layer virtual tabs: never
  // persisted, owns no PTY, `activeId` may hold the sentinel while open.
  // Unlike them it survives workspace switches/closes — settings is not
  // owned by any one workspace. When active, the content area shows the
  // settings pane INSTEAD of a WorkspaceView (keyed remount semantics).
  const settingsTabOpen = ref(false);

  function openSettingsTab(): void {
    settingsTabOpen.value = true;
    activeId.value = SETTINGS_TAB_ID;
  }

  function closeSettingsTab(): void {
    settingsTabOpen.value = false;
    if (activeId.value === SETTINGS_TAB_ID) {
      // Fall back to the last workspace, else the launcher (never stranded).
      const target = byId(lastWorkspaceId.value) ?? launcher.value;
      activeId.value = target.id;
    }
  }

  const settingsTabActive = computed(() => settingsTabOpen.value && activeId.value === SETTINGS_TAB_ID);

  // --- IDEA-2 (2d): the「网络与用量」panel, a second workspace-layer
  // sentinel with the same contract as Settings (never persisted, owns no
  // PTY, survives workspace switches/closes). Entered via the + ▾ menu or
  // its strip chip; no app-level shortcut in v1.
  const networkUsageTabOpen = ref(false);

  function openNetworkUsageTab(): void {
    networkUsageTabOpen.value = true;
    activeId.value = NETWORK_USAGE_TAB_ID;
  }

  function closeNetworkUsageTab(): void {
    networkUsageTabOpen.value = false;
    if (activeId.value === NETWORK_USAGE_TAB_ID) {
      const target = byId(lastWorkspaceId.value) ?? launcher.value;
      activeId.value = target.id;
    }
  }

  const networkUsageTabActive = computed(
    () => networkUsageTabOpen.value && activeId.value === NETWORK_USAGE_TAB_ID,
  );

  function mint(): WorkspaceRuntime {
    // Late-bound self: the deps closures run long after mint returns, so the
    // const-binding trick below gives them the finished instance.
    let self: WorkspaceRuntime | null = null;
    const rt = createWorkspaceRuntime({
      markDirty: () => {
        if (self) markDirty(self.id);
      },
      getHistory: () => history.value,
      flushSave: () => flushSave(),
      onReady: () => {
        if (self) onInstanceReady(self);
      },
      // runtime-lifecycle-ux (01 §1.3): the launcher's reconcile found this
      // process already materialized the workspace — focus it, tell the
      // launcher to reset silently.
      focusExistingWorkspace: (path: string) => {
        const dup = runtimes.value.find((r) => sameWorkspace(r.workspace.value, path));
        if (!dup) return false;
        activate(dup.id);
        return true;
      },
    });
    self = rt;
    // markRaw: pinia deeply proxies returned state; through that proxy the
    // instance's refs would UNWRAP (breaking the facade's .value access and
    // the factory's internal closures). markRaw keeps instances raw — their
    // refs are still reactive on their own, and runtimes/launcher/activeId
    // (the reactive shells) still track list/pointer changes. (markRaw's
    // TYPE deep-unwraps refs; the cast restores the runtime-accurate type —
    // the object is untouched at runtime.)
    return markRaw(rt) as unknown as WorkspaceRuntime;
  }

  function byId(id: string): WorkspaceRuntime | null {
    if (launcher.value.id === id) return launcher.value;
    return runtimes.value.find((r) => r.id === id) ?? null;
  }

  /** The instance the runtime facade forwards to. Never null: the launcher
   * is always present (fresh machines land on it). */
  const activeRuntime = computed<WorkspaceRuntime>(() => {
    const found = byId(activeId.value);
    if (found && found !== launcher.value) return found;
    if (found) return found;
    // active id vanished (closed workspace raced a stale id): nearest live
    // workspace, else the launcher.
    return runtimes.value.find((r) => r.id === lastWorkspaceId.value)
      ?? runtimes.value[runtimes.value.length - 1]
      ?? launcher.value;
  });

  // --- activation ---

  function activate(id: string): void {
    if (!byId(id)) return;
    activeId.value = id;
    if (id !== launcher.value.id) lastWorkspaceId.value = id;
  }

  /** Focus the launcher tab. Single-flight: the only entry to a NEW launch
   * flow. Returns false at the workspace cap (caller surfaces the notice). */
  function openLauncher(): boolean {
    if (runtimes.value.length >= MAX_WORKSPACES) return false;
    activate(launcher.value.id);
    return true;
  }

  /** Cycle workspaces (launcher rides last — it is the `+` tab; the open
   * settings sentinel rides after that). */
  function cycle(dir: 1 | -1): void {
    const ids: string[] = [...runtimes.value.map((r) => r.id), launcher.value.id];
    if (settingsTabOpen.value) ids.push(SETTINGS_TAB_ID);
    if (networkUsageTabOpen.value) ids.push(NETWORK_USAGE_TAB_ID);
    if (ids.length < 2) return;
    const i = ids.indexOf(activeId.value);
    const next = ids[(i + dir + ids.length) % ids.length]!;
    if (next === SETTINGS_TAB_ID) {
      settingsTabOpen.value = true;
      activeId.value = SETTINGS_TAB_ID;
    } else if (next === NETWORK_USAGE_TAB_ID) {
      networkUsageTabOpen.value = true;
      activeId.value = NETWORK_USAGE_TAB_ID;
    } else {
      activate(next);
    }
  }

  // --- launcher materialization (the only way a workspace is born) ---

  function onInstanceReady(inst: WorkspaceRuntime): void {
    if (inst !== launcher.value) return; // an existing workspace re-readying (restart/resume): no-op
    materialize();
  }

  /** Promote the ready launcher into a workspace tab + mint a fresh launcher.
   * Same-path duplicates adopt the EXISTING workspace (preflight's
   * runtime_conflict check prevents this in practice; this is the defensive
   * path — the just-started runtime is torn down, never the user's live one). */
  function materialize(): void {
    const from = launcher.value;
    const dup = runtimes.value.find((r) => sameWorkspace(r.workspace.value, from.workspace.value));
    if (dup) {
      activate(dup.id);
      void discardFreshInstance(from);
      return;
    }
    runtimes.value = [...runtimes.value, from];
    activate(from.id);
    // Fresh launcher for the next workspace; it starts at the picker (not
    // `idle` — activating it must never show the boot spinner).
    const fresh = mint();
    fresh.status.value = "picker";
    launcher.value = fresh;
  }

  /** Close a just-started duplicate: stop its sessions + runtime, reset the
   * launcher slot in place (best-effort — this path is defensive only). */
  async function discardFreshInstance(inst: WorkspaceRuntime): Promise<void> {
    for (const t of inst.tabs.value) {
      for (const p of Object.values(t.panes)) {
        if (p.sessionId && !TERMINAL_STATES.includes(p.sessionState) && p.sessionState !== "closing") {
          p.sessionState = "closing";
          void ipc.closeSession(p.sessionId).catch(() => null);
        }
      }
    }
    try {
      if (inst.runtimeId.value) {
        await ipc.stopRuntime(inst.workspace.value.trim(), inst.runtimeId.value);
      }
    } catch {
      /* best-effort */
    }
    inst.resetWorkspace();
    inst.status.value = "picker";
  }

  // --- close (per-workspace stopRuntime; 真并行 means each × only stops ITS
  // container — other workspaces' runtimes are untouched) ---

  async function closeWorkspace(id: string): Promise<void> {
    const inst = byId(id);
    if (!inst || inst === launcher.value) return; // the launcher has no ×
    const live = inst.tabs.value
      .flatMap((t) => Object.values(t.panes))
      .filter((p) => p.sessionState === "running" || p.sessionState === "starting");
    const ok = await confirm(
      live.length > 0
        ? i18n.global.t("runtime.stopWithSessions", { count: live.length })
        : i18n.global.t("runtime.stopPlain")
    );
    if (!ok) return;
    // G-07 (2026-08-10): persist the CURRENT layout BEFORE tabs are cleared —
    // the flush is a fast local write, done while the tabs still exist.
    await flushSave();
    // User request 2026-08-18: closing a workspace must feel like closing the
    // window — VISUALLY instant, teardown continues silently in the
    // background. Take the chip away + hand focus to the neighbor now; the
    // staged session close + stop + verify + dispose run detached below.
    const idx = runtimes.value.indexOf(inst);
    if (idx >= 0) runtimes.value = runtimes.value.filter((r) => r !== inst);
    const list = runtimes.value;
    const neighbor = list.length > 0 ? list[Math.min(idx, list.length - 1)] : launcher.value;
    activate(neighbor.id);
    void (async () => {
      // Staged concurrent stop (03 §4.2): start every session close in
      // parallel, wait at most 400ms for the terminate spawns, then tear the
      // ephemeral runtime down (runtime-lifecycle-ux 01 §2.2: stop ->
      // verify -> remove -> lease release).
      const closing = inst.tabs.value.filter(
        (t) => t.sessionId && !TERMINAL_STATES.includes(t.sessionState) && t.sessionState !== "closing"
      );
      const closePromises = closing.map((t) => ipc.closeSession(t.sessionId!).catch(() => null));
      await Promise.race([
        Promise.all(closePromises),
        new Promise((resolve) => setTimeout(resolve, 400)),
      ]);
      inst.tabs.value = [];
      inst.activeTabId.value = null;
      inst.ccSwitchUiTabOpen.value = false;
      // The workspace-level Settings sentinel deliberately survives (3d).
      try {
        if (inst.runtimeId.value) {
          await inst.teardownRuntimeAndRelease(
            inst.workspace.value.trim(), inst.runtimeId.value
          );
        }
      } catch (e) {
        // The chip is already gone; a background cleanup failure is logged
        // and the next launch's reconcile auto-recycles the leftover — it
        // never resurfaces as a user-facing conflict (01 §2.2 失败路径).
        console.error("[workspaces] background cleanup failed (next reconcile recycles):", e);
        void ipc.logUiEvent?.(
          "close_cleanup", "error", (e as WorkbenchError)?.code ?? undefined
        );
      }
      inst.dispose();
      dirtyIds.delete(inst.id);
    })();
  }

  /** Total live panes across EVERY instance (exit gate aggregation). */
  function livePaneCount(): number {
    const count = (r: WorkspaceRuntime) =>
      r.tabs.value
        .flatMap((t) => Object.values(t.panes))
        .filter((p) => p.sessionState === "running" || p.sessionState === "starting").length;
    return runtimes.value.reduce((n, r) => n + count(r), 0) + count(launcher.value);
  }

  /** Exit-Workbench gate (02 §七.3), aggregated across all open workspaces. */
  async function confirmExit(): Promise<boolean> {
    const live = livePaneCount();
    if (live === 0) return true;
    const ok = await confirm(i18n.global.t("runtime.exitConfirm", { count: live }));
    if (!ok) return false;
    // Cleanup is owned by the shutdown coordinator (03 §4.3); no
    // fire-and-forget here.
    return true;
  }

  /** runtime-lifecycle-ux Stage 3 (02 §4): the structured shutdown request's
   * runtime targets — every materialized workspace with a live runtime id.
   * Retention is the registry default (remove_on_close); the backend maps
   * per-target behavior. */
  function shutdownTargets(): Array<{ workspace: string; runtimeId: string }> {
    return runtimes.value
      .filter((r) => r.workspace.value.trim() && r.runtimeId.value)
      .map((r) => ({
        workspace: r.workspace.value.trim(),
        runtimeId: r.runtimeId.value,
      }));
  }

  // --- merged history save cycle (shell-owned; see saveTimer above) ---

  function markDirty(id: string): void {
    const inst = byId(id);
    if (!inst || !inst.workspace.value.trim()) return;
    dirtyIds.add(id);
    if (saveTimer !== null) return; // window already open — the merged flush covers this id
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      void doSave(3);
    }, 300);
  }

  /** Flush a pending debounced save immediately (quit, workspace close). */
  function flushSave(): Promise<void> {
    if (saveTimer !== null) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
      return doSave(3);
    }
    return Promise.resolve();
  }

  async function doSave(retries: number): Promise<void> {
    const ids = [...dirtyIds].filter((id) => byId(id)?.workspace.value.trim());
    if (ids.length === 0) return;
    const records = ids.flatMap((id) => byId(id)!.buildPatch(history.value).workspaces);
    try {
      const newRev = await ipc.saveHistory(historyRevision.value, { workspaces: records });
      historyRevision.value = newRev;
      ids.forEach((id) => dirtyIds.delete(id));
      // Keep the in-memory history in sync with disk (G-07 fallback reads it).
      try {
        history.value = await ipc.loadHistory();
      } catch {
        /* best-effort: memory stays on the last known snapshot */
      }
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

  async function loadHistory(): Promise<void> {
    try {
      const h = await ipc.loadHistory();
      history.value = h;
      historyRevision.value = h.revision;
    } catch {
      history.value = { schema_version: 1, revision: 0, workspaces: [] };
      historyRevision.value = 0;
    }
  }

  // --- v2.1.7 S2 (⑦⑧): forget transaction + record-only clear ---
  // The destructive path is ONE backend IPC (never chained removals in the
  // frontend); the store only supplies the current revision and refreshes
  // the shared history afterwards. CAS conflicts propagate as rejections so
  // the caller can offer a retry after loadHistory() picked up the new rev.

  async function forgetPreview(path: string): Promise<ForgetPreview> {
    return ipc.workspaceForgetPreview(path);
  }

  async function forgetWorkspace(path: string): Promise<ForgetResult> {
    try {
      return await ipc.workspaceForget(path, historyRevision.value);
    } finally {
      // Refresh even on failure so a CAS-conflict retry uses the fresh
      // revision (the caller keeps its dialog open and can retry).
      await loadHistory();
    }
  }

  /** ⑧ "clear the moved/deleted record": drops the history entry only. */
  async function clearHistoryEntry(path: string): Promise<void> {
    try {
      await ipc.workspaceHistoryRemove(path, historyRevision.value);
    } finally {
      await loadHistory();
    }
  }

  /** ⑧ click guard: does the recent's path still exist on disk? Store-routed
   *  per the layer contract (F-A01) — components never touch lib/ipc facts. */
  async function workspacePathExists(path: string): Promise<boolean> {
    try {
      return await ipc.workspacePathExists(path);
    } catch {
      // Fail-open: preflight surfaces the real error; the guard is a UX
      // nicety for the friendly moved/deleted flow, not a hard gate.
      return true;
    }
  }

  return {
    // constants/state
    runtimes,
    launcher,
    activeId,
    activeRuntime,
    // workspace-level Settings sentinel (3d)
    settingsTabOpen,
    settingsTabActive,
    openSettingsTab,
    closeSettingsTab,
    // workspace-level「网络与用量」sentinel (IDEA-2 2d)
    networkUsageTabOpen,
    networkUsageTabActive,
    openNetworkUsageTab,
    closeNetworkUsageTab,
    // history (shared)
    history,
    historyRevision,
    recentWorkspaces,
    forgetPreview,
    forgetWorkspace,
    clearHistoryEntry,
    workspacePathExists,
    // activation
    activate,
    openLauncher,
    cycle,
    // lifecycle
    closeWorkspace,
    livePaneCount,
    confirmExit,
    shutdownTargets,
    flushSave,
    loadHistory,
    byId,
  };
});
