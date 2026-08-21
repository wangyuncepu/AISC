<script setup lang="ts">
/**
 * IDEA-3 (3c): the workspace picker, extracted from App.vue's inline block.
 * Renders inside the launcher's WorkspaceView — typed path / browse / recents
 * from the shared history. Facade-bound (only the ACTIVE view mounts).
 */
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();

function basename(p: string): string {
  // Both separators — Windows paths are backslashed (round-4 fix).
  const parts = p.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || p;
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
        <li v-for="w in store.recentWorkspaces" :key="w.path">
          <button class="recent ui-section-row interactive" :title="w.path" @click="store.selectRecentWorkspace(w.path)">
            <span class="r-name">{{ basename(w.path) }}</span>
            <span class="r-path">{{ w.path }}</span>
            <span class="r-agent">{{ w.last_agent || "-" }}</span>
          </button>
        </li>
      </ul>
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
.picker .hint { font-size: var(--font-sm); color: var(--text-muted); margin: 0; }
/* 10d: recents reuse the .ui-section inset-grouped card; rows come from
 * .ui-section-row (padding/hover/dividers), so only content styles stay. */
.recents { width: 560px; max-width: 90vw; }
.recents ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; }
.recents li { width: 100%; }
.recents li:first-of-type .recent { border-top: none; }
.recent {
  width: 100%; display: flex; align-items: center; gap: var(--space-2); text-align: left;
  background: transparent; color: var(--text-2);
  border: none; font-size: var(--font-sm); cursor: pointer;
  overflow: hidden; /* B-01: long folder names must truncate, not overflow */
}
.recent:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: calc(-1 * var(--focus-ring-offset)); }
.r-name {
  color: var(--text-2); font-weight: 500; min-width: 80px; max-width: 45%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.r-path {
  flex: 1; min-width: 0; /* flex ellipsis needs min-width: 0 */
  color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-xs);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.r-agent { color: var(--info); font-size: var(--font-xs); }
.workspace {
  flex: 1; min-width: 0; background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-md); padding: var(--space-1) var(--space-3); font-size: var(--font-base);
}
</style>
