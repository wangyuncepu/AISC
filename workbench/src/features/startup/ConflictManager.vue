<script setup lang="ts">
/**
 * ConflictManager (S2.2.b): shown when preflight returns `resolve_conflict`.
 * Lists Workbench-owned runtimes in the workspace (via `aisc runtime list`)
 * with their live state, and lets the user stop / remove the incompatible
 * one before re-preflighting (03 §三; 02 §四.2 runtime_conflict config gate).
 */
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();

function short(id: string): string {
  return id.slice(0, 8);
}
</script>

<template>
  <div class="conflict">
    <h2>{{ t("conflict.title") }}</h2>
    <p class="hint">{{ t("conflict.desc") }}</p>

    <ul class="list">
      <li v-for="r in store.conflicts" :key="r.runtime_id">
        <span class="rid" :title="r.runtime_id">{{ short(r.runtime_id) }}</span>
        <span class="state" :data-state="r.state">{{ r.state }}</span>
        <span class="cfg">{{ r.config.image || "?" }} · {{ r.config.scope || "?" }}</span>
        <span class="act">
          <button
            v-if="r.state === 'running' || r.state === 'starting'"
            @click="store.stopConflictRuntime(r.runtime_id)"
          >{{ t("conflict.stop") }}</button>
          <button
            v-if="r.state === 'running' || r.state === 'starting'"
            class="danger"
            :title="t('conflict.forceRemoveTitle')"
            @click="store.removeConflictRuntime(r.runtime_id, true)"
          >{{ t("conflict.forceRemove") }}</button>
          <button
            v-else-if="r.state === 'stopped' || r.state === 'stopping' || r.state === 'not_found'"
            class="danger"
            @click="store.removeConflictRuntime(r.runtime_id, false)"
          >{{ t("conflict.remove") }}</button>
        </span>
      </li>
      <li v-if="store.conflicts.length === 0" class="empty">{{ t("conflict.empty") }}</li>
    </ul>

    <p v-if="store.conflictError" class="err">{{ store.conflictError.message }}</p>

    <div class="actions">
      <button class="primary" @click="store.retryFromConflict()">{{ t("conflict.repreflight") }}</button>
      <button @click="store.backToPicker()">{{ t("conflict.back") }}</button>
    </div>
  </div>
</template>

<style scoped>
.conflict {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  color: var(--text-2);
}
.conflict h2 { color: var(--text-2); margin: 0; }
.hint { font-size: 12px; color: var(--text-muted); max-width: 480px; text-align: center; margin: 0; }
.list {
  list-style: none;
  padding: 0;
  margin: 8px 0;
  width: 560px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
}
.rid { font-family: monospace; color: var(--info); }
.state { font-size: 11px; color: var(--text-muted); min-width: 70px; }
.state[data-state="running"] { color: var(--success); }
.state[data-state="stopped"] { color: var(--warn); }
.state[data-state="unknown"] { color: var(--text-muted); }
.cfg { flex: 1; color: var(--text-muted); font-size: 12px; }
.act { display: flex; gap: 4px; }
.empty { color: var(--text-muted); font-size: 12px; justify-content: center; }
.err { color: var(--error); font-size: 12px; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: var(--surface-hover); }
button.primary { background: var(--accent); border-color: var(--accent); }
button.primary:hover { background: var(--accent-hover); }
button.danger { background: var(--error-bg); border-color: var(--error-border); }
button.danger:hover { background: var(--error-hover); }
</style>
