<script setup lang="ts">
/**
 * Workspace Explorer + Agent Artifacts.
 *
 * Stage 3 (3c, WX-01/02): lazy tree, containment-enforced file actions and
 * the merged artifact index.
 *
 * Stage 11 (11c): VS Code-style operations — single-click selects (files no
 * longer preview, D11-01; the Artifacts panel keeps click-to-preview,
 * D11-16), double-click/Enter opens, dir click toggles; toolbar new-file /
 * new-folder / refresh (selection-aware target, D11-17); target-aware context
 * menus (root/dir/file); inline create/rename name input with instant
 * validation and error-preserving conflicts (D11-06); in-app copy/paste
 * clipboard (D11-02/03). All mutations run through the Rust containment
 * gate (D11-04); the frontend only ever passes relative paths.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type ComponentPublicInstance } from "vue";
import { useI18n } from "vue-i18n";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { errorCodeOf, useWorkspaceExplorerStore } from "../../stores/workspaceExplorer";
import { useRuntimeStore } from "../../stores/runtime";
import { WORKSPACE_PATH_MIME } from "../../lib/workspaceDnd";
import { validateBasename } from "./basename";
import TypeIcon from "./TypeIcon.vue";
import type { WorkspaceNode } from "../../types";

const { t, te } = useI18n();
const explorer = useWorkspaceExplorerStore();
const runtime = useRuntimeStore();

const selected = ref<string | null>(null);
/** Roving focus index into `visibleNodes` (APG tree pattern). */
const focusIndex = ref(-1);

// --- Stage 11: target-aware context menu ---

type MenuTarget =
  | { kind: "root" }
  | { kind: "dir"; relativePath: string }
  /** `renamable`: the row exists in the loaded tree, so the inline rename
   *  input has a row to replace. Artifact-panel rows may not be loaded. */
  | { kind: "file"; relativePath: string; renamable: boolean };

interface MenuAction {
  id: string;
  label: string;
  disabled?: boolean;
  /** Disabled reason (tooltip / a11y) — a disabled item must still explain
   *  itself instead of silently doing nothing (03 §3). */
  reason?: string;
  run: () => void;
}

const menu = ref<{ target: MenuTarget; x: number; y: number } | null>(null);

// --- Stage 11: transient status feedback (bottom-right chip) ---

const status = ref<{ key: string; params?: Record<string, string>; tone: "ok" | "warn" } | null>(null);
let statusTimer: number | null = null;

function flash(key: string, params?: Record<string, string>, tone: "ok" | "warn" = "ok") {
  status.value = { key, params, tone };
  if (statusTimer !== null) window.clearTimeout(statusTimer);
  statusTimer = window.setTimeout(() => (status.value = null), 2200);
}

/** Stable WB_ERR_* code → i18n key (UI never parses message text, 06 §2). */
function errorI18nKey(e: unknown): string {
  switch (errorCodeOf(e)) {
    case "WB_ERR_WORKSPACE_CONFLICT": return "explorer.error.conflict";
    case "WB_ERR_WORKSPACE_INVALID": return "explorer.error.invalid";
    case "WB_ERR_WORKSPACE_NOT_FOUND": return "explorer.error.notFound";
    case "WB_ERR_WORKSPACE_READ_ONLY": return "explorer.error.readOnly";
    case "WB_ERR_WORKSPACE_IO": return "explorer.error.io";
    default: return "explorer.error.default";
  }
}

// --- Stage 11: inline create/rename name input (D11-06) ---

type Pending =
  | { mode: "create"; isDir: boolean; parentDir: string }
  | { mode: "rename"; relativePath: string; isDir: boolean };

const pending = ref<Pending | null>(null);
const pendingName = ref("");
/** i18n key under `explorer.nameError.*` / `explorer.error.*`; null = valid. */
const pendingError = ref<string | null>(null);
const nameInputEl = ref<HTMLInputElement | null>(null);

/** Function ref (NOT a string ref): inside a v-for a string ref collects an
 *  ARRAY of elements, but only one naming input ever mounts at a time — the
 *  function ref hands us that single element (or null on unmount). */
function setNameInputEl(el: Element | ComponentPublicInstance | null) {
  nameInputEl.value = (el as HTMLInputElement | null) ?? null;
}

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

// A workspace switch invalidates every row-relative UI state: selection,
// pending input, menu and roving focus must not survive into the new tree
// (06 §3: any new state must say how it is cleaned on workspace switch).
watch(
  () => explorer.workspace,
  () => {
    selected.value = null;
    pending.value = null;
    pendingError.value = null;
    menu.value = null;
    focusIndex.value = -1;
  },
);


function isExpanded(node: WorkspaceNode): boolean {
  return explorer.isExpanded(node.relative_path);
}

/** Tree depth for indentation: number of path segments below the workspace root. */
function depthOf(node: WorkspaceNode): number {
  if (!node.relative_path) return 0;
  return node.relative_path.split("/").length - 1;
}

function parentOf(relativePath: string): string {
  const idx = relativePath.lastIndexOf("/");
  return idx >= 0 ? relativePath.slice(0, idx) : "";
}

/** Stage 11 (D11-01): single click SELECTS. Files no longer preview; dirs
 *  toggle. The Artifacts panel keeps click-to-preview (D11-16). */
function onSelect(node: WorkspaceNode) {
  selected.value = node.relative_path;
  menu.value = null;
  if (node.kind === "dir") {
    void explorer.toggleDir(node.relative_path);
  }
}

/** Double-click / Enter: files open with the system app, dirs toggle. */
function onOpen(node: WorkspaceNode) {
  if (node.kind === "dir") {
    void explorer.toggleDir(node.relative_path);
    return;
  }
  void explorer.openFile(node.relative_path);
}

async function copyRelativePath(relativePath: string) {
  const abs = await explorer.copyPath(relativePath);
  if (abs) {
    try {
      await writeText(abs);
    } catch {
      // clipboard unavailable; keep the copied feedback but do not crash
    }
    flash("explorer.status.copiedPath");
  }
}

/** Copy FILE/FOLDER action: only the in-app Explorer clipboard is touched —
 *  the OS text clipboard is reserved for copy-PATH (D11-02). */
function copyEntryToClipboard(relativePath: string, kind: "file" | "dir") {
  explorer.setClipboardEntry(relativePath, kind);
  flash(kind === "dir" ? "explorer.status.copiedFolder" : "explorer.status.copiedFile", {
    name: fileName(relativePath),
  });
}

/** Resolve a node by relative path across loaded tree levels. */
function nodeOf(rel: string): WorkspaceNode | null {
  for (const list of Object.values(explorer.tree)) {
    const hit = list.find((n) => n.relative_path === rel);
    if (hit) return hit;
  }
  return null;
}

// --- Stage 11 (11d): drag a FILE row into the terminal (D11-09/10) ---
// The payload is ONLY the workspace-relative path under the controlled MIME;
// the container-path mapping and quoting happen at the terminal drop edge.

const draggingPath = ref<string | null>(null);

function onDragStart(node: WorkspaceNode, e: DragEvent) {
  // Dirs never start a terminal drag (misreading a folder as a file argument
  // is exactly what D11-09 avoids).
  if (node.kind !== "file" || !e.dataTransfer) {
    e.preventDefault();
    return;
  }
  e.dataTransfer.setData(WORKSPACE_PATH_MIME, node.relative_path);
  e.dataTransfer.effectAllowed = "copy";
  draggingPath.value = node.relative_path;
}

function onDragEnd() {
  draggingPath.value = null;
}

function selectedNode(): WorkspaceNode | null {
  return selected.value ? nodeOf(selected.value) : null;
}

/** Toolbar target directory (D11-17): selected dir → inside it; selected
 *  file → its parent; nothing selected → workspace root. */
function toolbarTargetDir(): string {
  const node = selectedNode();
  if (!node) return "";
  if (node.kind === "dir") return node.relative_path;
  return parentOf(node.relative_path);
}

// --- create / rename flows ---

/** Segment count of a relative dir ("" = 0). */
function segments(dir: string): number {
  return dir === "" ? 0 : dir.split("/").length;
}

/** Indent for the create input: one level below the target dir. */
const createIndentPx = computed(() => {
  if (pending.value?.mode === "create") {
    return 8 + (segments(pending.value.parentDir) + 1) * 16;
  }
  return 24;
});

async function beginCreate(isDir: boolean, parentDir: string) {
  if (!runtime.workspace) return;
  menu.value = null;
  // Expand (and list) the target dir first so the input row lands inside a
  // visible subtree; the root is always visible.
  if (parentDir !== "") {
    if (!explorer.isExpanded(parentDir)) {
      await explorer.toggleDir(parentDir);
    }
    if (!explorer.tree[parentDir]) {
      await explorer.loadDir(parentDir, true);
    }
  }
  pending.value = { mode: "create", isDir, parentDir };
  pendingName.value = "";
  pendingError.value = null;
  await focusNameInput(true);
}

async function beginRename(relativePath: string) {
  const node = nodeOf(relativePath);
  if (!node) return; // rename needs a loaded row to host the inline input
  menu.value = null;
  selected.value = relativePath;
  pending.value = { mode: "rename", relativePath, isDir: node.kind === "dir" };
  pendingName.value = node.name;
  pendingError.value = null;
  await focusNameInput(false);
}

async function focusNameInput(selectAll: boolean) {
  await nextTick();
  const el = nameInputEl.value;
  if (!el) return;
  el.focus();
  if (selectAll) {
    el.select();
    return;
  }
  // Rename: select the basename, keep the extension (VS Code convention).
  const dot = el.value.lastIndexOf(".");
  el.setSelectionRange(0, dot > 0 ? dot : el.value.length);
}

/** Instant frontend validation (Rust re-validates on submit, D11-22). */
function onNameInput() {
  pendingError.value = (() => {
    const err = validateBasename(pendingName.value);
    return err ? `explorer.nameError.${err}` : null;
  })();
}

async function submitName() {
  const p = pending.value;
  if (!p) return;
  if (validateBasename(pendingName.value)) return; // invalid: keep the input
  try {
    const result =
      p.mode === "create"
        ? await explorer.createEntry(p.parentDir, pendingName.value, p.isDir)
        : await explorer.renameEntry(p.relativePath, pendingName.value);
    // Clear pending BEFORE the input unmounts so the blur handler no-ops.
    pending.value = null;
    pendingError.value = null;
    selected.value = result.relative_path;
    focusPath(result.relative_path);
    flash(p.mode === "create" ? "explorer.status.created" : "explorer.status.renamed", {
      name: fileName(result.relative_path),
    });
  } catch (e) {
    // Backend rejection (conflict / invalid / …): keep the input open and
    // show the stable error next to it (03 §4).
    pendingError.value = errorI18nKey(e);
    await focusNameInput(p.mode === "create");
  }
}

function cancelName() {
  const p = pending.value;
  pending.value = null;
  pendingError.value = null;
  // Focus restore (03 §4): back to the row that hosted the input.
  void focusRow(p?.mode === "rename" ? p.relativePath : null);
}

/** Blur commits only when non-empty and locally valid (03 §4). Escape and
 *  successful submits clear `pending` before the blur event lands, so this
 *  only fires for genuine focus loss (clicking elsewhere). */
function onNameBlur() {
  const p = pending.value;
  if (!p) return;
  if (pendingName.value && !validateBasename(pendingName.value)) {
    void submitName();
  } else {
    cancelName();
  }
}

function isRenaming(node: WorkspaceNode): boolean {
  return pending.value?.mode === "rename" && pending.value.relativePath === node.relative_path;
}

/** Create input renders right below the target dir row (first-child slot);
 *  for the root target it renders above the first row (or alone in an empty
 *  tree — handled by the standalone template branch). */
function createInputAfterNode(node: WorkspaceNode): boolean {
  return pending.value?.mode === "create" && node.relative_path === pending.value.parentDir;
}

function focusPath(relativePath: string) {
  focusIndex.value = explorer.visibleNodes.findIndex((n) => n.relative_path === relativePath);
}

async function focusRow(relativePath: string | null) {
  await nextTick();
  if (!relativePath) return;
  const el = document.querySelector<HTMLElement>(
    `[data-path="${CSS.escape(relativePath)}"]`,
  );
  el?.focus();
}

// --- paste ---

async function pasteInto(destinationDir: string) {
  menu.value = null;
  try {
    const result = await explorer.pasteEntry(destinationDir);
    selected.value = result.relative_path;
    focusPath(result.relative_path);
    flash("explorer.status.pasted", { name: fileName(result.relative_path) });
  } catch (e) {
    flash(errorI18nKey(e), undefined, "warn");
  }
}

// --- context menu assembly ---

function buildMenuItems(target: MenuTarget): MenuAction[] {
  const actions: MenuAction[] = [];
  const pasteDisabled = !explorer.canPaste();
  const noWorkspace = !runtime.workspace;
  if (target.kind === "root") {
    actions.push(
      { id: "new-file", label: t("explorer.menu.newFile"), disabled: noWorkspace, run: () => void beginCreate(false, "") },
      { id: "new-folder", label: t("explorer.menu.newFolder"), disabled: noWorkspace, run: () => void beginCreate(true, "") },
      {
        id: "paste",
        label: t("explorer.menu.paste"),
        disabled: pasteDisabled,
        reason: pasteDisabled ? t("explorer.paste.disabled") : undefined,
        run: () => void pasteInto(""),
      },
      { id: "refresh", label: t("explorer.menu.refresh"), run: refreshFromMenu },
    );
    return actions;
  }
  if (target.kind === "dir") {
    actions.push(
      {
        id: "toggle",
        label: t("explorer.menu.toggle"),
        run: () => {
          menu.value = null;
          void explorer.toggleDir(target.relativePath);
        },
      },
      { id: "reveal", label: t("explorer.reveal"), run: () => void revealFromMenu(target) },
      { id: "new-file", label: t("explorer.menu.newFile"), run: () => void beginCreate(false, target.relativePath) },
      { id: "new-folder", label: t("explorer.menu.newFolder"), run: () => void beginCreate(true, target.relativePath) },
      {
        id: "paste",
        label: t("explorer.menu.paste"),
        disabled: pasteDisabled,
        reason: pasteDisabled ? t("explorer.paste.disabled") : undefined,
        run: () => void pasteInto(target.relativePath),
      },
      {
        id: "copy-entry",
        label: t("explorer.menu.copyFolder"),
        run: () => {
          menu.value = null;
          copyEntryToClipboard(target.relativePath, "dir");
        },
      },
      { id: "rename", label: t("explorer.menu.rename"), run: () => void beginRename(target.relativePath) },
      { id: "refresh", label: t("explorer.menu.refresh"), run: refreshFromMenu },
    );
    return actions;
  }
  // file target
  actions.push(
    { id: "open", label: t("explorer.open"), run: () => void openFromMenu(target) },
    { id: "reveal", label: t("explorer.reveal"), run: () => void revealFromMenu(target) },
    {
      id: "copy-entry",
      label: t("explorer.menu.copyFile"),
      run: () => {
        menu.value = null;
        copyEntryToClipboard(target.relativePath, "file");
      },
    },
    {
      id: "copy-path",
      label: t("explorer.copy"),
      run: () => {
        menu.value = null;
        void copyRelativePath(target.relativePath);
      },
    },
  );
  if (target.renamable) {
    actions.push({ id: "rename", label: t("explorer.menu.rename"), run: () => void beginRename(target.relativePath) });
  }
  return actions;
}

async function openFromMenu(target: MenuTarget) {
  menu.value = null;
  if (target.kind === "dir") {
    await explorer.toggleDir(target.relativePath);
    return;
  }
  if (target.kind === "root") return;
  await explorer.openFile(target.relativePath);
}

async function revealFromMenu(target: MenuTarget) {
  menu.value = null;
  if (target.kind === "root") return;
  await explorer.revealFile(target.relativePath);
}

function refreshFromMenu() {
  menu.value = null;
  void explorer.refreshRoot();
}

const menuItems = computed<MenuAction[]>(() => (menu.value ? buildMenuItems(menu.value.target) : []));

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

function openMenuAt(target: MenuTarget, clientX: number, clientY: number) {
  const items = buildMenuItems(target);
  const zoom = appZoom();
  const menuWidth = 200;
  const menuHeight = 12 + items.length * 26;
  menu.value = {
    target,
    x: Math.max(4, Math.min(clientX / zoom, window.innerWidth / zoom - menuWidth)),
    y: Math.max(4, Math.min(clientY / zoom, window.innerHeight / zoom - menuHeight)),
  };
}

function onRowContextMenu(node: WorkspaceNode, event: MouseEvent) {
  selected.value = node.relative_path;
  openMenuAt(
    node.kind === "dir"
      ? { kind: "dir", relativePath: node.relative_path }
      : { kind: "file", relativePath: node.relative_path, renamable: true },
    event.clientX,
    event.clientY,
  );
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

/** Select + preview a file from an artifact/unattributed row. The Artifacts
 *  panel keeps click-to-preview (D11-16); only the file tree moved to
 *  select-only. Double-click still opens. */
async function onArtifactSelect(relativePath: string) {
  selected.value = relativePath;
  menu.value = null;
  await explorer.previewFile(relativePath);
}

function focusNode(index: number) {
  const total = explorer.visibleNodes.length;
  if (total === 0) {
    focusIndex.value = -1;
    return;
  }
  focusIndex.value = (index + total) % total;
}

/** APG tree keyboard: Arrow/Home/End move focus; Enter activates (open /
 *  toggle, D11-19); Space selects only; Shift+F10 / Menu open the context
 *  menu on the focused row. */
function onTreeKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    menu.value = null;
    return;
  }
  const menuKey = (e.key === "F10" && e.shiftKey) || e.key === "ContextMenu";
  if (menuKey) {
    const node = explorer.visibleNodes[focusIndex.value];
    if (node) {
      e.preventDefault();
      selected.value = node.relative_path;
      openMenuAt(
        node.kind === "dir"
          ? { kind: "dir", relativePath: node.relative_path }
          : { kind: "file", relativePath: node.relative_path, renamable: true },
        40,
        60 + focusIndex.value * 24,
      );
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
  } else if (e.key === "Enter") {
    const node = explorer.visibleNodes[focusIndex.value];
    if (node) {
      e.preventDefault();
      onOpen(node);
    }
  } else if (e.key === " ") {
    const node = explorer.visibleNodes[focusIndex.value];
    if (node) {
      e.preventDefault();
      selected.value = node.relative_path;
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
      <!-- Stage 11 (11c): VS Code-density action row. Icon-only so Compact
           widths never squeeze the tabs (03 §2). -->
      <div class="explorer-actions">
        <button
          class="ui-icon-button sm"
          type="button"
          :aria-label="t('explorer.toolbar.newFile')"
          :title="t('explorer.toolbar.newFile')"
          :disabled="!runtime.workspace"
          @click="beginCreate(false, toolbarTargetDir())"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
            <path d="M4 1.5h5l3 3v10H4z" />
            <path d="M9 1.5v3h3" />
            <path d="M8.5 9.5h4M10.5 7.5v4" />
          </svg>
        </button>
        <button
          class="ui-icon-button sm"
          type="button"
          :aria-label="t('explorer.toolbar.newFolder')"
          :title="t('explorer.toolbar.newFolder')"
          :disabled="!runtime.workspace"
          @click="beginCreate(true, toolbarTargetDir())"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
            <path d="M1.5 3.5h4.5l1.5 2h7v7h-13z" />
            <path d="M8.5 10.5h4M10.5 8.5v4" />
          </svg>
        </button>
        <button
          class="ui-icon-button sm"
          type="button"
          :aria-label="t('explorer.refresh')"
          :title="t('explorer.refresh')"
          :disabled="!runtime.workspace"
          @click="explorer.refreshRoot()"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
            <path d="M13 8a5 5 0 1 1-1.6-3.7" />
            <path d="M13 2.5v3h-3" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="explorer.stale" class="explorer-stale" role="status">
      {{ t("explorer.stale") }}
    </div>

    <!-- 10e: cross-fade between the tree and artifacts panels (out-in). -->
    <Transition name="fade" mode="out-in">
    <!-- Explorer tree -->
    <div
      v-if="artifactFilter === 'explorer'"
      key="tree"
      class="explorer-body"
      role="tree"
      aria-orientation="vertical"
      @keydown="onTreeKeydown"
      @contextmenu.prevent="openMenuAt({ kind: 'root' }, $event.clientX, $event.clientY)"
    >
      <p v-if="!runtime.workspace" class="explorer-empty">{{ t("explorer.empty.workspace") }}</p>
      <p
        v-else-if="explorer.visibleNodes.length === 0 && !explorer.isLoading('') && !explorer.errors[''] && pending === null"
        class="explorer-empty"
      >
        {{ t("explorer.empty.files") }}
      </p>
      <template v-else>
        <!-- Root-level create input: above the first row (or alone when the
             tree is empty — the v-for below never runs). -->
        <div
          v-if="pending?.mode === 'create' && pending.parentDir === ''"
          class="explorer-row name-input-row"
          :style="{ paddingLeft: `${createIndentPx}px` }"
        >
          <input
            :ref="setNameInputEl"
            v-model="pendingName"
            type="text"
            data-testid="name-input"
            class="explorer-name-input"
            :placeholder="pending.isDir ? t('explorer.nameInput.folder') : t('explorer.nameInput.file')"
            :aria-label="pending.isDir ? t('explorer.nameInput.folder') : t('explorer.nameInput.file')"
            @input="onNameInput"
            @keydown.enter.prevent="submitName"
            @keydown.esc.stop.prevent="cancelName"
            @blur="onNameBlur"
          />
          <span v-if="pendingError" class="name-error" role="alert">{{ t(pendingError) }}</span>
        </div>

        <template v-for="(node, i) in explorer.visibleNodes" :key="node.relative_path">
          <div
            :class="['explorer-row', { selected: selected === node.relative_path, dragging: draggingPath === node.relative_path }]"
            :data-path="node.relative_path"
            role="treeitem"
            :aria-selected="selected === node.relative_path"
            :aria-expanded="node.kind === 'dir' ? isExpanded(node) : undefined"
            :aria-level="depthOf(node) + 1"
            :tabindex="i === focusIndex ? 0 : -1"
            :style="{ paddingLeft: `${8 + depthOf(node) * 16}px` }"
            :draggable="node.kind === 'file'"
            @click="onSelect(node)"
            @dblclick="onOpen(node)"
            @contextmenu.prevent.stop="onRowContextMenu(node, $event)"
            @dragstart="onDragStart(node, $event)"
            @dragend="onDragEnd"
            @focus="focusIndex = i"
          >
            <span class="explorer-twisty" aria-hidden="true">
              {{ node.kind === "dir" ? (isExpanded(node) ? "▾" : "▸") : "" }}
            </span>
            <TypeIcon
              class="explorer-typeicon"
              :name="node.name"
              :dir="node.kind === 'dir'"
              :expanded="isExpanded(node)"
            />
            <!-- Stage 11 (11c): rename swaps the name span for the inline
                 input; the row itself (indent, icon) stays in place. -->
            <template v-if="isRenaming(node)">
              <input
                :ref="setNameInputEl"
                v-model="pendingName"
                type="text"
                data-testid="name-input"
                class="explorer-name-input"
                :placeholder="pending?.isDir ? t('explorer.nameInput.folder') : t('explorer.nameInput.file')"
                :aria-label="t('explorer.menu.rename')"
                @input="onNameInput"
                @keydown.enter.prevent="submitName"
                @keydown.esc.stop.prevent="cancelName"
                @blur="onNameBlur"
              />
              <span v-if="pendingError" class="name-error" role="alert">{{ t(pendingError) }}</span>
            </template>
            <template v-else>
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
            </template>
          </div>
          <!-- Create input for a non-root target: first-child slot under the
               (expanded) target dir row. -->
          <div
            v-if="createInputAfterNode(node)"
            class="explorer-row name-input-row"
            :style="{ paddingLeft: `${createIndentPx}px` }"
          >
            <input
              :ref="setNameInputEl"
              v-model="pendingName"
              type="text"
              data-testid="name-input"
              class="explorer-name-input"
              :placeholder="pending?.mode === 'create' && pending.isDir ? t('explorer.nameInput.folder') : t('explorer.nameInput.file')"
              :aria-label="pending?.mode === 'create' && pending.isDir ? t('explorer.nameInput.folder') : t('explorer.nameInput.file')"
              @input="onNameInput"
              @keydown.enter.prevent="submitName"
              @keydown.esc.stop.prevent="cancelName"
              @blur="onNameBlur"
            />
            <span v-if="pendingError" class="name-error" role="alert">{{ t(pendingError) }}</span>
          </div>
        </template>

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
    <div v-else key="artifacts" class="explorer-body artifacts-panel">
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
            @contextmenu.prevent.stop="openMenuAt({ kind: 'file', relativePath: a.workspace_relative_path, renamable: nodeOf(a.workspace_relative_path) !== null }, $event.clientX, $event.clientY)"
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
            @contextmenu.prevent.stop="openMenuAt({ kind: 'file', relativePath: a.workspace_relative_path, renamable: nodeOf(a.workspace_relative_path) !== null }, $event.clientX, $event.clientY)"
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
            @contextmenu.prevent.stop="openMenuAt({ kind: 'file', relativePath: a.workspace_relative_path, renamable: nodeOf(a.workspace_relative_path) !== null }, $event.clientX, $event.clientY)"
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
          @contextmenu.prevent.stop="openMenuAt({ kind: 'file', relativePath: u.relative_path, renamable: nodeOf(u.relative_path) !== null }, $event.clientX, $event.clientY)"
        >
          <span class="explorer-name" :title="hostPath(u.relative_path)">{{ artifactLabel(u.relative_path) }}</span>
          <span class="change-label">{{ changeLabel(u.change_type) }}</span>
        </div>
      </template>
    </div>
    </Transition>

    <!-- Context menu (10e: unified pop motion). Stage 11: items are built per
         target kind (root/dir/file) in buildMenuItems. -->
    <Transition name="pop">
    <div
      v-if="menu"
      class="explorer-menu"
      role="menu"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      @mousedown.stop
      @contextmenu.prevent
    >
      <button
        v-for="item in menuItems"
        :key="item.id"
        role="menuitem"
        :data-action="item.id"
        :disabled="item.disabled"
        :aria-disabled="item.disabled"
        :title="item.disabled ? item.reason : ''"
        @click="item.run()"
      >
        {{ item.label }}
      </button>
    </div>
    </Transition>

    <!-- Click-away backdrop: closes the menu without selecting a tree row. -->
    <div v-if="menu" class="explorer-menu-backdrop" @mousedown="menu = null" @contextmenu.prevent="menu = null" />

    <!-- Transient operation feedback (copy/paste/create/rename outcomes). -->
    <Transition name="pop">
      <div
        v-if="status"
        class="explorer-status"
        :class="{ warn: status.tone === 'warn' }"
        role="status"
      >
        {{ t(status.key, status.params ?? {}) }}
      </div>
    </Transition>

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
  position: relative;
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
.explorer-actions {
  display: flex;
  gap: 2px;
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
/* Stage 11 (11d): twisty slot (dirs only) + fixed-size type icon slot so
 * every row keeps the same two-slot rhythm without changing row height. */
.explorer-twisty {
  width: 14px;
  flex: none;
  color: var(--text-muted);
}
.explorer-typeicon {
  flex: none;
  color: var(--text-muted);
}
.explorer-row.dragging {
  opacity: 0.5;
}
.explorer-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
/* Stage 11 (11c): inline create/rename input. min-width:0 keeps the input
 * inside the padded row under CSS zoom / Compact widths (01 风险表). */
.explorer-name-input {
  flex: 1;
  min-width: 0;
  height: 20px;
  padding: 0 4px;
  background: var(--surface-3);
  color: var(--text);
  border: var(--border-w) solid var(--accent);
  border-radius: var(--radius-sm);
  font: inherit;
  outline: none;
}
/* Stable error shown next to the input, never closing it (03 §4). Anchored
 * below the row so it never reflows the tree. */
.name-error {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 2;
  margin-top: 2px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  box-shadow: var(--shadow-menu);
  color: var(--warn);
  font-size: var(--font-xs);
  white-space: nowrap;
}
.name-input-row {
  position: relative;
  cursor: default;
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
.explorer-menu button:hover:not(:disabled) {
  background: var(--surface-active);
  color: var(--text);
}
.explorer-menu button:disabled {
  color: var(--text-muted);
  cursor: default;
}
.explorer-menu button:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: calc(-1 * var(--focus-ring-offset));
}
/* Stage 11 (11c): transient operation feedback chip (bottom-right). */
.explorer-status {
  position: absolute;
  right: var(--space-2);
  bottom: var(--space-2);
  z-index: var(--z-overlay);
  max-width: calc(100% - var(--space-4));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  box-shadow: var(--shadow-menu);
  color: var(--text-muted);
  font-size: var(--font-xs);
  pointer-events: none;
}
.explorer-status.warn {
  color: var(--warn);
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
