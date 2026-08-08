<script setup lang="ts">
/**
 * S2.1.a startup shell: routes between startup-state views (02 §三) and the
 * terminal workspace. Capability gate on mount.
 */
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useRuntimeStore } from "./stores/runtime";
import { useRuntimePolling } from "./composables/useRuntimePolling";
import { useProviderPolling } from "./composables/useProviderPolling";
import Terminal from "./features/terminal/Terminal.vue";
import TabBar from "./features/workspace/TabBar.vue";
import RuntimeSidebar from "./features/workspace/RuntimeSidebar.vue";
import LaunchSummary from "./features/startup/LaunchSummary.vue";
import StartProgress from "./features/startup/StartProgress.vue";
import BuildProgress from "./features/startup/BuildProgress.vue";
import ConflictManager from "./features/startup/ConflictManager.vue";

const store = useRuntimeStore();
const polling = useRuntimePolling();
const providerPolling = useProviderPolling();

onMounted(() => {
  store.negotiate();
  // S2.2.b: exit-Workbench gate (02 §七.3). Always prevent the default close
  // and decide explicitly: confirm + end live sessions if any, then destroy.
  // The runtime is left running. (preventDefault must precede the async
  // confirm, otherwise the default close races the awaited dialog.)
  void getCurrentWindow().onCloseRequested(async (event) => {
    event.preventDefault();
    const allow = await store.confirmExit();
    if (allow) {
      await getCurrentWindow().destroy();
    }
  });
});

// S2.3.a/b: poll runtime + provider state while a runtime is active (ready),
// so external stop/remove is reflected within one poll cycle (04 §五; Phase 2).
watch(
  () => store.status,
  (s) => {
    if (s === "ready") {
      polling.start();
      providerPolling.start();
    } else {
      polling.stop();
      providerPolling.stop();
    }
  }
);

onBeforeUnmount(() => {
  polling.stop();
  providerPolling.stop();
});

function isStartingView(s: string): boolean {
  return s === "starting" || s === "cancelled";
}

// S2.2.a: render a Terminal for every non-idle tab; v-show keeps hidden tabs
// (and their PTY) alive so switching back preserves scrollback (03 §六.8).
const openTabs = computed(() => store.tabs.filter((t) => t.sessionState !== "idle"));

// S2.4.a: recent workspaces (from history) in the picker.
function basename(p: string): string {
  const parts = p.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || p;
}
function selectRecent(path: string): void {
  store.selectRecentWorkspace(path);
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
      <div v-if="store.recentWorkspaces.length" class="recents">
        <div class="recents-label">最近工作区</div>
        <ul>
          <li v-for="w in store.recentWorkspaces" :key="w.path">
            <button class="recent" :title="w.path" @click="selectRecent(w.path)">
              <span class="r-name">{{ basename(w.path) }}</span>
              <span class="r-path">{{ w.path }}</span>
              <span class="r-agent">{{ w.last_agent || "-" }}</span>
            </button>
          </li>
        </ul>
      </div>
    </div>

    <!-- Launch summary (preflight gate + config + Start) -->
    <div v-else-if="store.status === 'summary'" class="main">
      <LaunchSummary />
    </div>

    <!-- Start progress / cancel -->
    <div v-else-if="isStartingView(store.status)" class="main">
      <StartProgress />
    </div>

    <!-- Build progress (image missing -> aisc build --events) -->
    <div v-else-if="store.status === 'building'" class="main">
      <BuildProgress />
    </div>

    <!-- Runtime conflict (resolve_conflict -> list/stop/remove) -->
    <div v-else-if="store.status === 'conflict'" class="main">
      <ConflictManager />
    </div>

    <!-- Terminal workspace -->
    <div v-else-if="store.status === 'ready'" class="ready">
      <RuntimeSidebar />
      <div class="main">
        <TabBar />
        <main class="terminal-area">
          <Terminal
            v-for="t in openTabs"
            :key="t.tabId"
            :tab-id="t.tabId"
            v-show="t.tabId === store.activeTabId"
          />
        </main>
      </div>
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
.recents { width: 560px; max-width: 90vw; margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.recents-label { font-size: 11px; color: #6a6a6a; text-transform: uppercase; letter-spacing: 0.5px; }
.recents ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.recents li { width: 100%; }
.recent {
  width: 100%; display: flex; align-items: center; gap: 8px; text-align: left;
  background: #252526; color: #ccc; border: 1px solid #333; border-radius: 4px;
  padding: 6px 10px; font-size: 12px; cursor: pointer;
}
.recent:hover { background: #2d2d2d; border-color: #444; }
.r-name { color: #ddd; font-weight: 500; min-width: 80px; }
.r-path { flex: 1; color: #777; font-family: monospace; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r-agent { color: #9cdcfe; font-size: 11px; }
.workspace {
  flex: 1; min-width: 0; background: #252526; color: #ddd;
  border: 1px solid #444; border-radius: 4px; padding: 6px 8px; font-size: 13px;
}
.ready { flex: 1; display: flex; min-height: 0; }
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
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
