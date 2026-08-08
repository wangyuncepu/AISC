<script setup lang="ts">
/**
 * TabBar (S2.2.a): the 4 fixed agent tabs (03 §六). Each tab is a Session
 * view over the shared runtime. Click activates (idle tabs open on first
 * activation); running tabs close to exited; exited/failed/disconnected tabs
 * can be reopened with a fresh session id.
 */
import { ref } from "vue";
import { useRuntimeStore } from "../../stores/runtime";
import type { Tab, TabSessionState } from "../../types";

const store = useRuntimeStore();

// S3.3: ARIA tabs keyboard navigation (Left/Right/Up/Down move + activate,
// Home/End first/last, wrap-around).
const tabRefs = ref<(HTMLButtonElement | null)[]>([]);

function setTabRef(i: number) {
  return (el: unknown) => {
    tabRefs.value[i] = (el as HTMLButtonElement | null) ?? null;
  };
}

function onTablistKeydown(e: KeyboardEvent) {
  const count = store.tabs.length;
  if (count === 0) return;
  const currentIdx = store.tabs.findIndex((t) => t.tabId === store.activeTabId);
  let target = -1;
  switch (e.key) {
    case "ArrowLeft":
    case "ArrowUp":
      target = currentIdx <= 0 ? count - 1 : currentIdx - 1;
      break;
    case "ArrowRight":
    case "ArrowDown":
      target = currentIdx < 0 ? 0 : (currentIdx + 1) % count;
      break;
    case "Home":
      target = 0;
      break;
    case "End":
      target = count - 1;
      break;
    default:
      return;
  }
  e.preventDefault();
  const tab = store.tabs[target];
  if (tab) {
    store.activateTab(tab.tabId);
    tabRefs.value[target]?.focus();
  }
}

function stateLabel(t: Tab): string {
  switch (t.sessionState) {
    case "idle":
      return "未打开";
    case "starting":
      return "启动中";
    case "running":
      return "";
    case "closing":
      return "关闭中";
    case "exited":
      return t.exit
        ? `退出${t.exit.exitCode !== null ? ` ${t.exit.exitCode}` : ""}`
        : "已退出";
    case "failed":
      return "失败";
    case "disconnected":
      return "已断开";
  }
}

function canClose(s: TabSessionState): boolean {
  return s === "starting" || s === "running" || s === "closing";
}

function canReopen(s: TabSessionState): boolean {
  return s === "exited" || s === "failed" || s === "disconnected";
}
</script>

<template>
  <div class="tabbar" role="tablist" @keydown="onTablistKeydown">
    <button
      v-for="(t, i) in store.tabs"
      :key="t.tabId"
      :ref="setTabRef(i)"
      role="tab"
      class="tab"
      :class="[t.sessionState, { active: t.tabId === store.activeTabId }]"
      :aria-selected="t.tabId === store.activeTabId"
      :aria-controls="`terminal-${t.tabId}`"
      :title="t.title"
      @click="store.activateTab(t.tabId)"
    >
      <span class="title">{{ t.title }}</span>
      <span v-if="stateLabel(t)" class="state">{{ stateLabel(t) }}</span>
      <span class="actions" v-if="canClose(t.sessionState) || canReopen(t.sessionState)">
        <button
          v-if="canClose(t.sessionState)"
          class="icon x"
          title="关闭会话（保留 Runtime）"
          @click.stop="store.closeTab(t.tabId)"
        >×</button>
        <button
          v-if="canReopen(t.sessionState)"
          class="icon reopen"
          title="重新打开（新会话）"
          @click.stop="store.reopenTab(t.tabId)"
        >↻</button>
      </span>
    </button>
  </div>
</template>

<style scoped>
.tabbar {
  display: flex;
  align-items: stretch;
  gap: 2px;
  padding: 0 6px;
  background: #252526;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}
.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: transparent;
  color: #888;
  border: none;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  font-size: 13px;
  cursor: pointer;
}
.tab:hover { background: #2d2d2d; color: #ccc; }
.tab.active { color: #ddd; border-bottom-color: #0e639c; background: #1e1e1e; }
.tab .title { font-weight: 500; }
.tab .state { font-size: 11px; color: #777; }
.tab.idle { color: #6a6a6a; }
.tab.starting .state, .tab.closing .state { color: #cca84a; }
.tab.exited .state { color: #888; }
.tab.failed .state { color: #e57373; }
.tab.disconnected .state { color: #e0a868; }
.actions { display: flex; gap: 2px; margin-left: 2px; }
.icon {
  background: transparent;
  border: none;
  color: inherit;
  padding: 0 4px;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  border-radius: 3px;
}
.icon:hover { background: #3c3c3c; color: #fff; }
.icon.reopen { color: #9cce9c; }
</style>
