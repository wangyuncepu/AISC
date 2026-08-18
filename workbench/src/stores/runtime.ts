import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import type {
  CapabilityReport,
  WorkbenchError,
  WorkbenchHistory,
  WorkspaceRecord,
} from "../types";
import * as ipc from "../lib/ipc";
import { i18n } from "../i18n";
import { createWorkspaceRuntime } from "./workspaceRuntime";

// IDEA-3 (3a): the sentinel ids + status domain live with the per-workspace
// state machine now; re-exported here so existing consumers keep their import
// paths (App.vue, TabBar.vue, tests).
export { CC_SWITCH_UI_TAB_ID, SETTINGS_TAB_ID } from "./workspaceRuntime";
export type { WorkbenchStatus } from "./workspaceRuntime";

/**
 * IDEA-3 (3a): the runtime store is now a FACADE over workspace instances.
 *
 * Everything workspace-shaped (status machine, tabs, panes, streams, launch
 * flow) lives in `createWorkspaceRuntime` (`./workspaceRuntime`); this store
 * owns exactly one instance plus the shell-level concerns — capability
 * negotiation, the shared workbench history (load/debounce/save cycle), and
 * the exit gate. The instance's refs and actions are spread straight into the
 * store's return, so every existing consumer (`store.tabs`, `s.tabs = [...]`,
 * `watch(() => store.activeTabId)`, method calls) keeps working unchanged —
 * the 3a gate is a green suite with ZERO test-file edits.
 *
 * 3c will swap the fixed instance for the workspaces store's active one; the
 * facade is the seam where that happens.
 */
export const useRuntimeStore = defineStore("runtime", () => {
  // --- shell-owned: capability negotiation (app-level, one CLI pin) ---
  const capability = ref<CapabilityReport | null>(null);

  // --- shell-owned: shared workbench history (02 §九) ---
  const history = ref<WorkbenchHistory | null>(null);
  const historyRevision = ref(0);
  const recentWorkspaces = computed<WorkspaceRecord[]>(() => {
    const ws = history.value?.workspaces ?? [];
    return [...ws]
      .filter((w) => w.path)
      .sort((a, b) => (b.last_used_at || "").localeCompare(a.last_used_at || ""));
  });
  let saveTimer: number | null = null;

  const inst = createWorkspaceRuntime({
    markDirty: scheduleSave,
    getHistory: () => history.value,
    flushSave,
  });

  /** Debounce saves so rapid tab/layout changes coalesce. The instance's
   * scheduleSave calls land here (IDEA-3 3a deps); the workspace guard stays
   * on the shell because "which workspaces are dirty" is a shell concern. */
  function scheduleSave() {
    if (!inst.workspace.value.trim()) return;
    if (saveTimer !== null) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      void doSave(3);
    }, 300);
  }

  /** Flush a pending debounced save immediately (used on quit - a split or
   * pane-close inside the 300ms window must survive "立即关窗口 → 恢复布局",
   * G-17 feedback 2026-08-10). Best-effort: conflict retries stay fire-and-forget. */
  function flushSave(): Promise<void> {
    if (saveTimer !== null) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
      return doSave(3);
    }
    return Promise.resolve();
  }

  async function doSave(retries: number) {
    if (!inst.workspace.value.trim()) return;
    const patch = inst.buildPatch(history.value);
    try {
      const newRev = await ipc.saveHistory(historyRevision.value, patch);
      historyRevision.value = newRev;
      // Keep the in-memory history in sync with disk: buildPatch's G-07 fallback
      // (empty tabs after a runtime stop) preserves the workspace's LAST layout,
      // and that must be the freshly-saved one - not the startup snapshot, or
      // 恢复布局 restores the wrong tabs (feedback 2026-08-10).
      try {
        const fresh = await ipc.loadHistory();
        history.value = fresh;
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

  // --- shell-owned: negotiate + exit (write the instance's status/error) ---

  async function negotiate() {
    void loadHistory(); // parallel, best-effort (02 §九)
    inst.status.value = "negotiating";
    try {
      const report = await ipc.negotiateCapabilities();
      capability.value = report;
      if (report.required_ok) {
        inst.status.value = "picker";
        inst.error.value = null;
      } else {
        inst.status.value = "blocked";
        inst.error.value = report.error;
      }
    } catch (e) {
      inst.status.value = "blocked";
      inst.error.value = e as WorkbenchError;
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
      inst.status.value = report.required_ok ? "picker" : "blocked";
      inst.error.value = report.required_ok ? null : report.error;
    } catch (e) {
      inst.status.value = "blocked";
      inst.error.value = e as WorkbenchError;
    }
  }

  /** Surface a shutdown/exit failure as a recoverable error view (03 §4.3). */
  function setExitError(message: string) {
    inst.error.value = {
      code: "WB_ERR_REAP_TIMEOUT",
      message,
      technical_detail: null,
      retryable: true,
      action: "retry",
    };
    inst.status.value = "error";
  }

  /** Exit-Workbench gate (02 §七.3): confirm if any session is live, then end
   * owned sessions (keep the runtime running). Returns whether the window may
   * close. 3c will aggregate across ALL open workspaces. */
  async function confirmExit(): Promise<boolean> {
    // G-17: count live panes across all tabs (a split tab may have several).
    const live = inst.tabs.value.flatMap((t) => Object.values(t.panes)).filter(
      (p) => p.sessionState === "running" || p.sessionState === "starting"
    );
    if (live.length === 0) return true;
    const ok = await confirm(i18n.global.t("runtime.exitConfirm", { count: live.length }));
    if (!ok) return false;
    // Cleanup is owned by shutdown_workbench (03 §4.3); no fire-and-forget here.
    return true;
  }

  return {
    capability,
    history,
    historyRevision,
    recentWorkspaces,
    negotiate,
    pickAndPinCli,
    setExitError,
    confirmExit,
    flushSave,
    loadHistory,
    // The single workspace instance, spread so its refs/actions become store
    // state verbatim (assignment + watch semantics preserved; 3c swaps this
    // fixed instance for the workspaces store's active one).
    ...inst,
  };
});
