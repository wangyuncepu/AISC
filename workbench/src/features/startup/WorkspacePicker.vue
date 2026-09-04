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
import type { ForgetPreview, SshProfile } from "../../types";
import ForgetConfirmDialog from "./ForgetConfirmDialog.vue";
import InvalidPathDialog from "./InvalidPathDialog.vue";

const { t } = useI18n();
const store = useRuntimeStore();
const wsStore = useWorkspacesStore();

// --- F1 (D-10): SSH-workspace entry (collapsed form) ---
const settings = useSettingsStore();
const sshOpen = ref(false);
const sshForm = ref({ profile: 0, remotePath: "", name: "" });
const sshBusy = ref(false);
const sshError = computed(() => wsStore.createSshError);
const profiles = computed<SshProfile[]>(() => settings.doc?.sshProfiles ?? []);
void settings.load();

async function onCreateSsh(): Promise<void> {
  if (sshBusy.value) return;
  const p = profiles.value[sshForm.value.profile];
  if (!p || !sshForm.value.remotePath.trim() || !sshForm.value.name.trim()) return;
  sshBusy.value = true;
  try {
    const workspacePath = await wsStore.createSshWorkspace(
      sshForm.value.name.trim(), p, sshForm.value.remotePath.trim());
    if (workspacePath) {
      // Open the shadow dir as a NORMAL workspace — the identity chain is
      // untouched; the sync layer (T-F1c) attaches via the metadata file.
      store.workspace = workspacePath;
      sshOpen.value = false;
      sshForm.value = { profile: 0, remotePath: "", name: "" };
      await store.runPreflight();
    }
  } finally {
    sshBusy.value = false;
  }
}

// --- T-F1e: remote path browse dialog (click-to-pick instead of typing) ---
const browse = ref<{ open: boolean; path: string; entries: { name: string; isDir: boolean }[] } | null>(null);

function openBrowse(): void {
  const p = profiles.value[sshForm.value.profile];
  if (!p) return;
  const start = sshForm.value.remotePath.trim() || "/";
  browse.value = { open: true, path: start, entries: [] };
  void loadBrowse(start);
}

async function loadBrowse(path: string): Promise<void> {
  const p = profiles.value[sshForm.value.profile];
  if (!p || !browse.value) return;
  browse.value.entries = await wsStore.browseRemote(p, path);
  browse.value.path = path;
}

function browseInto(name: string): void {
  if (!browse.value) return;
  const next = (browse.value.path.replace(/\/+$/, "") + "/" + name).replace(/\/{2,}/g, "/");
  void loadBrowse(next);
}

function browseUp(): void {
  if (!browse.value) return;
  const parts = browse.value.path.replace(/\/+$/, "").split("/").filter(Boolean);
  parts.pop();
  void loadBrowse("/" + parts.join("/"));
}

function chooseBrowse(): void {
  if (browse.value) sshForm.value.remotePath = browse.value.path;
  browse.value = null;
}

function browseCrumb(index: number): void {
  if (!browse.value) return;
  const parts = browse.value.path.replace(/\/+$/, "").split("/").filter(Boolean);
  void loadBrowse("/" + parts.slice(0, index + 1).join("/"));
}
const browseCrumbs = computed(() =>
  (browse.value?.path ?? "/").replace(/\/+$/, "").split("/").filter(Boolean));

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
const invalidPath = ref<string | null>(null);
async function onRecentClick(path: string): Promise<void> {
  const exists = await wsStore.workspacePathExists(path);
  if (!exists) {
    invalidPath.value = path;
    return;
  }
  store.selectRecentWorkspace(path);
}
async function clearInvalidEntry(): Promise<void> {
  const path = invalidPath.value;
  invalidPath.value = null;
  if (!path) return;
  try {
    await wsStore.clearHistoryEntry(path);
  } catch {
    /* record-only clear is best-effort for the user; history reloads next open */
  }
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
      <button class="ui-button" @click="store.pickWorkspace()">{{ t("picker.browse") }}</button>
      <button class="ui-button primary" :disabled="!store.workspace.trim()" @click="store.runPreflight()">{{ t("picker.next") }}</button>
    </div>
    <p class="hint">{{ t("picker.hint") }}</p>

    <!-- F1 (D-10): SSH workspace entry — shadow dir under the data root,
         opened as a normal workspace; the sync layer attaches later. -->
    <div class="ssh ui-section">
      <button class="ssh-toggle ui-section-title" @click="sshOpen = !sshOpen">
        {{ sshOpen ? "▾" : "▸" }} {{ t("picker.ssh.title") }}
      </button>
      <div v-if="sshOpen" class="ssh-form">
        <p v-if="!profiles.length" class="ssh-hint">{{ t("picker.ssh.noProfiles") }}</p>
        <template v-else>
          <label class="ssh-field">
            <span>{{ t("picker.ssh.profile") }}</span>
            <select v-model.number="sshForm.profile">
              <option v-for="(p, i) in profiles" :key="p.name" :value="i">
                {{ p.name }} ({{ p.user }}@{{ p.host }}:{{ p.port }})
              </option>
            </select>
          </label>
          <label class="ssh-field">
            <span>{{ t("picker.ssh.remotePath") }}</span>
            <input v-model.trim="sshForm.remotePath" placeholder="/home/user/project" @keyup.enter="onCreateSsh" />
            <button class="ui-button" :title="t('picker.ssh.browse')" @click="openBrowse">…</button>
          </label>
          <label class="ssh-field">
            <span>{{ t("picker.ssh.name") }}</span>
            <input v-model.trim="sshForm.name" :placeholder="t('picker.ssh.namePh')" @keyup.enter="onCreateSsh" />
          </label>
          <div class="ssh-actions">
            <button class="ui-button primary" :disabled="sshBusy || !sshForm.remotePath || !sshForm.name" @click="onCreateSsh">
              {{ sshBusy ? t("picker.ssh.creating") : t("picker.ssh.create") }}
            </button>
          </div>
          <p class="ssh-hint">{{ t("picker.ssh.hint") }}</p>
        </template>
        <p v-if="sshError" class="forget-error" role="alert">{{ sshError }}</p>
      </div>
    </div>

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

    <!-- T-F1e: remote path browse dialog -->
    <div v-if="browse" class="browse-overlay" @mousedown="browse = null">
      <div class="browse" role="dialog" aria-modal="true" :aria-label="t('picker.ssh.browse')" @mousedown.stop>
        <div class="browse-head">
          <span class="crumbs">
            <button class="crumb" @click="loadBrowse('/')">/</button>
            <template v-for="(c, i) in browseCrumbs" :key="i">
              <button class="crumb" @click="browseCrumb(i)">{{ c }}</button>
            </template>
          </span>
          <button class="ui-button quiet" :disabled="browse.path === '/'" @click="browseUp">↑</button>
        </div>
        <div class="browse-list">
          <p v-if="wsStore.browseBusy" class="ssh-hint">{{ t("picker.ssh.loading") }}</p>
          <p v-else-if="wsStore.browseError" class="forget-error" role="alert">{{ wsStore.browseError }}</p>
          <p v-else-if="!browse.entries.length" class="ssh-hint">{{ t("picker.ssh.emptyDir") }}</p>
          <button
            v-for="e in browse.entries" :key="e.name"
            class="browse-item" :class="{ dir: e.isDir }"
            @click="e.isDir && browseInto(e.name)"
          >
            <span class="bi-icon">{{ e.isDir ? "📁" : "📄" }}</span>{{ e.name }}
          </button>
        </div>
        <div class="browse-foot">
          <span class="ssh-hint">{{ browse.path }}</span>
          <div class="browse-actions">
            <button class="ui-button" @click="browse = null">{{ t("picker.ssh.cancel") }}</button>
            <button class="ui-button primary" @click="chooseBrowse">{{ t("picker.ssh.choose") }}</button>
          </div>
        </div>
      </div>
    </div>

    <ForgetConfirmDialog
      v-if="forgetPreview"
      :preview="forgetPreview"
      :busy="forgetBusy"
      :error="forgetError"
      @close="forgetPreview = null; forgetError = null"
      @confirm="confirmForget"
    />
    <InvalidPathDialog
      v-if="invalidPath"
      :path="invalidPath"
      @close="invalidPath = null"
      @clear="clearInvalidEntry"
    />
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
/* F1: SSH workspace form */
.ssh { width: 560px; max-width: 90vw; }
.ssh-toggle {
  background: none; border: none; cursor: pointer; text-align: left;
  font-size: var(--font-sm); color: var(--text-muted); width: 100%; padding: 0;
}
.ssh-form { display: flex; flex-direction: column; gap: var(--space-2); padding-top: var(--space-2); }
.ssh-field { display: flex; align-items: center; gap: var(--space-2); font-size: var(--font-sm); }
.ssh-field > span { width: 90px; color: var(--text-muted); flex: none; }
.ssh-field input, .ssh-field select {
  flex: 1; background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-sm); padding: 0 var(--space-2);
}
.ssh-actions { display: flex; justify-content: flex-end; }
.ssh-hint { font-size: var(--font-xs); color: var(--text-faint); margin: 0; }
/* T-F1e: remote browse dialog */
.browse-overlay {
  position: fixed; inset: 0; z-index: 90; background: var(--scrim, rgba(0,0,0,.4));
  display: flex; align-items: center; justify-content: center;
}
.browse {
  width: 520px; max-width: 92vw; max-height: 70vh;
  display: flex; flex-direction: column;
  background: var(--surface); border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md); box-shadow: var(--shadow-menu);
}
.browse-head {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border);
}
.crumbs { display: flex; flex-wrap: wrap; gap: 2px; flex: 1; min-width: 0; }
.crumb {
  background: none; border: none; cursor: pointer; padding: 2px 4px;
  color: var(--accent); font-family: var(--font-mono); font-size: var(--font-sm);
  border-radius: var(--radius-sm);
}
.crumb:hover { background: var(--surface-hover); }
.browse-list { flex: 1; overflow-y: auto; padding: var(--space-2); min-height: 160px; }
.browse-item {
  display: flex; align-items: center; gap: var(--space-2); width: 100%;
  text-align: left; padding: 5px var(--space-2); border: none; cursor: default;
  background: none; color: var(--text-2); font-size: var(--font-sm);
  border-radius: var(--radius-sm);
}
.browse-item.dir { cursor: pointer; color: var(--text); }
.browse-item.dir:hover, .browse-item.dir:focus-visible { background: var(--surface-hover); }
.bi-icon { flex: none; }
.browse-foot {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-top: 1px solid var(--border);
}
.browse-foot .ssh-hint { font-family: var(--font-mono); }
.browse-actions { display: flex; gap: var(--space-2); }
</style>
