<script setup lang="ts">
/**
 * TabBar (G-08, Step 5): dynamic tabs over the shared runtime. A + menu
 * creates any agent tab (duplicates allowed, capped at 8 per runtime); ×
 * removes a tab entirely (live sessions close best-effort); exited/failed/
 * disconnected tabs can be reopened with a fresh session id. ARIA tablist
 * with arrow/Home/End navigation; the + menu is a keyboard-reachable popup.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { AGENTS } from "../../stores/tabLayout";
import type { LaunchAgent, Tab, TabSessionState } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();

// --- G-08 + menu (aria-haspopup; Enter/Space opens, arrows move, Enter picks) ---
const menuOpen = ref(false);
const menuRef = ref<HTMLUListElement | null>(null);

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
  if (menuOpen.value) {
    window.setTimeout(() => menuRef.value?.querySelector<HTMLElement>("[role=menuitem]")?.focus(), 0);
  }
}

function onMenuKeydown(e: KeyboardEvent) {
  if (!menuOpen.value) return;
  const items = Array.from(menuRef.value?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
  const idx = items.findIndex((el) => el === document.activeElement);
  if (e.key === "Escape" || e.key === "Tab") {
    menuOpen.value = false;
    if (e.key === "Escape") e.preventDefault();
    return;
  }
  if (e.key === "ArrowDown" || e.key === "ArrowRight") {
    e.preventDefault();
    items[(idx + 1) % items.length]?.focus();
  } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
    e.preventDefault();
    items[(idx - 1 + items.length) % items.length]?.focus();
  } else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    if (idx >= 0) choose(items[idx].dataset.agent as LaunchAgent);
  }
}

function choose(agent: LaunchAgent) {
  menuOpen.value = false;
  store.createTab(agent);
}

function onDocMousedown(e: MouseEvent) {
  if (menuOpen.value && !(e.target as HTMLElement).closest(".menu-wrap")) {
    menuOpen.value = false;
  }
}

onMounted(() => document.addEventListener("mousedown", onDocMousedown));
onBeforeUnmount(() => document.removeEventListener("mousedown", onDocMousedown));

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

function stateLabel(tab: Tab): string {
  switch (tab.sessionState) {
    case "idle":
      return t("tabbar.idle");
    case "guide":
      return t("tabbar.guide");
    case "starting":
      return t("tabbar.starting");
    case "running":
      return "";
    case "closing":
      return t("tabbar.closing");
    case "exited":
      return tab.exit
        ? tab.exit.exitCode !== null
          ? t("tabbar.exitedCode", { code: tab.exit.exitCode })
          : t("tabbar.exited")
        : t("tabbar.exited");
    case "failed":
      return t("tabbar.failed");
    case "disconnected":
      return t("tabbar.disconnected");
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
      v-for="(tab, i) in store.tabs"
      :key="tab.tabId"
      :ref="setTabRef(i)"
      role="tab"
      class="tab"
      :class="[tab.sessionState, { active: tab.tabId === store.activeTabId }]"
      :aria-selected="tab.tabId === store.activeTabId"
      :aria-controls="`terminal-${tab.tabId}`"
      :title="tab.title"
      @click="store.activateTab(tab.tabId)"
    >
      <span class="title">{{ tab.title }}</span>
      <span v-if="stateLabel(tab)" class="state">{{ stateLabel(tab) }}</span>
      <span class="actions" v-if="canClose(tab.sessionState) || canReopen(tab.sessionState)">
        <button
          v-if="canClose(tab.sessionState)"
          class="icon x"
          :title="t('tabbar.closeTitle')"
          @click.stop="store.removeTab(tab.tabId)"
        >×</button>
        <button
          v-if="canReopen(tab.sessionState)"
          class="icon reopen"
          :title="t('tabbar.reopenTitle')"
          @click.stop="store.reopenTab(tab.tabId)"
        >↻</button>
      </span>
    </button>

    <!-- G-08: + menu (duplicates allowed; cap enforced by the store) -->
    <div class="menu-wrap">
      <button
        class="icon add"
        :aria-label="t('tabbar.newTab')"
        :title="t('tabbar.newTab')"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
        @keydown="onMenuKeydown"
      >+</button>
      <ul v-if="menuOpen" ref="menuRef" class="menu" role="menu" @keydown="onMenuKeydown">
        <li
          v-for="a in AGENTS"
          :key="a"
          role="menuitem"
          tabindex="0"
          :data-agent="a"
          @click="choose(a)"
        >{{ t(`tabbar.menu.${a}`) }}</li>
      </ul>
    </div>
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
.icon.add { color: #9cdcfe; font-size: 16px; margin-left: 4px; }
.menu-wrap { position: relative; display: flex; align-items: center; }
.menu {
  position: absolute; top: 100%; left: 0; z-index: 30;
  list-style: none; margin: 2px 0 0; padding: 4px 0;
  background: #2d2d2d; border: 1px solid #444; border-radius: 4px;
  min-width: 140px;
}
.menu li {
  padding: 6px 12px; font-size: 13px; color: #ccc; cursor: pointer;
  outline: none;
}
.menu li:hover, .menu li:focus { background: #3c3c3c; color: #fff; }
</style>
