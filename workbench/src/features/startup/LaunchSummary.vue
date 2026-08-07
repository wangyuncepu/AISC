<script setup lang="ts">
/** Launch summary (02 §七): preflight gate + inferred config + Start/Change/Cancel. */
import { computed } from "vue";
import { useRuntimeStore } from "../../stores/runtime";
import PreflightGate from "./PreflightGate.vue";
import type { LaunchAgent } from "../../types";

const store = useRuntimeStore();

const agents: LaunchAgent[] = ["claude", "codex", "bash", "cc-switch"];

const action = computed(() => store.preflight?.recommended_action ?? "start");
const actionText = computed(
  () => ({ start: "新建 Runtime", reuse: "复用运行中 Runtime", restart: "重启已停止 Runtime", resolve_conflict: "需解决冲突" }[action.value] ?? action.value)
);

function checkStatus(id: string): string {
  return store.preflight?.checks.find((c) => c.id === id)?.status ?? "pass";
}

const hardBlocking = computed(() => checkStatus("docker") === "fail" || checkStatus("workspace") === "fail");
const imageMissing = computed(() => checkStatus("image") === "fail" && action.value !== "reuse");
const startEnabled = computed(
  () =>
    !!store.preflight &&
    ["start", "reuse", "restart"].includes(action.value) &&
    !hardBlocking.value &&
    !imageMissing.value
);

function changeSettings() {
  store.showAdvanced = !store.showAdvanced;
}

function onConfigChanged() {
  store.recomputePreflightNeeded();
}
</script>

<template>
  <div class="summary">
    <h2>启动摘要</h2>
    <PreflightGate v-if="store.preflight" :report="store.preflight" />

    <div class="row"><span class="k">Workspace</span><span class="v">{{ store.workspace }}</span></div>
    <div class="row">
      <span class="k">Agent</span>
      <select v-model="store.launch.agent" :disabled="store.showAdvanced === false && false">
        <option v-for="a in agents" :key="a" :value="a">{{ a }}</option>
      </select>
    </div>
    <div class="row"><span class="k">Runtime</span><span class="v">{{ actionText }}</span></div>

    <div v-if="store.showAdvanced" class="advanced">
      <div class="row">
        <span class="k">Image</span>
        <input v-model="store.launch.image" @change="onConfigChanged" />
      </div>
      <div class="row">
        <span class="k">Network</span>
        <select v-model="store.launch.network" @change="onConfigChanged">
          <option value="direct">direct</option>
          <option value="proxy">proxy</option>
        </select>
      </div>
      <div class="row">
        <span class="k">Scope</span>
        <select v-model="store.launch.scope" @change="onConfigChanged">
          <option value="project">project</option>
          <option value="temporary">temporary</option>
        </select>
      </div>
    </div>

    <p v-if="imageMissing" class="gate-msg config">
      镜像缺失（Config gate）。可点击「构建镜像」用 `aisc build --events` 构建（可取消）。
    </p>
    <p v-else-if="hardBlocking" class="gate-msg hard">
      Hard gate 未通过，无法启动。请修复 Docker / workspace 权限后重试。
    </p>
    <p v-else-if="action === 'resolve_conflict'" class="gate-msg hard">
      工作区已有不兼容 Runtime，需先停止或复用它。
    </p>

    <div class="actions">
      <button class="primary" :disabled="!startEnabled" @click="store.startFromSummary()">Start</button>
      <button @click="changeSettings">{{ store.showAdvanced ? "收起设置" : "Change settings" }}</button>
      <button v-if="imageMissing" class="danger" @click="store.startBuild(store.launch.image)">构建镜像</button>
      <button @click="store.backToPicker()">Cancel</button>
    </div>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  color: #ccc;
  overflow: auto;
}
h2 { margin: 0 0 4px; font-size: 15px; }
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.k { width: 90px; color: #888; }
.v { color: #ddd; word-break: break-all; }
input, select {
  background: #252526;
  color: #ddd;
  border: 1px solid #444;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 13px;
  flex: 1;
  min-width: 0;
}
.advanced {
  padding: 8px;
  background: #252526;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gate-msg { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin: 0; }
.gate-msg.config { background: #3a3220; color: #e0c97a; }
.gate-msg.hard { background: #4a2626; color: #e0b0b0; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover:not(:disabled) { background: #1177bb; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
</style>
