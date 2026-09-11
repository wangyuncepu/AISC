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
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useWorkspacesStore, MAX_WORKSPACES } from "../../stores/workspaces";
import { useRuntimeStore } from "../../stores/runtime";
import { useSettingsStore } from "../../stores/settings";

const { t } = useI18n();
const ws = useWorkspacesStore();
const settingsStore = useSettingsStore();

// --- + split button (3f round 2, user request): main + opens the launcher
// W1 (shell-redesign): the ▾ menu is RETIRED (settings/dashboard are
// rail-bottom floating panes now) — only the + launcher button remains.





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

// P2-2 (D-2): the GLOBAL status label relocated here from the retired topbar
// row — the ACTIVE instance's state via the facade (NOT the chips' own
// per-workspace snapshot), KI-1 docker wake-up included. Renders at the
// strip's right end (.bar-status).
const facade = useRuntimeStore();
const activeStatusRaw = computed(() => facade.status);
const activeStatusLabel = computed(() =>
  facade.dockerStarting
    ? t("app.dockerStartingStatus")
    : t(STATUS_KEY[facade.status] ?? "app.unknown")
);

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
  // W1 (shell-redesign): Settings / 数据看板 chips are RETIRED — both ride
  // the rail-bottom icons as FLOATING panes now (the store flags stay; they
  // drive the overlay, not a chip).
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
        v-if="!c.launcher"
        class="close"
        :title="t('workspbar.close')"
        :aria-label="`${t('workspbar.close')}: ${c.title}`"
        @click.stop="ws.closeWorkspace(c.id)"
      >
        ×
      </button>
    </div>

    <!-- W1: the + button (launcher / configured default page) — the ▾ half
         of the old split button retired with the menu. -->
    <div class="add-group">
      <button
        ref="addBtnRef"
        class="add"
        :aria-label="t('workspbar.launcher')"
        :title="plusDisabled ? t('workspbar.capHint') : t('workspbar.launcher')"
        :disabled="plusDisabled"
        @click="openDefaultPage()"
      >+</button>
    </div>

    <!-- P2-2 (D-2): global status, relocated from the retired topbar row —
         pinned to the strip's right end (sticky, so chip overflow scrolls
         under it instead of pushing it out of view). -->
    <span
      class="bar-status"
      :data-status="activeStatusRaw"
      :title="activeStatusLabel"
    >{{ activeStatusLabel }}</span>
  </nav>
</template>

<style scoped>
/* P2-2 (D-2): the global status label — same quiet-text language the old
 * topbar used (10c round 2), now at the strip's right end. Sticky against
 * chip overflow; hidden on compact tiers (unscoped rule in App.vue). */
.bar-status {
  margin-left: auto;
  position: sticky;
  right: 0;
  padding: 2px 8px;
  background: var(--surface);
  font-size: var(--font-sm);
  color: var(--text-muted);
  white-space: nowrap;
  flex: none;
}
.bar-status[data-status="ready"] { color: var(--success); }
.bar-status[data-status="error"],
.bar-status[data-status="blocked"] { color: var(--error); }

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
