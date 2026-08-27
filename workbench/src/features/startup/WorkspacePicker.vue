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
import type { ForgetPreview } from "../../types";
import ForgetConfirmDialog from "./ForgetConfirmDialog.vue";
import InvalidPathDialog from "./InvalidPathDialog.vue";

const { t } = useI18n();
const store = useRuntimeStore();
const wsStore = useWorkspacesStore();

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
const menuX = ref(0);
const menuY = ref(0);
/** Live .app zoom (font_scale): the menu is position:fixed INSIDE the
 * zoomed .app, which re-scales fixed offsets — viewport pixels must be
 * divided by the zoom (Stage 11 two-space model, re-hit 2026-08-27). */
function appZoom(): number {
  const el = document.querySelector(".app");
  const z = el ? parseFloat(getComputedStyle(el).zoom || "1") : 1;
  return Number.isFinite(z) && z > 0 ? z : 1;
}
function openMenu(path: string, vx: number, vy: number): void {
  const z = appZoom();
  menuFor.value = path;
  menuX.value = Math.round(vx / z);
  menuY.value = Math.round(vy / z);
}
/** Kebab path: anchor the menu to the button (below, right-aligned) instead
 * of screen coordinates (2026-08-27 manual test: the 50%/50% fallback read
 * as a random position). */
function openMenuAtButton(path: string, e: MouseEvent): void {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  openMenu(path, Math.max(8, r.right - 170), r.bottom + 4);
}
function closeMenu(): void {
  menuFor.value = null;
}

const forgetPreview = ref<ForgetPreview | null>(null);
const forgetBusy = ref(false);
const forgetError = ref<string | null>(null);
async function startForget(path: string): Promise<void> {
  closeMenu();
  forgetError.value = null;
  try {
    forgetPreview.value = await wsStore.forgetPreview(path);
  } catch (e) {
    forgetError.value = String(e);
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
    forgetError.value = String(e);
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
              <span class="r-agent">{{ w.last_agent || "-" }}</span>
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
      :style="menuX ? { left: `${menuX}px`, top: `${menuY}px` } : undefined"
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
.r-agent { color: var(--info); font-size: var(--font-xs); }
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
</style>
