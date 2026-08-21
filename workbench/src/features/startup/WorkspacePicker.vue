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
    <div v-if="store.recentWorkspaces.length" class="recents">
      <div class="recents-label">{{ t("picker.recents") }}</div>
      <ul>
        <li v-for="w in store.recentWorkspaces" :key="w.path">
          <button class="recent" :title="w.path" @click="store.selectRecentWorkspace(w.path)">
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
  gap: 12px;
  color: var(--text-2);
}
.picker .row { display: flex; gap: 8px; width: 560px; max-width: 90vw; }
.picker .hint { font-size: var(--font-sm); color: var(--text-muted); }
.recents { width: 560px; max-width: 90vw; margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.recents-label { font-size: var(--font-xs); color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.5px; }
.recents ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.recents li { width: 100%; }
.recent {
  width: 100%; display: flex; align-items: center; gap: 8px; text-align: left;
  background: var(--surface); color: var(--text-2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), border-color var(--duration-normal) var(--ease);
}
.recent:hover { background: var(--surface-2); border-color: var(--border-2); }
.recent:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
.r-name { color: var(--text-2); font-weight: 500; min-width: 80px; }
.r-path { flex: 1; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r-agent { color: var(--info); font-size: var(--font-xs); }
.workspace {
  flex: 1; min-width: 0; background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-md); padding: var(--space-1) var(--space-3); font-size: var(--font-base);
}
</style>
