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
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useWorkspacesStore, MAX_WORKSPACES } from "../../stores/workspaces";
import { useSettingsStore } from "../../stores/settings";
import { SETTINGS_TAB_ID } from "../../stores/runtime";

const { t } = useI18n();
const ws = useWorkspacesStore();
const settingsStore = useSettingsStore();

interface Chip {
  id: string;
  label: string;
  title: string;
  status: string;
  state: string;
  launcher: boolean;
  settings?: boolean;
}

function basename(p: string): string {
  const parts = p.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || p;
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
  const list: Chip[] = ws.runtimes.map((r) => ({
    id: r.id,
    label: basename(r.workspace.value),
    title: r.workspace.value,
    status: r.status.value,
    state: r.runtimeState.value,
    launcher: false,
  }));
  const lg = ws.launcher;
  list.push({
    id: lg.id,
    label: t("workspbar.launcher"),
    title: t("workspbar.launcher"),
    status: lg.status.value,
    state: lg.runtimeState.value,
    launcher: true,
  });
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
  return list;
});

const atCap = computed(() => ws.runtimes.length >= MAX_WORKSPACES);
/** The launcher chip refuses new launches at the cap, but still works as a
 * focus target while one is already mid-flight or active. */
const launcherDisabled = computed(
  () => atCap.value && ws.activeId !== ws.launcher.id
);

function chipTitle(c: Chip): string {
  if (c.settings) return `${c.label} · ${t("tabbar.closeSettings")}`;
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
  if (c.launcher) {
    if (!launcherDisabled.value) ws.openLauncher();
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
</script>

<template>
  <nav class="workspbar" role="tablist" :aria-label="t('workspbar.label')">
    <div
      v-for="c in chips"
      :key="c.id"
      class="chip"
      :class="{ active: ws.activeId === c.id, launcher: c.launcher }"
      role="tab"
      :aria-selected="ws.activeId === c.id"
      :aria-label="chipTitle(c)"
      :title="chipTitle(c)"
      :data-dot="dotState(c)"
      tabindex="0"
      @click="onChip(c)"
      @keydown.enter.prevent="onChip(c)"
      @keydown.space.prevent="onChip(c)"
    >
      <span class="dot" :data-state="dotState(c)" />
      <span class="name">{{ c.label }}</span>
      <button
        v-if="c.settings"
        class="close"
        :title="t('tabbar.closeSettings')"
        :aria-label="t('tabbar.closeSettings')"
        @click.stop="closeSettingsChip()"
      >
        ×
      </button>
      <button
        v-else-if="!c.launcher"
        class="close"
        :title="t('workspbar.close')"
        :aria-label="`${t('workspbar.close')}: ${c.title}`"
        @click.stop="ws.closeWorkspace(c.id)"
      >
        ×
      </button>
    </div>
  </nav>
</template>

<style scoped>
.workspbar {
  display: flex;
  align-items: stretch;
  gap: 2px;
  padding: 2px 8px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}
.chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  border: 1px solid transparent;
  border-bottom: none;
  color: var(--text-muted);
  font-size: var(--font-sm);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.chip:hover { background: var(--surface-2); color: var(--text-2); }
.chip.active {
  background: var(--surface-2);
  border-color: var(--border-strong);
  color: var(--text-1);
}
.chip.launcher { border-style: dashed; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); flex: none; }
.dot[data-state="running"] { background: var(--success); }
.dot[data-state="starting"], .dot[data-state="building"] { background: var(--info); }
.dot[data-state="stopped"], .dot[data-state="not_found"] { background: var(--text-faint); }
.dot[data-state="error"], .dot[data-state="conflict"], .dot[data-state="cancelled"] { background: var(--error); }
.close {
  padding: 0 3px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: var(--font-md);
  line-height: 1;
  cursor: pointer;
}
.close:hover { color: var(--error-fg); }
</style>
