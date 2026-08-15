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
  workspaceCopyPath,
  workspaceList,
  workspaceOpen,
  workspacePreview,
  workspaceReveal,
  workspaceWatchStart,
  workspaceWatchStop,
} from "../lib/ipc";
import type { ArtifactRecord, WorkspaceNode, WorkspacePreviewResult } from "../types";

interface WorkspaceChangeBatch {
  changes: Array<{ relative_path: string; change_type: string; revision: number }>;
  overflow: boolean;
  stale: boolean;
}

export type ExplorerKind = "explorer" | "artifacts";

export const useWorkspaceExplorerStore = defineStore("workspaceExplorer", {
  state: () => ({
    workspace: null as string | null,
    /** Directory children keyed by relative dir ("" = root). */
    tree: {} as Record<string, WorkspaceNode[]>,
    /** Directories the user has expanded. */
    expanded: new Set<string>(),
    /** Per-directory loading flag. */
    loading: {} as Record<string, boolean>,
    /** Per-directory error message. */
    errors: {} as Record<string, string>,
    /** The merged artifact index (manifest facts). */
    artifacts: [] as ArtifactRecord[],
    artifactsLoading: false,
    artifactsError: null as string | null,
    /** Watcher overflow: Explorer may be stale until a bounded rescan. */
    stale: false,
    /** Unattributed changes (watcher projection, never agent provenance). */
    unattributed: {} as Record<string, string>,
    activeKind: "explorer" as ExplorerKind,
    /** Inline preview for the selected file. */
    preview: null as WorkspacePreviewResult | null,
    previewLoading: false,
  }),

  getters: {
    rootNodes: (s) => s.tree[""] ?? [],
    artifactDeliverables: (s) => s.artifacts.filter((a) => a.kind === "deliverable"),
    artifactSourceChanges: (s) => s.artifacts.filter((a) => a.kind === "source_change"),
    artifactGenerated: (s) => s.artifacts.filter((a) => a.kind === "generated_output"),
    nodeChildren: (s) => (dir: string) => s.tree[dir] ?? [],
    isExpanded: (s) => (dir: string) => s.expanded.has(dir),
    isLoading: (s) => (dir: string) => !!s.loading[dir],
    unattributedEntries: (s) =>
      Object.entries(s.unattributed)
        .map(([relative_path, change_type]) => ({ relative_path, change_type }))
        .sort((a, b) => a.relative_path.localeCompare(b.relative_path)),
  },

  actions: {
    setWorkspace(workspace: string) {
      if (this.workspace !== workspace) {
        this.workspace = workspace;
        this.tree = {};
        this.expanded = new Set();
        this.artifacts = [];
        this.unattributed = {};
        void this.startWatching(workspace);
      }
    },

    /** Start the backend watcher and subscribe to change/stale events. */
    async startWatching(workspace: string) {
      try {
        await workspaceWatchStart(workspace);
      } catch {
        // watcher is best-effort; Explorer still works via manual refresh
      }
      await listen<WorkspaceChangeBatch>("workspace://changed", (ev) => {
        for (const c of ev.payload.changes) {
          this.unattributed[c.relative_path] = c.change_type;
          // Drop the parent dir from the loaded tree so the next expand reloads.
          const idx = c.relative_path.lastIndexOf("/");
          const parent = idx >= 0 ? c.relative_path.slice(0, idx) : "";
          delete this.tree[parent];
        }
      });
      await listen("workspace://stale", () => {
        this.stale = true;
        // Bounded rescan: re-list the root; clear stale once loaded.
        void this.loadDir("", true).then(() => {
          this.stale = false;
        });
      });
    },

    async stopWatching() {
      try {
        await workspaceWatchStop();
      } catch {
        // noop
      }
    },

    /** Lazily load a directory's children. No-op if already loaded or loading. */
    async loadDir(dir: string, force = false) {
      if (!this.workspace) return;
      if (this.loading[dir]) return;
      if (!force && this.tree[dir]) return;
      this.loading[dir] = true;
      this.errors[dir] = "";
      try {
        const result = await workspaceList(this.workspace, dir);
        this.tree[dir] = result.nodes;
      } catch (e) {
        this.errors[dir] = String(e);
      } finally {
        this.loading[dir] = false;
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

    async refreshRoot() {
      await this.loadDir("", true);
      await this.loadArtifacts();
    },

    async loadArtifacts() {
      if (!this.workspace) return;
      this.artifactsLoading = true;
      this.artifactsError = null;
      try {
        const result = await artifactList();
        this.artifacts = result.artifacts;
      } catch (e) {
        this.artifactsError = String(e);
      } finally {
        this.artifactsLoading = false;
      }
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
  },
});
