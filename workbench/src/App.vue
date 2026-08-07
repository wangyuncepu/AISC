<script setup lang="ts">
/**
 * Minimal end-to-end UI (S1.4): workspace input + "启动 Bash" + terminal +
 * "停止 Runtime". Capability gate on mount; blocking message + manual CLI pin
 * when required capabilities are missing.
 */
import { onMounted } from "vue";
import { useRuntimeStore } from "./stores/runtime";
import Terminal from "./features/terminal/Terminal.vue";

const store = useRuntimeStore();

onMounted(() => {
  store.negotiate();
});
</script>

<template>
  <div class="app">
    <header class="topbar">
      <span class="brand">AISC Workbench</span>
      <span class="status" :data-status="store.status">{{ store.status }}</span>
    </header>

    <!-- Capability gate: unsupported / no pinned CLI -->
    <div v-if="store.status === 'blocked'" class="gate blocked">
      <h2>无法启动 Workbench 主路径</h2>
      <p class="err">{{ store.error?.message ?? "AISC CLI 不可用" }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <button @click="store.pickAndPinCli()">选择 AISC CLI</button>
    </div>

    <!-- Main path -->
    <div v-else class="main">
      <div class="toolbar">
        <input
          v-model="store.workspace"
          class="workspace"
          placeholder="工作区路径（如 /home/user/project）"
          @keyup.enter="store.startBash()"
        />
        <button @click="store.pickWorkspace()" :disabled="store.status !== 'ready' && store.status !== 'running'">
          选择
        </button>
        <button
          class="primary"
          @click="store.startBash()"
          :disabled="!store.canStart() || store.status === 'starting' || store.status === 'stopping'"
        >
          {{ store.status === "starting" ? "启动中…" : "启动 Bash" }}
        </button>
        <button
          class="danger"
          @click="store.stopRuntime()"
          :disabled="store.status !== 'running' && store.status !== 'stopping'"
        >
          {{ store.status === "stopping" ? "停止中…" : "停止 Runtime" }}
        </button>
      </div>
      <p v-if="store.error && store.status === 'error'" class="toolbar-error">
        {{ store.error.message }}
        <button class="inline" @click="store.negotiate()">重试</button>
      </p>
      <main class="terminal-area">
        <Terminal />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  background: #252526;
  color: #ccc;
  font-size: 13px;
  border-bottom: 1px solid #333;
}
.brand {
  font-weight: 600;
}
.status {
  font-size: 12px;
  color: #888;
}
.status[data-status="running"] {
  color: #4caf50;
}
.status[data-status="error"],
.status[data-status="blocked"] {
  color: #e57373;
}
.gate.blocked {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #ccc;
}
.gate .err {
  color: #e57373;
}
.gate .detail {
  font-size: 12px;
  color: #888;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.toolbar {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: #1e1e1e;
  border-bottom: 1px solid #333;
}
.workspace {
  flex: 1;
  min-width: 0;
  background: #252526;
  color: #ddd;
  border: 1px solid #444;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 13px;
}
button {
  background: #333;
  color: #ddd;
  border: 1px solid #555;
  border-radius: 4px;
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
}
button:hover:not(:disabled) {
  background: #3c3c3c;
}
button:disabled {
  opacity: 0.45;
  cursor: default;
}
button.primary {
  background: #0e639c;
  border-color: #0e639c;
}
button.primary:hover:not(:disabled) {
  background: #1177bb;
}
button.danger {
  background: #5a2d2d;
  border-color: #6b3636;
}
button.danger:hover:not(:disabled) {
  background: #6e3a3a;
}
.toolbar-error {
  margin: 0;
  padding: 6px 12px;
  background: #4a2626;
  color: #e0b0b0;
  font-size: 13px;
  display: flex;
  gap: 8px;
  align-items: center;
}
button.inline {
  padding: 2px 8px;
  font-size: 12px;
}
.terminal-area {
  flex: 1;
  min-height: 0;
  padding: 4px;
  background: #1e1e1e;
}
</style>
