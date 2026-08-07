<script setup lang="ts">
/**
 * ConflictManager (S2.2.b): shown when preflight returns `resolve_conflict`.
 * Lists Workbench-owned runtimes in the workspace (via `aisc runtime list`)
 * with their live state, and lets the user stop / remove the incompatible
 * one before re-preflighting (03 §三; 02 §四.2 runtime_conflict config gate).
 */
import { useRuntimeStore } from "../../stores/runtime";

const store = useRuntimeStore();

function short(id: string): string {
  return id.slice(0, 8);
}
</script>

<template>
  <div class="conflict">
    <h2>工作区已有 Runtime</h2>
    <p class="hint">
      工作区存在不兼容的 Workbench Runtime，需先停止或移除后才能继续启动。
    </p>

    <ul class="list">
      <li v-for="r in store.conflicts" :key="r.runtime_id">
        <span class="rid" :title="r.runtime_id">{{ short(r.runtime_id) }}</span>
        <span class="state" :data-state="r.state">{{ r.state }}</span>
        <span class="cfg">{{ r.config.image || "?" }} · {{ r.config.scope || "?" }}</span>
        <span class="act">
          <button
            v-if="r.state === 'running' || r.state === 'starting'"
            @click="store.stopConflictRuntime(r.runtime_id)"
          >停止</button>
          <button
            v-if="r.state === 'running' || r.state === 'starting'"
            class="danger"
            title="强制移除运行中的 Runtime"
            @click="store.removeConflictRuntime(r.runtime_id, true)"
          >强制移除</button>
          <button
            v-else-if="r.state === 'stopped' || r.state === 'stopping'"
            class="danger"
            @click="store.removeConflictRuntime(r.runtime_id, false)"
          >移除</button>
        </span>
      </li>
      <li v-if="store.conflicts.length === 0" class="empty">无 Runtime（可重新预检）</li>
    </ul>

    <p v-if="store.conflictError" class="err">{{ store.conflictError.message }}</p>

    <div class="actions">
      <button class="primary" @click="store.retryFromConflict()">重新预检</button>
      <button @click="store.backToPicker()">返回</button>
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
  color: #ccc;
}
.conflict h2 { color: #ddd; margin: 0; }
.hint { font-size: 12px; color: #888; max-width: 480px; text-align: center; margin: 0; }
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
  background: #252526;
  border: 1px solid #333;
  border-radius: 4px;
  font-size: 13px;
}
.rid { font-family: monospace; color: #9cdcfe; }
.state { font-size: 11px; color: #888; min-width: 70px; }
.state[data-state="running"] { color: #4caf50; }
.state[data-state="stopped"] { color: #cca84a; }
.state[data-state="unknown"] { color: #888; }
.cfg { flex: 1; color: #aaa; font-size: 12px; }
.act { display: flex; gap: 4px; }
.empty { color: #888; font-size: 12px; justify-content: center; }
.err { color: #e57373; font-size: 12px; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover { background: #1177bb; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
button.danger:hover { background: #6e3a3a; }
</style>
