<script setup lang="ts">
/**
 * IDEA-3 (3c): the workspace picker, extracted from App.vue's inline block.
 * Renders inside the launcher's WorkspaceView — typed path / browse / recents
 * from the shared history. Facade-bound (only the ACTIVE view mounts).
 *
 * v2.1.7 S2 (⑦⑧): recents cap at 8 with an inline "show all" toggle;
 * right-click / kebab menu offers the destructive "forget this workspace"
 * flow (preview dialog → single-IPC transaction); clicking a recent whose
 * path no longer exists offers the record-only clear.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkspacesStore } from "../../stores/workspaces";
import { useSettingsStore } from "../../stores/settings";
import type { ForgetPreview } from "../../types";
import ForgetConfirmDialog from "./ForgetConfirmDialog.vue";
import InvalidPathDialog from "./InvalidPathDialog.vue";
import { buildSearchMatcher } from "../../lib/search";

const { t } = useI18n();
const store = useRuntimeStore();
const wsStore = useWorkspacesStore();

// --- R4b: which machine this Workbench drives (store-routed, F-A01) ---
const settings = useSettingsStore();
void settings.load();
const target = computed(() => settings.target);
const targetError = computed(() => settings.targetError);
const switchTarget = (name: string | null) => settings.switchTarget(name);

function basename(p: string): string {
  // Both separators — Windows paths are backslashed (round-4 fix).
  const parts = p.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

// --- (⑦a) cap the recents at 8, inline expand/collapse ---
const RECENT_CAP = 8;
const expanded = ref(false);
const visibleRecents = computed(() => {
  const all = store.recentWorkspaces;
  if (expanded.value || all.length <= RECENT_CAP) return all;
  return all.slice(0, RECENT_CAP);
});
const hiddenCount = computed(
  () => store.recentWorkspaces.length - visibleRecents.value.length,
);

// --- (⑧) click guard: verify the path exists before launching preflight ---
// R4 (field #1/#5): a recent entry belongs to the machine its path names —
// a POSIX path is a REMOTE workspace. Clicking it under the wrong target
// auto-switches the drive target first (tunnels re-root), then probes.
const invalidPath = ref<string | null>(null);
function isRemotePath(path: string): boolean {
  return path.startsWith("/");
}
async function onRecentClick(path: string): Promise<void> {
  const pathRemote = isRemotePath(path);
  const nowRemote = target.value?.kind === "remote";
  if (pathRemote !== nowRemote) {
    // machine mismatch: switch so the probe runs on the right machine.
    // A remote path needs A machine — prefer the current one, else the
    // first configured profile (never a hardcoded name).
    const name = target.value?.machine?.name
      ?? settings.doc?.remoteMachines?.[0]?.name ?? null;
    await switchTarget(pathRemote ? name : null);
  }
  const exists = await wsStore.workspacePathExists(path);
  if (!exists) {
    invalidPath.value = path;
    return;
  }
  store.selectRecentWorkspace(path);
}
/* W3 手测 r11: dead-recent actions live in the workspaces store now
 * (shared with the app-level overlay); exportBusy stays local for the
 * ForgetConfirmDialog export hand-off. */
const exportBusy = ref(false);

/** W3 手测 r11: close-then-act wrappers over the shared store actions (the
 * bare inline arrows left the dialog open — the original local handlers
 * cleared invalidPath FIRST; the tests caught the regression). */
function onInvalidClear(purgeData: boolean): void {
  const path = invalidPath.value;
  invalidPath.value = null;
  if (path) void wsStore.clearInvalidRecent(path, purgeData);
}
async function onInvalidExport(): Promise<void> {
  const path = invalidPath.value;
  if (!path) return;
  exportBusy.value = true;
  try {
    await wsStore.exportInvalidRecent(path);
  } finally {
    exportBusy.value = false;
  }
}


// --- F2-B: remote directory browser (fs.list over the pooled serve
// channel, pinned at the remote $HOME; manual absolute input stays the
// escape hatch for anything outside the pin). Explorer mental model
// (field feedback): click selects, DOUBLE-click descends, the button
// confirms the selection. ---
const browse = ref<{ cwd: string; root: string; entries: { name: string; isDir: boolean }[] } | null>(null);
const browseSelected = ref<string | null>(null);
// Field #4/#5: hidden-dotdir toggle + fuzzy search over the current page
// (the S5 matcher — substring > subsequence, /re/ explicit regex).
const browseShowHidden = ref(false);
const browseQuery = ref("");

function onBrowse(): void {
  if (target.value?.kind === "remote") {
    // Start where the input points when it already names a remote path.
    const cur = store.workspace.trim();
    void openBrowse(cur.startsWith("/") ? cur : undefined);
  } else {
    store.pickWorkspace();
  }
}
async function openBrowse(start?: string): Promise<void> {
  const r = await wsStore.browseRemote(start, browseShowHidden.value);
  if (r) {
    browse.value = { cwd: r.cwd, root: r.root, entries: r.entries };
    browseSelected.value = null;
    browseQuery.value = "";
  }
}
async function loadBrowse(path: string): Promise<void> {
  if (!browse.value) return;
  const r = await wsStore.browseRemote(path, browseShowHidden.value);
  if (r) {
    browse.value.cwd = r.cwd;
    browse.value.root = r.root;
    browse.value.entries = r.entries;
    browseSelected.value = null;
    browseQuery.value = "";
  }
}
function toggleBrowseHidden(): void {
  browseShowHidden.value = !browseShowHidden.value;
  if (browse.value) void loadBrowse(browse.value.cwd);
}
function browseSelect(name: string): void {
  browseSelected.value = browseSelected.value === name ? null : name;
}
function browseInto(name: string): void {
  if (!browse.value) return;
  void loadBrowse(`${browse.value.cwd.replace(/\/+$/, "")}/${name}`);
}
function browseUp(): void {
  if (!browse.value) return;
  const { cwd, root } = browse.value;
  if (cwd === root) return;
  const rel = cwd.slice(root.length).replace(/^\/+|\/+$/g, "");
  const parts = rel.split("/").filter(Boolean);
  parts.pop();
  void loadBrowse(parts.length ? `${root.replace(/\/+$/, "")}/${parts.join("/")}` : root);
}
const browseVisible = computed(() => {
  const matcher = buildSearchMatcher(browseQuery.value);
  if (!browse.value) return [];
  if (!matcher) return browse.value.entries;
  return [...browse.value.entries]
    .map((e) => ({ e, rank: matcher(e.name.toLowerCase()) }))
    .filter((x) => x.rank > 0)
    .sort((a, b) => b.rank - a.rank || a.e.name.localeCompare(b.e.name))
    .map((x) => x.e);
});

const browseCrumbs = computed(() => {
  if (!browse.value) return [] as { label: string; path: string }[];
  const { cwd, root } = browse.value;
  const rel = cwd.slice(root.length).replace(/^\/+|\/+$/g, "");
  const segs = rel ? rel.split("/").filter(Boolean) : [];
  const rootLabel = root === "/" ? "/" : (root.split("/").filter(Boolean).pop() ?? "/");
  const out = [{ label: rootLabel, path: root }];
  let acc = root.replace(/\/+$/, "");
  for (const s of segs) {
    acc += `/${s}`;
    out.push({ label: s, path: acc });
  }
  return out;
});
/** The absolute path the confirm button would commit: the selected child
 *  when one is highlighted, else the current directory. */
const browseChoice = computed(() => {
  if (!browse.value) return "";
  const { cwd, root } = browse.value;
  return browseSelected.value
    ? `${cwd.replace(/\/+$/, "")}/${browseSelected.value}`
    : cwd === root
      ? root
      : cwd;
});
function chooseBrowse(): void {
  if (browse.value) store.workspace = browseChoice.value;
  browse.value = null;
}

// --- (⑦b) context menu: forget this workspace ---
const menuFor = ref<string | null>(null);
const menuLeft = ref(0);
const menuRight = ref<number | null>(null);
const menuTop = ref(0);
/** Live .app zoom (font_scale): the menu is position:fixed INSIDE the
 * zoomed .app, which re-scales fixed offsets — viewport pixels must be
 * divided by the zoom (Stage 11 two-space model, re-hit 2026-08-27). */
function appZoom(): number {
  const el = document.querySelector(".app");
  const z = el ? parseFloat(getComputedStyle(el).zoom || "1") : 1;
  return Number.isFinite(z) && z > 0 ? z : 1;
}
/** Anchor by viewport px; `fromRight` right-aligns (kebab path) so the
 * menu's own zoom-scaled WIDTH never shifts the anchor (0.8× manual test:
 * a fixed -170px left-offset over/undershot at every zoom but 1.5). */
function openMenuAt(path: string, vx: number, vy: number, fromRight?: number): void {
  const z = appZoom();
  menuFor.value = path;
  menuTop.value = Math.round(vy / z);
  if (fromRight !== undefined) {
    menuRight.value = Math.round(fromRight / z);
    menuLeft.value = 0;
  } else {
    menuLeft.value = Math.round(vx / z);
    menuRight.value = null;
  }
}
function openMenu(path: string, vx: number, vy: number): void {
  openMenuAt(path, vx, vy);
}
function openMenuAtButton(path: string, e: MouseEvent): void {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  openMenuAt(path, 0, r.bottom + 4, window.innerWidth - r.right + 8);
}
function closeMenu(): void {
  menuFor.value = null;
}
const menuStyle = computed(() =>
  menuRight.value !== null
    ? { right: `${menuRight.value}px`, top: `${menuTop.value}px` }
    : { left: `${menuLeft.value}px`, top: `${menuTop.value}px` },
);

const forgetPreview = ref<ForgetPreview | null>(null);
const forgetBusy = ref(false);
const forgetError = ref<string | null>(null);
/** Rejected Tauri commands arrive as serialized WorkbenchError OBJECTS —
 * String(e) rendered "[object Object]" (2026-08-27 manual test). The real
 * detail rides `technical_detail` (snake_case wire shape). */
function errText(e: unknown): string {
  if (e instanceof Error) return e.message;
  const w = e as { technical_detail?: string; message?: string; code?: string };
  const body = w?.technical_detail || w?.message || "";
  const code = w?.code ? ` (${w.code})` : "";
  return (body ? `${body}${code}` : code || JSON.stringify(e));
}
async function startForget(path: string): Promise<void> {
  closeMenu();
  forgetError.value = null;
  try {
    forgetPreview.value = await wsStore.forgetPreview(path);
  } catch (e) {
    forgetError.value = errText(e);
    forgetPreview.value = null;
  }
}
/** 2.1.11 P1-3: rescue-export from the forget dialog (memories/configs as
 * zip; the dialog stays open — the destructive confirm is still manual). */
async function exportForgetLifecycle(): Promise<void> {
  const preview = forgetPreview.value;
  if (!preview || exportBusy.value) return;
  exportBusy.value = true;
  try {
    await wsStore.exportLifecycle(preview.workspacePath);
  } catch {
    /* best-effort rescue path */
  } finally {
    exportBusy.value = false;
  }
}

async function confirmForget(): Promise<void> {
  const preview = forgetPreview.value;
  if (!preview || forgetBusy.value) return;
  forgetBusy.value = true;
  try {
    await wsStore.forgetWorkspace(preview.workspacePath);
    forgetPreview.value = null;
  } catch (e) {
    // CAS conflict / transient failure: keep the dialog open with the error
    // — the store has reloaded its revision, so a retry is meaningful.
    forgetError.value = errText(e);
  } finally {
    forgetBusy.value = false;
  }
}
</script>

<template>
  <div class="picker">
    <h2>{{ t("picker.title") }}</h2>
    <div class="row">
      <input
        v-model="store.workspace"
        class="workspace"
        :placeholder="t('picker.placeholder')"
        @keyup.enter="store.runPreflight()"
      />
      <!-- F2-B: local keeps the native dialog; remote opens the fs.list
           browse popover (pinned at the remote $HOME). -->
      <button
        class="ui-button"
        :title="target?.kind === 'remote' ? t('picker.browseRemoteHint') : undefined"
        @click="onBrowse()"
      >{{ t("picker.browse") }}</button>
      <button class="ui-button primary" :disabled="!store.workspace.trim()" @click="store.runPreflight()">{{ t("picker.next") }}</button>
    </div>
    <!-- R4b: machine switcher — local machine or a settings.remoteMachines
         entry. Switching tears every tunnel down (backend) and re-roots all
         ops on the new machine. -->
    <div class="target-row">
      <span class="target-label">{{ t("picker.target.label") }}</span>
      <select
        class="target-select"
        :value="target?.machine?.name ?? ''"
        @change="switchTarget(($event.target as HTMLSelectElement).value || null)"
      >
        <option value="">{{ t("picker.target.local") }}</option>
        <option v-for="m in settings.doc?.remoteMachines ?? []" :key="m.name" :value="m.name">
          {{ m.name }} ({{ m.user ? `${m.user}@` : "" }}{{ m.host }}{{ m.port ? `:${m.port}` : "" }})
        </option>
      </select>
      <span v-if="target?.kind === 'remote'" class="target-badge">{{ t("picker.target.remoteOn", { name: target.machine?.name }) }}</span>
    </div>
    <p v-if="targetError" class="forget-error" role="alert">{{ targetError }}</p>

    <p class="hint">{{ t("picker.hint") }}</p>

    <div v-if="store.recentWorkspaces.length" class="recents ui-section">
      <div class="recents-label ui-section-title">{{ t("picker.recents") }}</div>
      <ul>
        <li v-for="w in visibleRecents" :key="w.path">
          <div class="recent-wrap">
            <button
              class="recent ui-section-row interactive"
              :title="w.path"
              @click="onRecentClick(w.path)"
              @contextmenu.prevent="openMenu(w.path, $event.clientX, $event.clientY)"
            >
              <span class="r-name">{{ basename(w.path) }}</span>
              <span v-if="isRemotePath(w.path)" class="r-machine" :title="w.path">{{ t("picker.target.remoteTag") }}</span>
              <span class="r-path">{{ w.path }}</span>
            </button>
            <button
              class="kebab"
              :aria-label="t('picker.rowMenu')"
              :aria-haspopup="menuFor === w.path ? 'true' : undefined"
              aria-expanded="false"
              @click="openMenuAtButton(w.path, $event)"
              @keydown.escape="closeMenu"
            >⋯</button>
          </div>
        </li>
      </ul>
      <button v-if="hiddenCount > 0" class="expand ui-button quiet" @click="expanded = true">
        {{ t("picker.showAll", { n: hiddenCount }) }}
      </button>
      <button v-else-if="expanded && store.recentWorkspaces.length > RECENT_CAP" class="expand ui-button quiet" @click="expanded = false">
        {{ t("picker.collapse") }}
      </button>
    </div>

    <!-- right-click / kebab context menu (single destructive action). Inside
         .app (inherits the font-scale zoom) with viewport coords divided by
         the live zoom — the Stage 11 two-space model. -->
    <div v-if="menuFor" class="ctx-overlay" @mousedown="closeMenu" @contextmenu.prevent="closeMenu" />
    <div
      v-if="menuFor"
      class="ctx"
      role="menu"
      :style="menuStyle"
      @keydown.escape="closeMenu"
    >
      <button role="menuitem" class="ctx-item danger" @click="startForget(menuFor)">
        {{ t("picker.ctxForget") }}
      </button>
    </div>

    <p v-if="forgetError && !forgetPreview" class="forget-error" role="alert">{{ forgetError }}</p>

    <ForgetConfirmDialog
      v-if="forgetPreview"
      :preview="forgetPreview"
      :busy="forgetBusy"
      :error="forgetError"
      v-model:export-busy="exportBusy"
      @close="forgetPreview = null; forgetError = null"
      @confirm="confirmForget"
      @export="exportForgetLifecycle"
    />
    <InvalidPathDialog
      v-if="invalidPath"
      :path="invalidPath"
      :busy="exportBusy"
      @close="invalidPath = null"
      @clear="onInvalidClear"
      @export="onInvalidExport"
    />
    <!-- F2-B: remote directory browser — click selects, double-click
         descends (explorer mental model); dirs only, dotfiles hidden. -->
    <div v-if="browse" class="browse-overlay" @mousedown="browse = null">
      <div class="browse" role="dialog" aria-modal="true" :aria-label="t('picker.browse')" @mousedown.stop>
        <div class="browse-head">
          <span class="crumbs">
            <template v-for="c in browseCrumbs" :key="c.path">
              <button class="crumb" @click="loadBrowse(c.path)">{{ c.label }}</button>
            </template>
          </span>
          <input
            v-model="browseQuery"
            class="browse-search"
            type="search"
            :placeholder="t('picker.browseDialog.searchPlaceholder')"
          />
          <button
            class="ui-button quiet"
            :title="browseShowHidden ? t('picker.browseDialog.hideHidden') : t('picker.browseDialog.showHidden')"
            @click="toggleBrowseHidden"
          >{{ browseShowHidden ? "●" : "◌" }}</button>
          <button class="ui-button quiet" :disabled="browse.cwd === browse.root" @click="browseUp">↑</button>
        </div>
        <div class="browse-list">
          <p v-if="wsStore.browseBusy" class="hint">{{ t("picker.browseDialog.loading") }}</p>
          <p v-else-if="wsStore.browseError" class="forget-error" role="alert">{{ wsStore.browseError }}</p>
          <p v-else-if="!browse.entries.length" class="hint">{{ t("picker.browseDialog.empty") }}</p>
          <p v-else-if="!browseVisible.length" class="hint">{{ t("picker.browseDialog.noMatches") }}</p>
          <div
            v-for="e in browseVisible" :key="e.name"
            class="browse-item"
            :class="{ selected: browseSelected === e.name }"
            role="button" tabindex="0"
            @click="browseSelect(e.name)"
            @dblclick="browseInto(e.name)"
            @keyup.enter="browseInto(e.name)"
          >
            <span class="bi-arrow" aria-hidden="true">▸</span>
            <span class="bi-name">{{ e.name }}</span>
          </div>
        </div>
        <div class="browse-foot">
          <span class="browse-path">{{ browseChoice }}</span>
          <div class="browse-actions">
            <button class="ui-button" @click="browse = null">{{ t("picker.browseDialog.cancel") }}</button>
            <button class="ui-button primary" :disabled="!browseChoice" @click="chooseBrowse">{{ t("picker.browseDialog.choose") }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  color: var(--text-2);
}
.picker h2 { margin: 0; font-size: var(--font-xl); font-weight: 600; color: var(--text); }
.picker .row { display: flex; gap: var(--space-2); width: 560px; max-width: 90vw; }
.target-row { display: flex; align-items: center; gap: var(--space-2); font-size: var(--font-sm); }
.target-label { color: var(--text-muted); }
.target-select {
  background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-sm); padding: 0 var(--space-2);
}
.target-badge {
  color: var(--info); font-size: var(--font-xs);
  border: 1px solid currentColor; border-radius: var(--radius-sm); padding: 0 6px;
}
.picker .hint { font-size: var(--font-sm); color: var(--text-muted); margin: 0; }
/* 10d: recents reuse the .ui-section inset-grouped card; rows come from
 * .ui-section-row (padding/hover/dividers), so only content styles stay. */
.recents { width: 560px; max-width: 90vw; }
.recents ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; }
.recents li { width: 100%; }
.recents li:first-of-type .recent { border-top: none; }
.recent-wrap { display: flex; align-items: stretch; width: 100%; }
.recent {
  /* Grid with fixed name column: every row aligns regardless of name/path
   * length (user round-2 feedback — flex rows misaligned on long names). */
  flex: 1; min-width: 0; display: grid; grid-template-columns: minmax(0, 220px) minmax(0, 1fr) auto;
  align-items: center; gap: var(--space-2); text-align: left;
  background: transparent; color: var(--text-2);
  border: none; font-size: var(--font-sm); cursor: pointer;
  overflow: hidden; /* B-01: long folder names must truncate, not overflow */
}
.recent:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: calc(-1 * var(--focus-ring-offset)); }
.r-name {
  color: var(--text-2); font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.r-machine {
  color: var(--info); font-size: var(--font-xs); border: 1px solid currentColor;
  border-radius: var(--radius-sm); padding: 0 4px; flex: none;
}
.r-path {
  flex: 1; min-width: 0; /* flex ellipsis needs min-width: 0 */
  color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-xs);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kebab {
  flex: none; width: 28px; border: none; background: transparent; color: var(--text-muted);
  cursor: pointer; font-size: var(--font-md); border-radius: var(--radius-sm);
}
.kebab:hover, .kebab:focus-visible { background: var(--surface-hover); color: var(--text); }
.kebab:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: calc(-1 * var(--focus-ring-offset)); }
.expand {
  margin-top: var(--space-1); align-self: stretch; width: 100%;
  text-align: center; font-size: var(--font-sm);
}
.workspace {
  flex: 1; min-width: 0; background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-md); padding: var(--space-1) var(--space-3); font-size: var(--font-base);
}
/* --- context menu --- */
.ctx-overlay { position: fixed; inset: 0; z-index: 80; }
.ctx {
  position: fixed; z-index: 81;
  background: var(--surface); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  box-shadow: var(--shadow-menu); padding: var(--space-1); min-width: 160px;
}
.ctx-item {
  display: block; width: 100%; text-align: left; padding: var(--space-1) var(--space-2);
  background: transparent; border: none; border-radius: var(--radius-sm);
  font-size: var(--font-sm); cursor: pointer; color: var(--text-2);
}
.ctx-item:hover, .ctx-item:focus-visible { background: var(--surface-hover); color: var(--text); }
.ctx-item.danger { color: var(--error-fg); }
.ctx-item:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: calc(-1 * var(--focus-ring-offset)); }
.forget-error { color: var(--error-fg); font-size: var(--font-sm); margin: 0; max-width: 560px; }

/* --- F2-B: remote browse popover (field-redesign: dirs-only rows with a
       chevron, clear selection state, explorer interactions) --- */
.browse-overlay {
  position: fixed; inset: 0; z-index: 90; background: var(--scrim, rgba(0, 0, 0, 0.4));
  display: flex; align-items: center; justify-content: center;
}
.browse {
  width: 640px; max-width: 92vw;
  /* Field r2 #1: a FIXED body height — the listing scrolls inside; without
     it the flex child's min-height:auto grows past the dialog (hidden-dir
     listings overflowed the screen). */
  height: min(600px, 72vh);
  display: flex; flex-direction: column;
  background: var(--surface); border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md); box-shadow: var(--shadow-menu);
}
.browse-head {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border);
}
.crumbs { display: flex; flex-wrap: wrap; gap: 2px; flex: 1; min-width: 0; }
.browse-search {
  flex: none; width: 140px; padding: 3px var(--space-2);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
.browse-search:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: calc(-1 * var(--focus-ring-offset)); }
.crumb {
  background: none; border: none; cursor: pointer; padding: 2px 4px;
  color: var(--accent); font-family: var(--font-mono); font-size: var(--font-sm);
  border-radius: var(--radius-sm);
}
.crumb:hover { background: var(--surface-hover); }
.browse-list { flex: 1; min-height: 0; overflow-y: auto; padding: var(--space-2); }
.browse-item {
  display: flex; align-items: center; gap: var(--space-2); width: 100%;
  text-align: left; padding: 7px var(--space-2);
  border: none; border-radius: var(--radius-sm);
  background: none; color: var(--text); font-size: var(--font-md, var(--font-sm));
  cursor: pointer; user-select: none;
}
.browse-item:hover, .browse-item:focus-visible { background: var(--surface-hover); }
.browse-item.selected {
  background: var(--accent-soft);
  outline: 1px solid var(--accent);
}
.bi-arrow { flex: none; color: var(--accent); font-size: var(--font-sm); }
.bi-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.browse-foot {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-top: 1px solid var(--border);
}
.browse-path {
  font-family: var(--font-mono); font-size: var(--font-sm); color: var(--text-2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;
}
.browse-actions { display: flex; gap: var(--space-2); flex: none; }
</style>
