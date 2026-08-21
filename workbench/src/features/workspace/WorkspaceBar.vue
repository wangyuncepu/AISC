<script setup lang="ts">
/**
 * IDEA-3 (3c): the workspace-level tab strip — the top of the two-strip
 * layout (this bar + the session TabBar of the active workspace). Chips:
 * ready workspaces (basename + status dot, × to close via closeWorkspace) and
 * the single-flight "new workspace" launcher chip (openLauncher; disabled at
 * MAX_WORKSPACES). The Settings chip lands here in 3d.
 *
 * Reads the workspaces store directly (NOT the facade — the strip must show
 * every workspace, not just the active one). Full APG roving-focus polish is
 * 3e; this ships the correct roles/labels.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useWorkspacesStore, MAX_WORKSPACES } from "../../stores/workspaces";
import { useSettingsStore } from "../../stores/settings";
import { SETTINGS_TAB_ID, NETWORK_USAGE_TAB_ID } from "../../stores/runtime";

const { t } = useI18n();
const ws = useWorkspacesStore();
const settingsStore = useSettingsStore();

// --- + split button (3f round 2, user request): main + opens the launcher
// (default new workspace), ▾ opens a menu with the workspace-layer entries
// (Settings). Same teleport + zoom-compensation pattern as TabBar's ▾: the
// strip is an overflow-x scroll container, and the chrome is CSS-zoomed. ---
const menuOpen = ref(false);
const menuRef = ref<HTMLUListElement | null>(null);
const addBtnRef = ref<HTMLButtonElement | null>(null);
const caretBtnRef = ref<HTMLButtonElement | null>(null);
const menuPos = ref({ x: 0, y: 0 });

function placeMenu(): boolean {
  const btn = caretBtnRef.value ?? addBtnRef.value;
  if (!btn) return false;
  const rect = btn.getBoundingClientRect();
  // 10d: a detached / not-yet-laid-out ref reports an all-zero rect, and the
  // clamped minimum then parked the menu at the window's top-left corner
  // (user evidence 2.png). Refuse to open instead.
  if (rect.width === 0 && rect.height === 0) return false;
  // The teleported menu lives OUTSIDE the zoomed .app, so its fixed px are
  // viewport (VISUAL) px. r4: .app is sized width:100vw/scale, so the live
  // scale is innerWidth / app.offsetWidth regardless of engine. A visual-space
  // rect (modern engines: ratio == scale) is already correct; a layout-space
  // rect (legacy: ratio == 1) must be MULTIPLIED by the scale. Never divided —
  // dividing made the offset grow with the caret's distance from the left
  // edge (user evidence: more tabs → bigger drift at font_scale 1.5).
  const app = document.querySelector<HTMLElement>(".app");
  const scale = app && app.offsetWidth > 0 ? window.innerWidth / app.offsetWidth : 1;
  const ratio = btn.offsetWidth > 0 ? rect.width / btn.offsetWidth : 1;
  const z = Math.abs(scale - 1) < 0.02 ? 1 : (Math.abs(ratio - scale) < 0.05 ? 1 : scale);
  const menuWidth = 180;
  menuPos.value = {
    x: Math.max(4, Math.min(rect.left * z, window.innerWidth - menuWidth)),
    y: rect.bottom * z + 2,
  };
  return true;
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
  if (menuOpen.value) {
    // Place after the menu mounts AND after the next paint: opening the
    // menu right after closing a tab catches the +/▾ mid-FLIP, and transforms
    // DO land in getBoundingClientRect — the menu then anchored at the
    // transient position (occasional repro, user evidence 1.png). Double
    // rAF measures the settled layout.
    void nextTick(() => {
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (!placeMenu()) {
            menuOpen.value = false;
            return;
          }
          menuRef.value?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
        }),
      );
    });
  }
}

function closeMenu() {
  menuOpen.value = false;
}

function onMenuKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" || e.key === "Tab") {
    e.preventDefault();
    closeMenu();
    caretBtnRef.value?.focus();
    return;
  }
  const items = Array.from(menuRef.value?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
  if (items.length === 0) return;
  const idx = items.findIndex((el) => el === document.activeElement);
  if (e.key === "ArrowDown") {
    e.preventDefault();
    items[(idx + 1 + items.length) % items.length]!.focus();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    items[(idx - 1 + items.length) % items.length]!.focus();
  } else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    (items[idx >= 0 ? idx : 0] as HTMLElement).click();
  }
}

function onDocMousedown(e: MouseEvent) {
  const target = e.target as HTMLElement;
  if (menuOpen.value && !target.closest(".wsp-menu") && !target.closest(".add-group")) {
    closeMenu();
  }
}

onMounted(() => document.addEventListener("mousedown", onDocMousedown));
onBeforeUnmount(() => document.removeEventListener("mousedown", onDocMousedown));

function menuOpenSettings() {
  closeMenu();
  ws.openSettingsTab();
}

function menuOpenNetworkUsage() {
  closeMenu();
  ws.openNetworkUsageTab();
}

interface Chip {
  id: string;
  label: string;
  title: string;
  status: string;
  state: string;
  launcher: boolean;
  settings?: boolean;
  networkUsage?: boolean;
}

/** Folder name of a workspace path (both separators — Windows paths are
 * backslashed; a "/"-only split returned the whole path as the "name"). */
function basename(p: string): string {
  const parts = p.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

/** Round-4 rule (user): chips show the FOLDER NAME; only when two open
 * workspaces share a folder name do those chips show the full path so the
 * user can tell them apart. */
function chipLabel(path: string, all: string[]): string {
  const name = basename(path);
  return all.filter((p) => basename(p) === name).length > 1 ? path : name;
}

const STATUS_KEY: Record<string, string> = {
  picker: "app.status.picker",
  preflight: "app.preflight",
  summary: "app.status.summary",
  starting: "app.starting",
  cancelled: "app.status.cancelled",
  building: "app.status.building",
  conflict: "app.status.conflict",
  ready: "app.status.ready",
  stopping: "app.stopping",
  error: "app.error.title",
};

/** The dot shows the LIVE runtime state when the workspace is ready (external
 * docker stop becomes visible via the downshifted background poll), else the
 * launch-flow status (starting/building/...) — the strip is the progress
 * surface for background workspaces. */
function dotState(c: Chip): string {
  if (c.status === "ready") return c.state || "unknown";
  return c.status;
}

const chips = computed<Chip[]>(() => {
  const paths = ws.runtimes.map((r) => r.workspace.value);
  const list: Chip[] = ws.runtimes.map((r) => ({
    id: r.id,
    label: chipLabel(r.workspace.value, paths),
    title: r.workspace.value,
    status: r.status.value,
    state: r.runtimeState.value,
    launcher: false,
  }));
  // Round-3 model (user spec): the strip shows only REAL open pages — the
  // launcher chip exists while it is the FOCUSED page (initial state, or
  // re-opened via +), and disappears once a workspace materializes.
  if (ws.activeId === ws.launcher.id) {
    const lg = ws.launcher;
    list.push({
      id: lg.id,
      label: t("workspbar.launcher"),
      title: t("workspbar.launcher"),
      status: lg.status.value,
      state: lg.runtimeState.value,
      launcher: true,
    });
  }
  // Settings is a page opened via ▾ / Ctrl+, — its chip (and ×) exist only
  // while it is open.
  if (ws.settingsTabOpen) {
    list.push({
      id: SETTINGS_TAB_ID,
      label: t("workspbar.settings"),
      title: t("workspbar.settings"),
      status: "settings",
      state: "",
      launcher: false,
      settings: true,
    });
  }
  // IDEA-2 (2d): the「网络与用量」panel rides after Settings — same
  // only-while-open chip model.
  if (ws.networkUsageTabOpen) {
    list.push({
      id: NETWORK_USAGE_TAB_ID,
      label: t("workspbar.networkUsage"),
      title: t("workspbar.networkUsage"),
      status: "settings",
      state: "",
      launcher: false,
      networkUsage: true,
    });
  }
  return list;
});

/** The + button's default target (round 3): the configured page; the cap
 * only disables a workspace-target +. */
const defaultPage = computed(
  () => settingsStore.doc?.ui.default_new_page ?? "workspace"
);
function openDefaultPage(): void {
  if (defaultPage.value === "settings") {
    ws.openSettingsTab();
    return;
  }
  ws.openLauncher();
}
const plusDisabled = computed(() => defaultPage.value === "workspace" && atCap.value);

const atCap = computed(() => ws.runtimes.length >= MAX_WORKSPACES);

function chipTitle(c: Chip): string {
  if (c.settings) return `${c.label} · ${t("tabbar.closeSettings")}`;
  if (c.networkUsage) return `${c.label} · ${t("tabbar.closeNetworkUsage")}`;
  const statusText = t(STATUS_KEY[c.status] ?? "app.unknown");
  const parts = c.launcher ? [c.label] : [c.title, statusText];
  if (!c.launcher) parts.push(t("workspbar.close"));
  return parts.join(" · ");
}

function onChip(c: Chip): void {
  if (c.settings) {
    ws.openSettingsTab();
    return;
  }
  if (c.networkUsage) {
    ws.openNetworkUsageTab();
    return;
  }
  if (c.launcher) {
    // The launcher chip only renders while already focused; clicking it just
    // re-asserts focus (the cap gate lives on the + button).
    ws.openLauncher();
    return;
  }
  ws.activate(c.id);
}

/** The Settings chip × reverts unsaved form edits via the settings store
 * (same contract the session-layer chip had), then closes the sentinel. */
function closeSettingsChip(): void {
  settingsStore.cancel();
  ws.closeSettingsTab();
}

/** The「网络与用量」chip × — no dirty-form contract, just close. */
function closeNetworkUsageChip(): void {
  ws.closeNetworkUsageTab();
}

// --- APG tabs pattern (3e): roving tabindex. Arrows/Home/End move FOCUS
// without activating; Enter/Space activates (the chip's own handlers).
const chipEls = ref<(HTMLElement | null)[]>([]);
function setChipRef(i: number) {
  return (el: unknown) => {
    chipEls.value[i] = (el as HTMLElement | null) ?? null;
  };
}
function chipTabIndex(i: number): string {
  const activeI = chips.value.findIndex((c) => c.id === ws.activeId);
  return i === (activeI >= 0 ? activeI : 0) ? "0" : "-1";
}
function onBarKeydown(e: KeyboardEvent) {
  const n = chips.value.length;
  if (n === 0) return;
  let next: number;
  const activeI = Math.max(0, chips.value.findIndex((c) => c.id === ws.activeId));
  if (e.key === "ArrowLeft") next = (activeI - 1 + n) % n;
  else if (e.key === "ArrowRight") next = (activeI + 1) % n;
  else if (e.key === "Home") next = 0;
  else if (e.key === "End") next = n - 1;
  else return;
  e.preventDefault();
  chipEls.value[next]?.focus();
}
</script>

<template>
  <nav class="workspbar" role="tablist" :aria-label="t('workspbar.label')" @keydown="onBarKeydown">
    <div
      v-for="(c, i) in chips"
      :key="c.id"
      :ref="setChipRef(i)"
      class="chip"
      :class="{ active: ws.activeId === c.id, launcher: c.launcher }"
      role="tab"
      :aria-selected="ws.activeId === c.id"
      :aria-label="chipTitle(c)"
      :title="chipTitle(c)"
      :data-dot="dotState(c)"
      :tabindex="chipTabIndex(i)"
      @click="onChip(c)"
      @keydown.enter.prevent="onChip(c)"
      @keydown.space.prevent="onChip(c)"
    >
      <!-- 10c: the runtime-state dot only exists for real workspace chips —
           settings/network-usage/launcher pages have no container behind
           them, so a permanently-grey dot is noise (user feedback d.png). -->
      <span
        v-if="!c.launcher && !c.settings && !c.networkUsage"
        class="dot"
        :data-state="dotState(c)"
      />
      <span class="name">{{ c.label }}</span>
      <button
        v-if="c.settings && ws.settingsTabOpen"
        class="close"
        :title="t('tabbar.closeSettings')"
        :aria-label="t('tabbar.closeSettings')"
        @click.stop="closeSettingsChip()"
      >
        ×
      </button>
      <button
        v-else-if="c.networkUsage && ws.networkUsageTabOpen"
        class="close"
        :title="t('tabbar.closeNetworkUsage')"
        :aria-label="t('tabbar.closeNetworkUsage')"
        @click.stop="closeNetworkUsageChip()"
      >
        ×
      </button>
      <button
        v-else-if="!c.launcher && !c.settings"
        class="close"
        :title="t('workspbar.close')"
        :aria-label="`${t('workspbar.close')}: ${c.title}`"
        @click.stop="ws.closeWorkspace(c.id)"
      >
        ×
      </button>
    </div>

    <!-- + split button: + = launcher (default new workspace), ▾ = Settings. -->
    <div class="add-group wsp-menu">
      <button
        ref="addBtnRef"
        class="add"
        :aria-label="t('workspbar.launcher')"
        :title="plusDisabled ? t('workspbar.capHint') : t('workspbar.launcher')"
        :disabled="plusDisabled"
        @click="openDefaultPage()"
      >+</button>
      <button
        ref="caretBtnRef"
        class="add-caret"
        :aria-label="t('workspbar.choose')"
        :title="t('workspbar.choose')"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
        @keydown="onMenuKeydown"
      >▾</button>
      <Teleport to="body">
        <Transition name="pop">
        <ul
          v-if="menuOpen"
          ref="menuRef"
          class="menu wsp-menu tab-new-menu"
          role="menu"
          :style="{ left: `${menuPos.x}px`, top: `${menuPos.y}px` }"
          @keydown="onMenuKeydown"
        >
          <li
            role="menuitem"
            tabindex="0"
            @click="menuOpenSettings"
          >{{ t("workspbar.settings") }}</li>
          <li
            role="menuitem"
            tabindex="0"
            @click="menuOpenNetworkUsage"
          >{{ t("workspbar.networkUsage") }}</li>
        </ul>
        </Transition>
      </Teleport>
    </div>
  </nav>
</template>

<style scoped>
.workspbar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 8px;
  background: var(--surface);
  border-bottom: var(--border-w) solid var(--border);
  overflow-x: auto;
}
/* 10c: chips follow the TabBar pill language (D10-14), one tier thinner. */
.chip {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: var(--control-h-sm);
  padding: 0 6px 0 10px;
  border-radius: var(--radius-sm);
  border: var(--border-w) solid transparent;
  color: var(--text-muted);
  font-size: var(--font-sm);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  /* 10e r7: active hand-off snaps (no 200ms dual-highlight smear — see TabBar). */
  transition: opacity var(--duration-normal) var(--ease);
}
.chip:hover { background: var(--surface-hover); color: var(--text-2); }
.chip.active {
  background: var(--accent-soft);
  color: var(--text);
}
.chip.launcher { border-style: dashed; }
.chip .name {
  max-width: 22ch; /* B-02: long workspace names must not eat the strip */
  overflow: hidden;
  text-overflow: ellipsis;
}
.dot { width: 8px; height: 8px; border-radius: var(--radius-full); background: var(--text-faint); flex: none; }
.dot[data-state="running"] { background: var(--success); }
.dot[data-state="starting"], .dot[data-state="building"] { background: var(--info); }
.dot[data-state="stopped"], .dot[data-state="not_found"] { background: var(--text-faint); }
.dot[data-state="error"], .dot[data-state="conflict"], .dot[data-state="cancelled"] { background: var(--error); }
.close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  min-height: 20px;
  padding: 0 3px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--font-md);
  line-height: 1;
  cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.close:hover { color: var(--error-fg); background: var(--surface-hover); }

/* + split button (mirrors TabBar's, one tier thinner). */
.add-group { display: flex; align-items: center; margin-left: 4px; }
.add, .add-caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--font-md);
  line-height: 1;
  padding: 3px 6px;
  cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.add:hover:not(:disabled), .add-caret:hover { color: var(--text-2); background: var(--surface-hover); }
.add:disabled { opacity: 0.45; cursor: default; }
.menu {
  position: fixed;
  z-index: var(--z-menu);
  min-width: 180px;
  margin: 0;
  padding: 4px;
  list-style: none;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
}
.menu li {
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--font-md);
  color: var(--text-2);
  cursor: pointer;
}
.menu li:hover, .menu li:focus { background: var(--surface-hover); outline: none; }
</style>
