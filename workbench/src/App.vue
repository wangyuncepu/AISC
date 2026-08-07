<script setup lang="ts">
/**
 * S2.1.a startup shell: routes between startup-state views (02 §三) and the
 * terminal workspace. Capability gate on mount.
 */
import { onMounted } from "vue";
import { useRuntimeStore } from "./stores/runtime";
import Terminal from "./features/terminal/Terminal.vue";
import LaunchSummary from "./features/startup/LaunchSummary.vue";
import StartProgress from "./features/startup/StartProgress.vue";

const store = useRuntimeStore();

onMounted(() => {
  store.negotiate();
});

function isStartingView(s: string): boolean {
  return s === "starting" || s === "cancelled";
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <span class="brand">AISC Workbench</span>
      <span class="status" :data-status="store.status">{{ store.status }}</span>
    </header>

    <!-- Capability gate -->
    <div v-if="store.status === 'blocked'" class="gate blocked">
      <h2>无法启动 Workbench 主路径</h2>
      <p class="err">{{ store.error?.message ?? "AISC CLI 不可用" }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <button @click="store.pickAndPinCli()">选择 AISC CLI</button>
    </div>

    <!-- Loading / stopping -->
    <div v-else-if="['idle', 'negotiating', 'preflight', 'stopping'].includes(store.status)" class="center">
      <p class="msg">{{
        store.status === "stopping"
          ? "正在停止 Runtime…"
          : store.status === "preflight"
          ? "正在预检环境…"
          : "正在协商 AISC CLI 能力…"
      }}</p>
    </div>

    <!-- Workspace picker -->
    <div v-else-if="store.status === 'picker'" class="picker">
      <h2>选择工作区</h2>
      <div class="row">
        <input
          v-model="store.workspace"
          class="workspace"
          placeholder="工作区路径（如 /home/user/project）"
          @keyup.enter="store.runPreflight()"
        />
        <button @click="store.pickWorkspace()">选择</button>
        <button class="primary" :disabled="!store.workspace.trim()" @click="store.runPreflight()">下一步</button>
      </div>
      <p class="hint">Workbench 不会自动创建目录或 runtime；选择后执行只读预检。</p>
    </div>

    <!-- Launch summary (preflight gate + config + Start) -->
    <div v-else-if="store.status === 'summary'" class="main">
      <LaunchSummary />
    </div>

    <!-- Start progress / cancel -->
    <div v-else-if="isStartingView(store.status)" class="main">
      <StartProgress />
    </div>

    <!-- Terminal workspace -->
    <div v-else-if="store.status === 'ready'" class="main">
      <div class="toolbar">
        <span class="meta">{{ store.workspace }}</span>
        <span class="meta">agent={{ store.launch.agent }}</span>
        <span class="meta">{{ store.runtimeId.slice(0, 8) }}</span>
        <button class="danger" @click="store.stopRuntime()">停止 Runtime</button>
      </div>
      <main class="terminal-area">
        <Terminal />
      </main>
    </div>

    <!-- Error -->
    <div v-else-if="store.status === 'error'" class="gate error">
      <h2>操作失败</h2>
      <p class="err">{{ store.error?.message }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <div class="actions">
        <button @click="store.negotiate()">重试</button>
        <button @click="store.backToPicker()">返回</button>
      </div>
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
.brand { font-weight: 600; }
.status { font-size: 12px; color: #888; }
.status[data-status="ready"] { color: #4caf50; }
.status[data-status="error"], .status[data-status="blocked"] { color: #e57373; }
.gate.blocked, .gate.error, .center, .picker {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #ccc;
}
.gate .err, .picker h2 { color: #ddd; }
.gate .detail { font-size: 12px; color: #888; }
.center .msg { color: #888; }
.picker { gap: 12px; }
.picker .row { display: flex; gap: 8px; width: 560px; max-width: 90vw; }
.picker .hint { font-size: 12px; color: #888; }
.workspace {
  flex: 1; min-width: 0; background: #252526; color: #ddd;
  border: 1px solid #444; border-radius: 4px; padding: 6px 8px; font-size: 13px;
}
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.toolbar {
  display: flex; gap: 12px; align-items: center;
  padding: 6px 12px; background: #1e1e1e; border-bottom: 1px solid #333;
}
.meta { font-size: 12px; color: #888; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover:not(:disabled) { background: #1177bb; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
button.danger:hover:not(:disabled) { background: #6e3a3a; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
.terminal-area { flex: 1; min-height: 0; padding: 4px; background: #1e1e1e; }
</style>
