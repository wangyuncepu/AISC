/**
 * Stage 3 (3c, WX-01/02): Workspace Explorer + Agent Artifact store.
 *
 * Lazy tree: directories are listed on demand (never a full recursion), keyed
 * by their relative path in `tree`; `expanded` tracks open directories.
 * Artifacts come from the merged Workbench index (a projection of the CLI's
 * manifest registries; the watcher's unattributed changes are separate).
 */
import { defineStore } from "pinia";
import { listen } from "@tauri-apps/api/event";
import {
  artifactList,
  artifactRefresh,
  conversationDelete,
  conversationList,
  conversationPreflight,
  conversationRename,
  workspaceCopyEntry,
  workspaceCopyPath,
  workspaceCreateDir,
  workspaceCreateFile,
  workspaceList,
  workspaceOpen,
  workspacePreview,
  workspaceRename,
  workspaceReveal,
  workspaceWatchStart,
  workspaceWatchStop,
} from "../lib/ipc";
import { useSettingsStore } from "./settings";
import type {
  ArtifactRecord,
  ConversationSummary,
  WorkspaceMutationResult,
  WorkspaceNode,
  WorkspacePreviewResult,
} from "../types";

interface WorkspaceChangeBatch {
  /** The WATCHED workspace path (IDEA-3 3e): lets the frontend drop batches
   * from a just-replaced watcher during rapid workspace switches. Absent in
   * payloads from older backends (treated as unscoped = accepted). */
  workspace?: string;
  changes: Array<{
    relative_path: string;
    change_type: string;
    kind: string;
    revision: number;
  }>;
  overflow: boolean;
  stale: boolean;
}

/** One workspace's cached Explorer state (IDEA-3 3e: per-path cache —
 * switching back restores the tree instead of re-listing from scratch). */
interface ExplorerCache {
  tree: Record<string, WorkspaceNode[]>;
  expanded: Set<string>;
  loading: Record<string, boolean>;
  loadingMore: Record<string, boolean>;
  errors: Record<string, string>;
  nextCursors: Record<string, string | null>;
  truncatedDirs: Record<string, boolean>;
  unattributed: Record<string, string>;
  stale: boolean;
}

export type ExplorerKind = "explorer" | "conversations" | "artifacts" | "services";

/** Stage 11 (D11-02/D11-03): the in-app file clipboard. Short-lived store
 *  state — copy never touches the OS text clipboard. Single source entry
 *  only; invalidated on workspace switch or when the source disappears. */
export interface ExplorerClipboard {
  workspace: string;
  sourceRelativePath: string;
  kind: "file" | "dir";
  generation: number;
}

/** Extract the stable WB_ERR_* code from an invoke rejection. The Rust side
 *  rejects with the serialized WorkbenchError struct; UI routing must key on
 *  the code, never on message text (06 §2). */
export function errorCodeOf(e: unknown): string {
  if (e && typeof e === "object" && "code" in e) {
    const code = (e as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return "";
}

/** Parent directory of a workspace-relative path ("" = root). */
function parentDirOf(relativePath: string): string {
  const idx = relativePath.lastIndexOf("/");
  return idx >= 0 ? relativePath.slice(0, idx) : "";
}

/** User-configured Explorer ignore names (`ui.explorer_ignore`). Matched
 *  against any path component (mirrors the Rust listing/watcher ignore). */
function explorerIgnoreSet(): Set<string> {
  const settings = useSettingsStore();
  return new Set(settings.doc?.ui.explorer_ignore ?? []);
}

/** Atomic-write / editor temp files (`report.md.tmp.1234`, `foo.tmp`,
 *  `foo.temp`, `file~`, `.swp`, `.#file`, `~$lock`). These are transient
 *  writes the agent renames over the real file; they must not surface as
 *  unattributed changes even if the watcher already emitted them. Mirrors the
 *  Rust watcher/listing `is_temp_file`. */
function isTempFile(relative: string): boolean {
  const name = relative.split("/").pop() ?? relative;
  if (!name) return false;
  const lower = name.toLowerCase();
  if (lower.includes(".tmp.") || lower.endsWith(".tmp") || lower.endsWith(".temp")) {
    return true;
  }
  return (
    name.endsWith("~") ||
    name.endsWith(".swp") ||
    name.endsWith(".swo") ||
    name.startsWith(".#") ||
    name.startsWith("~$")
  );
}

/** True when a workspace-relative path sits under an ignored name (or is
 *  itself a transient temp file). */
function isIgnoredPath(relative: string): boolean {
  if (isTempFile(relative)) return true;
  const ignore = explorerIgnoreSet();
  if (ignore.size === 0) return false;
  return relative.split("/").some((part) => ignore.has(part));
}

/** Non-reactive module-level cleanup handles for Tauri event subscriptions. */
let watcherUnlisteners: Array<() => void> = [];

export const useWorkspaceExplorerStore = defineStore("workspaceExplorer", {
  state: () => ({
    workspace: null as string | null,
    /** IDEA-3 (3e): per-workspace Explorer caches (switch-back is instant). */
    caches: {} as Record<string, ExplorerCache>,
    /** Directory children keyed by relative dir ("" = root). */
    tree: {} as Record<string, WorkspaceNode[]>,
    /** Directories the user has expanded. */
    expanded: new Set<string>(),
    /** Per-directory loading flag. */
    loading: {} as Record<string, boolean>,
    /** Per-directory "load more" flag. */
    loadingMore: {} as Record<string, boolean>,
    /** Per-directory error message. */
    errors: {} as Record<string, string>,
    /** Per-directory pagination cursor. */
    nextCursors: {} as Record<string, string | null>,
    /** Per-directory truncated flag (more pages available). */
    truncatedDirs: {} as Record<string, boolean>,
    /** The merged artifact index (manifest facts). */
    artifacts: [] as ArtifactRecord[],
    artifactsLoading: false,
    artifactsLoadingMore: false,
    artifactsError: null as string | null,
    /** Artifact list pagination. */
    artifactsNextCursor: null as number | null,
    /** Watcher overflow: Explorer may be stale until a bounded rescan. */
    stale: false,
    /** v2.1.8 T4: agent history conversations (变更页第 5 组). */
    conversations: [] as ConversationSummary[],
    conversationsLoading: false,
    conversationsError: null as string | null,
    /** Per-conversation inline resume error (preflight failure keeps the
     *  layout — no tab is created; design §1c). */
    resumeErrors: {} as Record<string, string>,
    /** Unattributed changes (watcher projection, never agent provenance). */
    unattributed: {} as Record<string, string>,
    activeKind: "explorer" as ExplorerKind,
    /** Inline preview for the selected file. */
    preview: null as WorkspacePreviewResult | null,
    previewLoading: false,
    /** Stage 11: in-app file clipboard (copy action). Cleared when the
     *  workspace changes so a stale source can never be pasted elsewhere. */
    clipboard: null as ExplorerClipboard | null,
    clipboardGeneration: 0,
  }),

  getters: {
    rootNodes: (s) => s.tree[""] ?? [],
    artifactDeliverables: (s) => s.artifacts.filter((a) => a.kind === "deliverable"),
    artifactSourceChanges: (s) => s.artifacts.filter((a) => a.kind === "source_change"),
    artifactGenerated: (s) => s.artifacts.filter((a) => a.kind === "generated_output"),
    nodeChildren: (s) => (dir: string) => s.tree[dir] ?? [],
    isExpanded: (s) => (dir: string) => s.expanded.has(dir),
    isLoading: (s) => (dir: string) => !!s.loading[dir],
    isLoadingMore: (s) => (dir: string) => !!s.loadingMore[dir],
    isTruncated: (s) => (dir: string) => !!s.truncatedDirs[dir] && !!s.nextCursors[dir],
    unattributedEntries: (s) => {
      // Directories are structural containers, not artifacts: a newly-created
      // (possibly empty) folder must not appear in the Artifacts panel even
      // though the watcher reports it as an unattributed change. Only files
      // (and their descendants) surface. We still keep dirs in `unattributed`
      // so `loadNewCreatedDirs` can list their children.
      const dirPaths = new Set<string>();
      for (const list of Object.values(s.tree)) {
        for (const n of list) {
          if (n.kind === "dir") dirPaths.add(n.relative_path);
        }
      }
      return Object.entries(s.unattributed)
        .filter(
          ([relative_path]) =>
            !isIgnoredPath(relative_path) && !dirPaths.has(relative_path),
        )
        .map(([relative_path, change_type]) => ({ relative_path, change_type }))
        .sort((a, b) => a.relative_path.localeCompare(b.relative_path));
    },
    /** Flatten the currently expanded tree for APG keyboard navigation.
     *  Only expanded directories are descended into; unexpanded subtrees stay lazy. */
    visibleNodes: (s) => {
      const out: WorkspaceNode[] = [];
      const visit = (nodes: WorkspaceNode[]) => {
        for (const n of nodes) {
          out.push(n);
          if (n.kind === "dir" && s.expanded.has(n.relative_path)) {
            visit(s.tree[n.relative_path] ?? []);
          }
        }
      };
      visit(s.tree[""] ?? []);
      return out;
    },
    /** Directories that have more pages to load and are currently expanded. */
    truncatedExpandedDirs: (s) => {
      const dirs: string[] = [];
      if (s.truncatedDirs[""] && s.nextCursors[""]) {
        dirs.push("");
      }
      const visit = (nodes: WorkspaceNode[]) => {
        for (const n of nodes) {
          if (n.kind === "dir" && s.expanded.has(n.relative_path)) {
            if (s.truncatedDirs[n.relative_path] && s.nextCursors[n.relative_path]) {
              dirs.push(n.relative_path);
            }
            visit(s.tree[n.relative_path] ?? []);
          }
        }
      };
      visit(s.tree[""] ?? []);
      return dirs;
    },
  },

  actions: {
    setWorkspace(workspace: string) {
      if (this.workspace !== workspace) {
        void this.stopWatching();
        // IDEA-3 (3e): snapshot the outgoing workspace; restore a prior cache
        // for the incoming one instead of destroying everything. Rapid A→B→A
        // switches keep A's tree, expansions and unattributed projection.
        if (this.workspace) {
          this.caches[this.workspace] = {
            tree: this.tree,
            expanded: this.expanded,
            loading: {},
            loadingMore: {},
            errors: this.errors,
            nextCursors: this.nextCursors,
            truncatedDirs: this.truncatedDirs,
            unattributed: this.unattributed,
            stale: this.stale,
          };
        }
        const cached = this.caches[workspace];
        if (cached) {
          this.tree = cached.tree;
          this.expanded = cached.expanded;
          this.loading = {};
          this.loadingMore = {};
          this.errors = cached.errors;
          this.nextCursors = cached.nextCursors;
          this.truncatedDirs = cached.truncatedDirs;
          this.unattributed = cached.unattributed;
          this.stale = cached.stale;
        } else {
          this.tree = {};
          this.expanded = new Set();
          this.loading = {};
          this.loadingMore = {};
          this.errors = {};
          this.nextCursors = {};
          this.truncatedDirs = {};
          this.unattributed = {};
          this.stale = false;
        }
        this.workspace = workspace;
        this.artifacts = [];
        this.artifactsNextCursor = null;
        this.preview = null;
        // v2.1.8 T4: conversations belong to the outgoing workspace; inline
        // resume errors equally so.
        this.conversations = [];
        this.resumeErrors = {};
        // A copied entry belongs to its workspace; pasting into another
        // workspace must be refused (02 §3), so drop the buffer on switch.
        this.clipboard = null;
        void this.startWatching(workspace);
      }
    },

    /** Start the backend watcher and subscribe to change/stale events. */
    async startWatching(workspace: string) {
      await this.stopWatching();
      try {
        await workspaceWatchStart(workspace);
      } catch {
        // watcher is best-effort; Explorer still works via manual refresh
      }
      const unlisteners: Array<() => void> = [];
      const unlistenChanged = await listen<WorkspaceChangeBatch>("workspace://changed", (ev) => {
        // IDEA-3 (3e): scope by the watched path — a batch from a just-
        // replaced watcher (rapid workspace switch) must not mutate the new
        // workspace's tree. Unscoped payloads (older backends) pass through.
        if (ev.payload.workspace && ev.payload.workspace !== workspace) return;
        this.handleWorkspaceChanges(ev.payload.changes);
      });
      unlisteners.push(unlistenChanged);
      const unlistenStale = await listen<WorkspaceChangeBatch>("workspace://stale", (ev) => {
        if (ev.payload.workspace && ev.payload.workspace !== workspace) return;
        this.stale = true;
        // Bounded rescan: re-list the root; clear stale once loaded.
        void this.loadDir("", true).then(() => {
          this.stale = false;
        });
      });
      unlisteners.push(unlistenStale);
      watcherUnlisteners = unlisteners;
    },

    async stopWatching() {
      for (const unlisten of watcherUnlisteners.splice(0)) {
        try {
          unlisten();
        } catch {
          // noop
        }
      }
      try {
        await workspaceWatchStop();
      } catch {
        // noop
      }
    },

    /** Update unattributed state and refresh/drop affected directory caches. */
    handleWorkspaceChanges(changes: WorkspaceChangeBatch["changes"]) {
      const parents = new Set<string>();
      for (const c of changes) {
        if (isIgnoredPath(c.relative_path)) {
          // User-configured ignores hide dependency/build/state noise from the
          // Artifacts panel even when the watcher already emitted it.
          continue;
        }
        this.unattributed[c.relative_path] = c.change_type;
        const idx = c.relative_path.lastIndexOf("/");
        const parent = idx >= 0 ? c.relative_path.slice(0, idx) : "";
        parents.add(parent);
      }
      this.applyChangeStates();
      // Immediately re-list loaded parent dirs so new files appear without
      // a manual refresh; unexpanded dirs just drop their cache. The root
      // ("") is always loaded and must never be deleted by a change event.
      const reloadTasks: Promise<void>[] = [];
      for (const parent of parents) {
        if (this.tree[parent] && (parent === "" || this.expanded.has(parent))) {
          reloadTasks.push(this.loadDir(parent, true));
        } else if (parent !== "") {
          delete this.tree[parent];
          delete this.nextCursors[parent];
          delete this.truncatedDirs[parent];
        }
      }
      // A newly-created folder may not be watched recursively on all
      // platforms. List it once immediately after its parent reloaded so
      // files created inside it also become visible without manual refresh.
      void Promise.all(reloadTasks).then(() => this.loadNewCreatedDirs());
    },

    /** Re-apply watcher-derived change_state to loaded tree nodes. With a
     *  dir only that directory is rescanned (S5/R3 — the poll loop used to
     *  walk EVERY loaded directory's nodes on every 1.5s tick); no arg
     *  rescans everything (workspace switch / reset). */
    applyChangeStates(dir?: string) {
      const lists = dir === undefined ? Object.values(this.tree) : [this.tree[dir]];
      for (const list of lists) {
        if (!list) continue;
        for (const node of list) {
          const change = this.unattributed[node.relative_path];
          if (change) {
            node.change_state = change;
          }
        }
      }
    },

    /** Lazily load a directory's children. No-op if already loaded or loading.
     *  `silent` (S5/R2): the 1.5s background poll must NOT flip the loading
     *  flag — a big dir listing slower than the interval kept the spinner
     *  permanently on ("疯狂转圈"). User-initiated loads keep the spinner. */
    async loadDir(dir: string, force = false, markCreated = false, silent = false) {
      if (!this.workspace) return;
      if (this.loading[dir]) return;
      if (!force && this.tree[dir]) return;
      const previous = this.tree[dir] ?? [];
      const previousPaths = new Set(previous.map((n) => n.relative_path));
      if (!silent) this.loading[dir] = true;
      this.errors[dir] = "";
      try {
        const result = await workspaceList(this.workspace, dir, null);
        this.tree[dir] = result.nodes;
        this.nextCursors[dir] = result.next_cursor;
        this.truncatedDirs[dir] = result.truncated;
        // When this is a forced refresh of an already-loaded directory, mark
        // paths that appeared/disappeared since the last listing so the
        // Artifacts panel can surface them even if the live watcher missed the
        // event (e.g. the Explorer was hidden or the app just started).
        if (force && previous.length > 0) {
          const currentPaths = new Set(result.nodes.map((n) => n.relative_path));
          for (const path of currentPaths) {
            if (!previousPaths.has(path) && !this.unattributed[path] && !isIgnoredPath(path)) {
              this.unattributed[path] = "created";
            }
          }
          for (const path of previousPaths) {
            if (!currentPaths.has(path) && !this.unattributed[path] && !isIgnoredPath(path)) {
              this.unattributed[path] = "deleted";
            }
          }
        } else if (markCreated && previous.length === 0) {
          // This directory itself is newly created: its immediate children are
          // new to the user too, so surface them as unattributed immediately.
          for (const node of result.nodes) {
            if (!this.unattributed[node.relative_path] && !isIgnoredPath(node.relative_path)) {
              this.unattributed[node.relative_path] = "created";
            }
          }
        }
        this.applyChangeStates(dir);
      } catch (e) {
        this.errors[dir] = String(e);
      } finally {
        if (!silent) this.loading[dir] = false;
      }
    },

    /** Load the next page for an already-listed directory. */
    async loadMore(dir: string) {
      if (!this.workspace) return;
      if (this.loadingMore[dir]) return;
      const cursor = this.nextCursors[dir];
      if (!cursor) return;
      this.loadingMore[dir] = true;
      try {
        const result = await workspaceList(this.workspace, dir, cursor);
        const existing = this.tree[dir] ?? [];
        const seen = new Set(existing.map((n) => n.relative_path));
        const fresh = result.nodes.filter((n) => !seen.has(n.relative_path));
        this.tree[dir] = [...existing, ...fresh];
        this.nextCursors[dir] = result.next_cursor;
        this.truncatedDirs[dir] = result.truncated;
        this.applyChangeStates();
      } catch (e) {
        this.errors[dir] = String(e);
      } finally {
        this.loadingMore[dir] = false;
      }
    },

    async toggleDir(dir: string) {
      if (this.expanded.has(dir)) {
        this.expanded.delete(dir);
        return;
      }
      this.expanded.add(dir);
      if (!this.tree[dir]) {
        await this.loadDir(dir);
      }
    },

    async refreshArtifacts() {
      if (this.workspace) {
        try {
          await artifactRefresh(this.workspace);
        } catch {
          // refresh is best-effort; the existing index may still be usable
        }
      }
      await this.loadArtifacts(true);
    },

    async refreshRoot() {
      // Run artifact refresh and the root listing concurrently so the tree is
      // not blocked behind index import (large registries can be slow).
      await Promise.all([
        this.refreshArtifacts(),
        this.loadDir("", true),
      ]);
    },

    /** Poll loaded/expanded directories as a realtime fallback when the
     *  native watcher is not delivering events reliably. The directory
     *  diff logic keeps this cheap: only changed dirs produce UI work. */
    async pollLoadedDirs() {
      if (!this.workspace || this.stale) return;
      const dirs = new Set<string>([""]);
      for (const dir of this.expanded) {
        dirs.add(dir);
      }
      const tasks: Promise<void>[] = [];
      for (const dir of dirs) {
        if (this.tree[dir] && !this.loading[dir]) {
          tasks.push(this.loadDir(dir, true, false, true /* silent poll (S5/R2) */));
        }
      }
      await Promise.all(tasks);
      await this.loadNewCreatedDirs();
    },

    /** Recursively list newly-created directories (bounded depth) so files
     *  created inside a just-created folder appear without manual refresh. */
    async loadNewCreatedDirs() {
      if (!this.workspace) return;
      for (let round = 0; round < 8; round += 1) {
        const pending: string[] = [];
        for (const list of Object.values(this.tree)) {
          for (const node of list) {
            if (
              node.kind === "dir" &&
              this.unattributed[node.relative_path] === "created" &&
              !this.tree[node.relative_path] &&
              !this.loading[node.relative_path]
            ) {
              pending.push(node.relative_path);
            }
          }
        }
        if (pending.length === 0) break;
        await Promise.all(
          pending.map((dir) => this.loadDir(dir, false, true, true /* silent */)),
        );
      }
    },

    async loadArtifacts(force = false) {
      if (!this.workspace) return;
      if (this.artifactsLoading) return;
      if (!force && this.artifacts.length > 0 && this.artifactsNextCursor === null) return;
      this.artifactsLoading = true;
      this.artifactsError = null;
      try {
        const result = await artifactList();
        this.artifacts = result.artifacts;
        this.artifactsNextCursor = result.next_cursor;
      } catch (e) {
        this.artifactsError = String(e);
      } finally {
        this.artifactsLoading = false;
      }
    },

    async loadMoreArtifacts() {      if (!this.workspace) return;
      if (this.artifactsLoadingMore) return;
      if (this.artifactsNextCursor === null) return;
      this.artifactsLoadingMore = true;
      try {
        const result = await artifactList(null, this.artifactsNextCursor);
        const seen = new Set(this.artifacts.map((a) => a.artifact_id));
        const fresh = result.artifacts.filter((a) => !seen.has(a.artifact_id));
        this.artifacts = [...this.artifacts, ...fresh];
        this.artifactsNextCursor = result.next_cursor;
      } catch (e) {
        this.artifactsError = String(e);
      } finally {
        this.artifactsLoadingMore = false;
      }
    },

    // --- v2.1.8 T4: agent history conversations (变更页第 5 组) ---

    /** Load the workspace's agent history conversations (most recent first;
     *  the CLI owns ordering). Called when the 变更 tab activates. */
    async loadConversations(force = false) {
      if (!this.workspace) return;
      if (this.conversationsLoading) return;
      if (!force && this.conversations.length > 0) return;
      this.conversationsLoading = true;
      this.conversationsError = null;
      try {
        const result = await conversationList(this.workspace);
        this.conversations = result.conversations;
      } catch (e) {
        this.conversationsError = String(e);
      } finally {
        this.conversationsLoading = false;
      }
    },

    /** Two-call resume orchestration (design §1c): preflight FIRST — its
     *  failure keeps the current layout (no tab/pane/Channel) and surfaces
     *  an inline row error; success hands off to createTab, which threads
     *  the id through openPane → open_session → wrapper `--resume-id`.
     *  Returns true when the resume tab was created. */
    async resumeConversation(c: ConversationSummary): Promise<boolean> {
      if (!this.workspace) return false;
      delete this.resumeErrors[c.conversation_id];
      try {
        await conversationPreflight(this.workspace, c.conversation_id, c.agent);
      } catch (e) {
        // WorkbenchError serializes { code, message }; prefer its message.
        const msg =
          e && typeof e === "object" && "message" in e
            ? String((e as { message?: unknown }).message)
            : String(e);
        this.resumeErrors[c.conversation_id] = msg;
        return false;
      }
      const { useRuntimeStore } = await import("./runtime");
      const runtime = useRuntimeStore();
      // A live tab that already resumed this conversation: activate it
      // instead of spawning a duplicate resume — the provider refuses a
      // second resume of a live session (手测反馈).
      const live = runtime.findLiveResumeTab?.(c.conversation_id);
      if (live) {
        runtime.activateTab(live.tabId);
        return true;
      }
      return runtime.createTab(c.agent, c.conversation_id) !== null;
    },

    /** Rename a conversation (手测反馈 #2): persists a title override in the
     *  workspace runtime dir (the CLI owns the storage) and refreshes. */
    async renameConversation(c: ConversationSummary, title: string): Promise<void> {
      if (!this.workspace) return;
      await conversationRename(this.workspace, c.conversation_id, c.agent, title);
      await this.loadConversations(true);
    },

    /** Delete a conversation after the UI's confirm dialog; the list
     *  refreshes so the row disappears immediately (手测反馈 #4). */
    async deleteConversation(c: ConversationSummary): Promise<void> {
      if (!this.workspace) return;
      delete this.resumeErrors[c.conversation_id];
      await conversationDelete(this.workspace, c.conversation_id, c.agent);
      await this.loadConversations(true);
    },

    // --- file actions (containment enforced in Rust) ---

    async openFile(relativePath: string) {
      if (!this.workspace) return;
      await workspaceOpen(this.workspace, relativePath);
    },

    async revealFile(relativePath: string) {
      if (!this.workspace) return;
      await workspaceReveal(this.workspace, relativePath);
    },

    async copyPath(relativePath: string): Promise<string> {
      if (!this.workspace) return "";
      const result = await workspaceCopyPath(this.workspace, relativePath);
      return result.absolute_path;
    },

    async previewFile(relativePath: string) {
      if (!this.workspace) return;
      this.previewLoading = true;
      try {
        this.preview = await workspacePreview(this.workspace, relativePath);
      } finally {
        this.previewLoading = false;
      }
    },

    clearPreview() {
      this.preview = null;
    },

    // --- Stage 11 (11c): contained mutations + in-app clipboard ---
    // All actions re-check `workspace`, let Rust validate again, then do a
    // directed refresh of the affected parent directory. The watcher stays a
    // supplementary signal (02 §3, 05 §2).

    /** Copy action: only records the in-app clipboard (D11-02). */
    setClipboardEntry(sourceRelativePath: string, kind: "file" | "dir") {
      if (!this.workspace) return;
      this.clipboardGeneration += 1;
      this.clipboard = {
        workspace: this.workspace,
        sourceRelativePath,
        kind,
        generation: this.clipboardGeneration,
      };
    },

    /** True when the clipboard holds a pasteable entry for THIS workspace. */
    canPaste(): boolean {
      const c = this.clipboard;
      return !!c && !!this.workspace && c.workspace === this.workspace;
    },

    /** Paste: copy the clipboard entry into `destinationDir`. Rejects when
     *  the buffer is empty, from another workspace, or the source vanished.
     *  Never overwrites — conflicts surface as WB_ERR_WORKSPACE_CONFLICT. */
    async pasteEntry(destinationDir: string): Promise<WorkspaceMutationResult> {
      const c = this.clipboard;
      if (!c || !this.workspace || c.workspace !== this.workspace) {
        throw { code: "WB_ERR_WORKSPACE_INVALID" };
      }
      const result = await workspaceCopyEntry(
        this.workspace,
        c.sourceRelativePath,
        destinationDir,
      );
      await this.loadDir(destinationDir, true);
      return result;
    },

    /** Create an empty file or a directory in `relativeDir`. */
    async createEntry(
      relativeDir: string,
      name: string,
      isDir: boolean,
    ): Promise<WorkspaceMutationResult> {
      if (!this.workspace) throw { code: "WB_ERR_WORKSPACE_INVALID" };
      const result = isDir
        ? await workspaceCreateDir(this.workspace, relativeDir, name)
        : await workspaceCreateFile(this.workspace, relativeDir, name);
      await this.loadDir(relativeDir, true);
      return result;
    },

    /** Rename an entry inside its own parent directory. Directory caches and
     *  expansion state move to the new key (children reload lazily). */
    async renameEntry(relativePath: string, newName: string): Promise<WorkspaceMutationResult> {
      if (!this.workspace) throw { code: "WB_ERR_WORKSPACE_INVALID" };
      const result = await workspaceRename(this.workspace, relativePath, newName);
      const parent = parentDirOf(relativePath);
      if (result.kind === "dir") {
        // Re-key the renamed dir's cached subtree/expanded/unattributed state;
        // a stale `tree[old]` would render phantom rows on next expansion.
        delete this.tree[relativePath];
        delete this.nextCursors[relativePath];
        delete this.truncatedDirs[relativePath];
        if (this.expanded.has(relativePath)) {
          this.expanded.delete(relativePath);
          this.expanded.add(result.relative_path);
          await this.loadDir(result.relative_path);
        }
        const movedUnattributed: Record<string, string> = {};
        for (const [path, change] of Object.entries(this.unattributed)) {
          if (path === relativePath || path.startsWith(`${relativePath}/`)) {
            delete this.unattributed[path];
            const next = `${result.relative_path}${path.slice(relativePath.length)}`;
            movedUnattributed[next] = change;
          }
        }
        Object.assign(this.unattributed, movedUnattributed);
      }
      await this.loadDir(parent, true);
      return result;
    },
  },
});
