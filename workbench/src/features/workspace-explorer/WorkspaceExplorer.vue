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
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useWorkspaceExplorerStore } from "../../stores/workspaceExplorer";
import { useRuntimeStore } from "../../stores/runtime";
import type { WorkspaceNode } from "../../types";

const { t } = useI18n();
const explorer = useWorkspaceExplorerStore();
const runtime = useRuntimeStore();

const selected = ref<string | null>(null);
const menuFor = ref<string | null>(null);
const copied = ref<string | null>(null);
/** Roving focus index into `visibleNodes` (APG tree pattern). */
const focusIndex = ref(-1);

/** Flatten the visible tree (root + expanded children, one level) for keyboard. */
const visibleNodes = computed<WorkspaceNode[]>(() => {
  const out: WorkspaceNode[] = [];
  for (const n of explorer.rootNodes) {
    out.push(n);
    if (n.kind === "dir" && explorer.isExpanded(n.relative_path)) {
      out.push(...explorer.nodeChildren(n.relative_path));
    }
  }
  return out;
});

const artifactFilter = computed(() => explorer.activeKind);

onMounted(() => {
  if (runtime.workspace && explorer.workspace !== runtime.workspace) {
    explorer.setWorkspace(runtime.workspace);
    void explorer.refreshRoot();
  }
});

function isExpanded(node: WorkspaceNode): boolean {
  return explorer.isExpanded(node.relative_path);
}

async function onToggle(node: WorkspaceNode) {
  if (node.kind !== "dir") return;
  await explorer.toggleDir(node.relative_path);
}

/** Tree depth for indentation: 0 = root, 1 = child of an expanded dir. */
function depthOf(node: WorkspaceNode): number {
  const idx = node.relative_path.lastIndexOf("/");
  if (idx < 0) return 0;
  return explorer.isExpanded(node.relative_path.slice(0, idx)) ? 1 : 0;
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
  if (node.kind !== "file") return;
  await explorer.openFile(node.relative_path);
}

async function onReveal(node: WorkspaceNode) {
  if (node.kind !== "file") return;
  await explorer.revealFile(node.relative_path);
}

async function onCopy(node: WorkspaceNode) {
  const abs = await explorer.copyPath(node.relative_path);
  if (abs) {
    await navigator.clipboard?.writeText(abs).catch(() => {});
    copied.value = node.relative_path;
    setTimeout(() => (copied.value = null), 1500);
  }
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
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
  const total = visibleNodes.value.length;
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
    const node = visibleNodes.value[focusIndex.value];
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
    focusNode(visibleNodes.value.length - 1);
  } else if (e.key === "Enter" || e.key === " ") {
    const node = visibleNodes.value[focusIndex.value];
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
          @click="explorer.activeKind = 'explorer'"
        >
          {{ t("explorer.tab.files") }}
        </button>
        <button
          role="tab"
          :aria-selected="explorer.activeKind === 'artifacts'"
          class="explorer-tab"
          :class="{ active: explorer.activeKind === 'artifacts' }"
          @click="explorer.activeKind = 'artifacts'"
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
      <template v-else>
        <div
          v-for="(node, i) in visibleNodes"
          :key="node.relative_path"
          :class="['explorer-row', { selected: selected === node.relative_path }]"
          role="treeitem"
          :aria-selected="selected === node.relative_path"
          :aria-expanded="node.kind === 'dir' ? isExpanded(node) : undefined"
          :tabindex="i === focusIndex ? 0 : -1"
          :style="{ paddingLeft: `${8 + depthOf(node) * 16}px` }"
          @click="onSelect(node)"
          @dblclick="node.kind === 'file' && onOpen(node)"
          @contextmenu.prevent="menuFor = node.relative_path"
          @focus="focusIndex = i"
        >
          <span class="explorer-icon" aria-hidden="true">
            {{ node.kind === "dir" ? (isExpanded(node) ? "▾" : "▸") : "·" }}
          </span>
          <span class="explorer-name">{{ node.name }}</span>
          <span
            v-for="badge in node.artifact_badges"
            :key="badge"
            class="explorer-badge"
            >{{ badge }}</span
          >
        </div>
        <p v-if="explorer.errors['']" class="explorer-error">{{ explorer.errors[""] }}</p>
      </template>
    </div>

    <!-- Artifacts panel -->
    <div v-else class="explorer-body artifacts-panel">
      <p v-if="explorer.artifactsLoading">{{ t("explorer.loading") }}</p>
      <template v-else>
        <p v-if="explorer.artifactDeliverables.length === 0" class="explorer-empty">
          {{ t("explorer.empty.artifacts") }}
        </p>
        <template v-else>
          <h4 class="artifacts-group">{{ t("explorer.artifacts.deliverables") }}</h4>
          <div
            v-for="a in explorer.artifactDeliverables"
            :key="a.artifact_id"
            class="explorer-row"
            @click="selected = a.workspace_relative_path"
          >
            <span class="explorer-name" :title="a.workspace_relative_path">
              {{ a.workspace_relative_path }}
            </span>
            <button class="explorer-mini" @click="explorer.openFile(a.workspace_relative_path)">
              {{ t("explorer.open") }}
            </button>
          </div>
        </template>

        <h4 v-if="explorer.unattributedEntries.length" class="artifacts-group">
          {{ t("explorer.artifacts.workspaceChanges") }}
        </h4>
        <div
          v-for="u in explorer.unattributedEntries"
          :key="u.relative_path"
          class="explorer-row unattributed"
          @click="selected = u.relative_path"
        >
          <span class="explorer-name" :title="u.relative_path">{{ u.relative_path }}</span>
          <span class="explorer-badge unattributed-badge">{{ u.change_type }}</span>
        </div>
      </template>
    </div>

    <!-- Context menu -->
    <div v-if="menuFor" class="explorer-menu" role="menu">
      <button role="menuitem" @click="onOpen(nodeOf(menuFor)!)">{{ t("explorer.open") }}</button>
      <button role="menuitem" @click="onReveal(nodeOf(menuFor)!)">
        {{ t("explorer.reveal") }}
      </button>
      <button role="menuitem" @click="onCopy(nodeOf(menuFor)!)">{{ t("explorer.copy") }}</button>
      <button class="menu-close" role="menuitem" @click="menuFor = null">✕</button>
    </div>

    <!-- Preview pane -->
    <div v-if="explorer.preview" class="explorer-preview">
      <div class="preview-head">
        <span class="preview-path">{{ explorer.preview.relative_path }}</span>
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
  font-size: 13px;
}
.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border, #333);
}
.explorer-tabs {
  display: flex;
  gap: 2px;
}
.explorer-tab {
  background: none;
  border: none;
  color: inherit;
  padding: 2px 8px;
  cursor: pointer;
  opacity: 0.7;
}
.explorer-tab.active {
  opacity: 1;
  border-bottom: 2px solid var(--accent, #4a9eff);
}
.explorer-refresh {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
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
  padding: 2px 8px;
  cursor: pointer;
  white-space: nowrap;
}
.explorer-row.selected {
  background: var(--selection, rgba(74, 158, 255, 0.18));
}
.explorer-icon {
  width: 14px;
  flex: none;
  color: var(--muted, #888);
}
.explorer-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.explorer-child {
  padding-left: 24px;
}
.explorer-badge {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 4px;
  background: var(--accent-dim, rgba(74, 158, 255, 0.15));
}
.unattributed {
  opacity: 0.75;
}
.unattributed-badge {
  background: var(--warn-dim, rgba(217, 164, 65, 0.15));
}
.explorer-stale,
.explorer-error {
  padding: 4px 8px;
  color: var(--warn, #d9a441);
  font-size: 12px;
}
.explorer-empty {
  padding: 8px;
  color: var(--muted, #888);
}
.explorer-menu {
  position: absolute;
  z-index: 20;
  background: var(--surface, #1e1e1e);
  border: 1px solid var(--border, #333);
  display: flex;
  flex-direction: column;
  min-width: 140px;
}
.explorer-menu button {
  background: none;
  border: none;
  color: inherit;
  text-align: left;
  padding: 4px 10px;
  cursor: pointer;
}
.explorer-menu button:hover {
  background: var(--selection, rgba(74, 158, 255, 0.18));
}
.explorer-preview {
  border-top: 1px solid var(--border, #333);
  max-height: 40%;
  overflow: auto;
}
.preview-head {
  display: flex;
  gap: 8px;
  padding: 4px 8px;
  align-items: center;
}
.preview-path {
  font-weight: 600;
}
.preview-meta {
  color: var(--muted, #888);
  font-size: 11px;
}
.preview-text {
  padding: 8px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  margin: 0;
}
.preview-image {
  max-width: 100%;
  max-height: 300px;
  display: block;
  margin: 8px auto;
}
.explorer-mini {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 11px;
}
.artifacts-group {
  margin: 6px 8px 2px;
  color: var(--muted, #888);
  font-size: 11px;
  text-transform: uppercase;
}
</style>
