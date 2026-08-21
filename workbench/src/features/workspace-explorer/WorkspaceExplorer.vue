<script setup lang="ts">
/**
 * Stage 3 (3c, WX-01/02): Workspace Explorer + Agent Artifacts.
 *
 * Lazy tree: only expanded directories are listed; the store never recurses
 * (R3-04). File actions (open/reveal/copy/preview) go through Rust containment
 * — the frontend never holds an arbitrary absolute path (D3-06). Artifacts
 * come from the merged manifest index; unattributed changes are a separate
 * "workspace changes" projection (never labelled as agent provenance, D3-03).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { useWorkspaceExplorerStore } from "../../stores/workspaceExplorer";
import { useRuntimeStore } from "../../stores/runtime";
import type { WorkspaceNode } from "../../types";

const { t, te } = useI18n();
const explorer = useWorkspaceExplorerStore();
const runtime = useRuntimeStore();

const selected = ref<string | null>(null);
const menuFor = ref<string | null>(null);
const menuPos = ref({ x: 0, y: 0 });
const copied = ref<string | null>(null);
/** Roving focus index into `visibleNodes` (APG tree pattern). */
const focusIndex = ref(-1);

const artifactFilter = computed(() => explorer.activeKind);

async function switchKind(kind: "explorer" | "artifacts") {
  explorer.activeKind = kind;
  if (kind === "artifacts") {
    await explorer.refreshArtifacts();
  }
}

let pollTimer: number | null = null;

onMounted(() => {
  if (runtime.workspace) {
    if (explorer.workspace !== runtime.workspace) {
      explorer.setWorkspace(runtime.workspace);
    }
    // Always refresh on open: the Explorer may have been hidden while the
    // agent created files, so cached tree/artifacts can be stale.
    void explorer.refreshRoot();
  }

  // Native watcher is the primary realtime path. Polling is a fallback for
  // platforms where notify events are delayed or not delivered reliably; the
  // directory diff in loadDir makes this a cheap no-op when nothing changed.
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void explorer.pollLoadedDirs();
    }
  }, 1500);
});

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
});

// The workspace may arrive asynchronously after mount (startup negotiation);
// initialize as soon as it is set so the Explorer never shows an empty tree.
watch(
  () => runtime.workspace,
  (ws) => {
    if (ws && explorer.workspace !== ws) {
      explorer.setWorkspace(ws);
      void explorer.refreshRoot();
    }
  },
);


function isExpanded(node: WorkspaceNode): boolean {
  return explorer.isExpanded(node.relative_path);
}

async function onToggle(node: WorkspaceNode) {
  if (node.kind !== "dir") return;
  await explorer.toggleDir(node.relative_path);
}

/** Tree depth for indentation: number of path segments below the workspace root. */
function depthOf(node: WorkspaceNode): number {
  if (!node.relative_path) return 0;
  return node.relative_path.split("/").length - 1;
}

async function onSelect(node: WorkspaceNode) {
  selected.value = node.relative_path;
  menuFor.value = null;
  if (node.kind === "dir") {
    await onToggle(node);
    return;
  }
  await explorer.previewFile(node.relative_path);
}

async function onOpen(node: WorkspaceNode) {
  if (node.kind === "dir") {
    await explorer.toggleDir(node.relative_path);
    return;
  }
  await explorer.openFile(node.relative_path);
}

async function onReveal(node: WorkspaceNode) {
  await explorer.revealFile(node.relative_path); // works for dirs and files
}

async function copyRelativePath(relativePath: string) {
  const abs = await explorer.copyPath(relativePath);
  if (abs) {
    try {
      await writeText(abs);
    } catch {
      // clipboard unavailable; keep the copied feedback but do not crash
    }
    copied.value = relativePath;
    setTimeout(() => (copied.value = null), 1500);
  }
}

async function onCopy(node: WorkspaceNode) {
  await copyRelativePath(node.relative_path);
}

/** Open a path from the context menu. Works for tree nodes and artifact rows
 *  (which may not be in the loaded tree): a dir toggles, a file opens. */
async function onMenuOpen(relativePath: string) {
  const node = nodeOf(relativePath);
  menuFor.value = null;
  if (node && node.kind === "dir") {
    await explorer.toggleDir(relativePath);
    return;
  }
  await explorer.openFile(relativePath);
}

async function onMenuReveal(relativePath: string) {
  const node = nodeOf(relativePath);
  menuFor.value = null;
  if (node) await onReveal(node);
  else await explorer.revealFile(relativePath);
}

async function onMenuCopy(relativePath: string) {
  const node = nodeOf(relativePath);
  menuFor.value = null;
  if (node) await onCopy(node);
  else await copyRelativePath(relativePath);
}

/**
 * The app chrome is CSS-zoomed (`ui.font_scale` → `.app { zoom }`). Under a
 * non-1 zoom, `position: fixed`'s containing block becomes the zoomed ancestor,
 * so `clientX/clientY` (1:1 viewport px) must be divided by the live zoom to
 * land at the pointer. Measure it from the `.app` box (rect.width/offsetWidth
 * is the standard way to read CSS zoom in Chromium) rather than re-deriving
 * the settings formula. Falls back to 1 when the app root is not measurable.
 */
/**
 * The app chrome is CSS-zoomed (`ui.font_scale` → `.app { zoom }`). Under a
 * non-1 zoom, `position: fixed`'s containing block becomes the zoomed ancestor,
 * so `clientX/clientY` (1:1 viewport px) must be divided by the live zoom to
 * land at the pointer. Measure it from the `.app` box (rect.width/offsetWidth
 * is the standard way to read CSS zoom in Chromium) rather than re-deriving
 * the settings formula. Falls back to 1 when the app root is not measurable.
 * (10d r4 note: this menu lives INSIDE the zoomed .app — keep dividing. Only
 * menus teleported OUTSIDE .app use raw viewport px; see TabBar/WorkspaceBar.)
 */
function appZoom(): number {
  const app = document.querySelector<HTMLElement>(".app");
  if (!app) return 1;
  const w = app.offsetWidth || 0;
  return w > 0 ? app.getBoundingClientRect().width / w : 1;
}

function openMenu(node: WorkspaceNode, event: MouseEvent) {
  menuFor.value = node.relative_path;
  const zoom = appZoom();
  const menuWidth = 160;
  const menuHeight = 160;
  menuPos.value = {
    x: Math.max(4, Math.min(event.clientX / zoom, window.innerWidth / zoom - menuWidth)),
    y: Math.max(4, Math.min(event.clientY / zoom, window.innerHeight / zoom - menuHeight)),
  };
}

/** Watcher change type → localized quiet label (raw enum never hits the UI). */
function changeLabel(change: string): string {
  const key = `explorer.change.${change}`;
  const known = ["created", "modified", "deleted"];
  return known.includes(change) ? te(key) ? t(key) : change : change;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Display a host absolute path for a workspace-relative path. */
function hostPath(relativePath: string): string {
  if (!runtime.workspace) return relativePath;
  const base = runtime.workspace.replace(/\\/g, "/").replace(/\/+$/, "");
  return `${base}/${relativePath}`;
}

/** Artifact rows show only the basename; the full host path is the title. */
function fileName(relativePath: string): string {
  const normalized = relativePath.replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}

/** Basenames that appear more than once across ALL rows in the Artifacts
 *  panel — manifest artifacts AND unattributed watcher changes (the container
 *  agent's writes usually land here, not in the manifest). When a basename
 *  collides, every row for it shows the workspace-relative path so the user can
 *  tell them apart (e.g. `a/result.md` vs `b/result.md`, or a `created` vs a
 *  `modified` of the same name in different folders). */
const collidingBasenames = computed(() => {
  const seen = new Map<string, number>();
  const count = (relativePath: string) => {
    const base = fileName(relativePath);
    seen.set(base, (seen.get(base) ?? 0) + 1);
  };
  for (const a of explorer.artifacts) {
    count(a.workspace_relative_path);
  }
  for (const u of explorer.unattributedEntries) {
    count(u.relative_path);
  }
  const colliding = new Set<string>();
  for (const [base, count] of seen) {
    if (count > 1) colliding.add(base);
  }
  return colliding;
});

/** Display label for an artifact/unattributed row: basename normally, full
 *  workspace-relative path when the basename is ambiguous across the panel. */
function artifactLabel(relativePath: string): string {
  const base = fileName(relativePath);
  return collidingBasenames.value.has(base) ? relativePath : base;
}

/** Adapter so the shared tree context menu (which consumes a WorkspaceNode)
 *  can open over an artifact/unattributed row without the file being loaded
 *  into the lazy tree. Only `relative_path`/`kind` matter to the menu. */
function pseudoNode(relativePath: string): WorkspaceNode {
  return {
    relative_path: relativePath,
    name: fileName(relativePath),
    kind: "file",
    expandable: false,
    artifact_badges: [],
    change_state: "unknown",
  };
}

/** Select + preview a file from an artifact/unattributed row (mirrors the
 *  file tree's single-click: preview; double-click opens). */
async function onArtifactSelect(relativePath: string) {
  selected.value = relativePath;
  menuFor.value = null;
  await explorer.previewFile(relativePath);
}

/** Resolve a node by relative path across loaded tree levels. */
function nodeOf(rel: string): WorkspaceNode | null {
  for (const list of Object.values(explorer.tree)) {
    const hit = list.find((n) => n.relative_path === rel);
    if (hit) return hit;
  }
  return null;
}

function focusNode(index: number) {
  const total = explorer.visibleNodes.length;
  if (total === 0) {
    focusIndex.value = -1;
    return;
  }
  focusIndex.value = (index + total) % total;
}

/** APG tree keyboard: Arrow/Home/End move focus, Enter/Space activate. */
function onTreeKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    menuFor.value = null;
    return;
  }
  if (e.key === "F10" && e.shiftKey) {
    const node = explorer.visibleNodes[focusIndex.value];
    if (node) {
      e.preventDefault();
      menuFor.value = node.relative_path;
    }
    return;
  }
  if (e.key === "ArrowDown") {
    e.preventDefault();
    focusNode((focusIndex.value < 0 ? -1 : focusIndex.value) + 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    focusNode(focusIndex.value < 0 ? -1 : focusIndex.value - 1);
  } else if (e.key === "Home") {
    e.preventDefault();
    focusNode(0);
  } else if (e.key === "End") {
    e.preventDefault();
    focusNode(explorer.visibleNodes.length - 1);
  } else if (e.key === "Enter" || e.key === " ") {
    const node = explorer.visibleNodes[focusIndex.value];
    if (node) {
      e.preventDefault();
      void onSelect(node);
    }
  }
}
</script>

<template>
  <div class="explorer" data-testid="workspace-explorer">
    <div class="explorer-header">
      <div class="explorer-tabs" role="tablist" aria-orientation="horizontal">
        <button
          role="tab"
          :aria-selected="explorer.activeKind === 'explorer'"
          class="explorer-tab"
          :class="{ active: explorer.activeKind === 'explorer' }"
          @click="switchKind('explorer')"
        >
          {{ t("explorer.tab.files") }}
        </button>
        <button
          role="tab"
          :aria-selected="explorer.activeKind === 'artifacts'"
          class="explorer-tab"
          :class="{ active: explorer.activeKind === 'artifacts' }"
          @click="switchKind('artifacts')"
        >
          {{ t("explorer.tab.artifacts") }}
        </button>
      </div>
      <button class="explorer-refresh" :title="t('explorer.refresh')" @click="explorer.refreshRoot()">
        ⟳
      </button>
    </div>

    <div v-if="explorer.stale" class="explorer-stale" role="status">
      {{ t("explorer.stale") }}
    </div>

    <!-- Explorer tree -->
    <div
      v-if="artifactFilter === 'explorer'"
      class="explorer-body"
      role="tree"
      aria-orientation="vertical"
      @keydown="onTreeKeydown"
    >
      <p v-if="!runtime.workspace" class="explorer-empty">{{ t("explorer.empty.workspace") }}</p>
      <p
        v-else-if="explorer.visibleNodes.length === 0 && !explorer.isLoading('') && !explorer.errors['']"
        class="explorer-empty"
      >
        {{ t("explorer.empty.files") }}
      </p>
      <template v-else>
        <div
          v-for="(node, i) in explorer.visibleNodes"
          :key="node.relative_path"
          :class="['explorer-row', { selected: selected === node.relative_path }]"
          role="treeitem"
          :aria-selected="selected === node.relative_path"
          :aria-expanded="node.kind === 'dir' ? isExpanded(node) : undefined"
          :aria-level="depthOf(node) + 1"
          :tabindex="i === focusIndex ? 0 : -1"
          :style="{ paddingLeft: `${8 + depthOf(node) * 16}px` }"
          @click="onSelect(node)"
          @dblclick="node.kind === 'file' && onOpen(node)"
          @contextmenu.prevent="openMenu(node, $event)"
          @focus="focusIndex = i"
        >
          <span class="explorer-icon" aria-hidden="true">
            {{ node.kind === "dir" ? (isExpanded(node) ? "▾" : "▸") : "·" }}
          </span>
          <span class="explorer-name" :title="hostPath(node.relative_path)">{{ node.name }}</span>
          <span
            v-for="badge in node.artifact_badges"
            :key="badge"
            class="explorer-badge"
            >{{ badge }}</span
          >
          <span
            v-if="node.change_state && node.change_state !== 'unknown' && node.change_state !== 'artifact'"
            class="change-label"
            >{{ changeLabel(node.change_state) }}</span
          >
        </div>

        <div v-if="explorer.truncatedExpandedDirs.length" class="explorer-more">
          <button
            v-for="dir in explorer.truncatedExpandedDirs"
            :key="dir"
            class="explorer-mini"
            :disabled="explorer.isLoadingMore(dir)"
            @click="explorer.loadMore(dir)"
          >
            {{ explorer.isLoadingMore(dir) ? t("explorer.loading") : (dir ? t("explorer.loadMore", { dir }) : t("explorer.loadMoreRoot")) }}
          </button>
        </div>

        <p v-if="explorer.errors['']" class="explorer-error">{{ explorer.errors[""] }}</p>
      </template>
    </div>

    <!-- Artifacts panel -->
    <div v-else class="explorer-body artifacts-panel">
      <p v-if="explorer.artifactsLoading">{{ t("explorer.loading") }}</p>
      <template v-else>
        <p
          v-if="explorer.artifacts.length === 0 && explorer.unattributedEntries.length === 0"
          class="explorer-empty"
        >
          {{ t("explorer.empty.artifacts") }}
        </p>

        <template v-if="explorer.artifactDeliverables.length">
          <h4 class="artifacts-group">{{ t("explorer.artifacts.deliverables") }}</h4>
          <div
            v-for="a in explorer.artifactDeliverables"
            :key="a.artifact_id"
            class="explorer-row artifact-row"
            :class="{ selected: selected === a.workspace_relative_path }"
            @click="onArtifactSelect(a.workspace_relative_path)"
            @dblclick="explorer.openFile(a.workspace_relative_path)"
            @contextmenu.prevent="openMenu(pseudoNode(a.workspace_relative_path), $event)"
          >
            <span class="explorer-name" :title="hostPath(a.workspace_relative_path)">
              {{ artifactLabel(a.workspace_relative_path) }}
            </span>
            <span v-if="a.label" class="explorer-label">{{ a.label }}</span>
          </div>
        </template>

        <template v-if="explorer.artifactSourceChanges.length">
          <h4 class="artifacts-group">{{ t("explorer.artifacts.sourceChanges") }}</h4>
          <div
            v-for="a in explorer.artifactSourceChanges"
            :key="a.artifact_id"
            class="explorer-row artifact-row"
            :class="{ selected: selected === a.workspace_relative_path }"
            @click="onArtifactSelect(a.workspace_relative_path)"
            @dblclick="explorer.openFile(a.workspace_relative_path)"
            @contextmenu.prevent="openMenu(pseudoNode(a.workspace_relative_path), $event)"
          >
            <span class="explorer-name" :title="hostPath(a.workspace_relative_path)">
              {{ artifactLabel(a.workspace_relative_path) }}
            </span>
          </div>
        </template>

        <template v-if="explorer.artifactGenerated.length">
          <h4 class="artifacts-group">{{ t("explorer.artifacts.generatedOutputs") }}</h4>
          <div
            v-for="a in explorer.artifactGenerated"
            :key="a.artifact_id"
            class="explorer-row artifact-row"
            :class="{ selected: selected === a.workspace_relative_path }"
            @click="onArtifactSelect(a.workspace_relative_path)"
            @dblclick="explorer.openFile(a.workspace_relative_path)"
            @contextmenu.prevent="openMenu(pseudoNode(a.workspace_relative_path), $event)"
          >
            <span class="explorer-name" :title="hostPath(a.workspace_relative_path)">
              {{ artifactLabel(a.workspace_relative_path) }}
            </span>
          </div>
        </template>

        <div v-if="explorer.artifactsNextCursor !== null" class="explorer-more">
          <button
            class="explorer-mini"
            :disabled="explorer.artifactsLoadingMore"
            @click="explorer.loadMoreArtifacts()"
          >
            {{ explorer.artifactsLoadingMore ? t("explorer.loading") : t("explorer.loadMoreArtifacts") }}
          </button>
        </div>

        <h4 v-if="explorer.unattributedEntries.length" class="artifacts-group">
          {{ t("explorer.artifacts.workspaceChanges") }}
        </h4>
        <div
          v-for="u in explorer.unattributedEntries"
          :key="u.relative_path"
          class="explorer-row unattributed"
          :class="{ selected: selected === u.relative_path }"
          @click="onArtifactSelect(u.relative_path)"
          @dblclick="explorer.openFile(u.relative_path)"
          @contextmenu.prevent="openMenu(pseudoNode(u.relative_path), $event)"
        >
          <span class="explorer-name" :title="hostPath(u.relative_path)">{{ artifactLabel(u.relative_path) }}</span>
          <span class="change-label">{{ changeLabel(u.change_type) }}</span>
        </div>
      </template>
    </div>

    <!-- Context menu (10e: unified pop motion) -->
    <Transition name="pop">
    <div
      v-if="menuFor"
      class="explorer-menu"
      role="menu"
      :style="{ left: `${menuPos.x}px`, top: `${menuPos.y}px` }"
      @mousedown.stop
      @contextmenu.prevent
    >
      <button role="menuitem" @click="onMenuOpen(menuFor!)">{{ t("explorer.open") }}</button>
      <button role="menuitem" @click="onMenuReveal(menuFor!)">
        {{ t("explorer.reveal") }}
      </button>
      <button role="menuitem" @click="onMenuCopy(menuFor!)">{{ t("explorer.copy") }}</button>
      <button class="menu-close" role="menuitem" @click="menuFor = null">✕</button>
    </div>
    </Transition>

    <!-- Click-away backdrop: closes the menu without selecting a tree row. -->
    <div v-if="menuFor" class="explorer-menu-backdrop" @mousedown="menuFor = null" @contextmenu.prevent="menuFor = null" />

    <!-- Preview pane -->
    <div v-if="explorer.preview" class="explorer-preview">
      <div class="preview-head">
        <span class="preview-path">{{ hostPath(explorer.preview.relative_path) }}</span>
        <span class="preview-meta">
          {{ explorer.preview.media_type }} · {{ formatBytes(explorer.preview.size) }}
          <template v-if="explorer.preview.truncated"> · {{ t("explorer.preview.truncated") }}</template>
        </span>
        <button class="explorer-mini" @click="explorer.clearPreview()">✕</button>
      </div>
      <pre v-if="explorer.preview.text" class="preview-text">{{
        explorer.preview.text
      }}</pre>
      <img
        v-else-if="explorer.preview.base64 && explorer.preview.media_type.startsWith('image/')"
        class="preview-image"
        :src="`data:${explorer.preview.media_type};base64,${explorer.preview.base64}`"
        :alt="explorer.preview.relative_path"
      />
      <p v-else class="explorer-empty">{{ t("explorer.preview.unsupported") }}</p>
    </div>
  </div>
</template>

<style scoped>
.explorer {
  display: flex;
  flex-direction: column;
  min-height: 0;
  font-size: var(--font-md);
}
.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
  border-bottom: var(--border-w) solid var(--border);
}
.explorer-tabs {
  display: flex;
  gap: 2px;
  padding: 2px;
  border-radius: var(--radius-sm);
  background: var(--surface-3);
}
.explorer-tab {
  background: none;
  border: none;
  color: var(--text-muted);
  padding: 0 var(--space-2);
  min-height: 22px;
  border-radius: calc(var(--radius-sm) - 2px);
  cursor: pointer;
  font-size: var(--font-sm);
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.explorer-tab:hover {
  background: var(--surface-hover);
  color: var(--text-2);
}
.explorer-tab.active {
  background: var(--accent-soft);
  color: var(--text);
  font-weight: 600;
}
.explorer-tab:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
.explorer-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.explorer-refresh:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.explorer-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.explorer-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 var(--space-2);
  margin: 0 var(--space-1);
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--duration-normal) var(--ease);
}
.explorer-row:hover {
  background: var(--surface-hover);
}
.explorer-row.selected {
  background: var(--accent-soft);
  color: var(--text);
}
.explorer-icon {
  width: 14px;
  flex: none;
  color: var(--text-muted);
}
.explorer-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.explorer-child {
  padding-left: 24px;
}
.explorer-badge {
  font-size: var(--font-xs);
  padding: 0 var(--space-2);
  border-radius: var(--radius-full);
  background: var(--accent-soft);
}
.explorer-label {
  font-size: var(--font-xs);
  color: var(--text-muted);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.unattributed {
  opacity: 0.75;
}
/* 10d r4: watcher change states are QUIET text labels — a warn pill on
 * every changed row read as noise (user feedback). Attribution badges
 * (.explorer-badge) keep their pills; change kind does not. */
.change-label {
  font-size: var(--font-xs);
  color: var(--warn);
  white-space: nowrap;
}
.explorer-stale,
.explorer-error {
  padding: var(--space-1) var(--space-2);
  color: var(--warn);
  font-size: var(--font-sm);
}
.explorer-empty {
  padding: var(--space-2);
  color: var(--text-muted);
}
.explorer-more {
  padding: var(--space-1) var(--space-2);
}
.explorer-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-overlay) - 1);
}
.explorer-menu {
  position: fixed;
  z-index: var(--z-overlay);
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  padding: var(--space-1);
  display: flex;
  flex-direction: column;
  min-width: 140px;
}
.explorer-menu button {
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  text-align: left;
  min-height: 24px;
  padding: 0 var(--space-2);
  cursor: pointer;
  font-size: var(--font-sm);
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.explorer-menu button:hover {
  background: var(--surface-active);
  color: var(--text);
}
.explorer-menu button:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: calc(-1 * var(--focus-ring-offset));
}
.explorer-preview {
  border-top: var(--border-w) solid var(--border);
  max-height: 40%;
  overflow: auto;
}
.preview-head {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  align-items: center;
}
.preview-path {
  font-weight: 600;
}
.preview-meta {
  color: var(--text-muted);
  font-size: var(--font-xs);
}
.preview-text {
  padding: var(--space-2);
  white-space: pre-wrap;
  word-break: break-all;
  font-size: var(--font-sm);
  margin: 0;
}
.preview-image {
  max-width: 100%;
  max-height: 300px;
  display: block;
  margin: var(--space-2) auto;
}
.explorer-mini {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: var(--font-xs);
}
.artifacts-group {
  margin: var(--space-1) var(--space-2) 2px;
  color: var(--text-muted);
  font-size: var(--font-xs);
  text-transform: uppercase;
}
</style>
