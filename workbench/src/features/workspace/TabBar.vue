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

// S3.3 / S1.6: ARIA tabs keyboard navigation (APG tabs pattern).
// Arrow/Home/End move FOCUS within the tablist (roving tabindex) WITHOUT
// activating - activation happens on Enter/Space, which is what sends the
// focus to the terminal. (Directly activateTab-ing on Arrow made the app-wide
// activeTabId watcher move keyboard focus to the terminal, so the next Arrow
// landed in the terminal and navigation appeared broken.)
const tabRefs = ref<(HTMLButtonElement | null)[]>([]);
const roving = ref(-1); // -1 = no manual roving; follow the active tab

function setTabRef(i: number) {
  return (el: unknown) => {
    tabRefs.value[i] = (el as HTMLButtonElement | null) ?? null;
  };
}

function tabIndex(tab: Tab, i: number): string {
  if (roving.value >= 0) return roving.value === i ? "0" : "-1";
  return tab.tabId === store.activeTabId ? "0" : "-1";
}

function onTabClick(tabId: string) {
  roving.value = -1;
  store.activateTab(tabId);
}

function onTablistKeydown(e: KeyboardEvent) {
  const count = store.tabs.length;
  if (count === 0) return;
  const activeIdx = store.tabs.findIndex((t) => t.tabId === store.activeTabId);
  const base = roving.value >= 0 ? roving.value : activeIdx;

  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    const pick = roving.value >= 0 ? roving.value : activeIdx;
    if (pick >= 0) {
      store.activateTab(store.tabs[pick].tabId);
      roving.value = -1;
    }
    return;
  }

  let target = -1;
  switch (e.key) {
    case "ArrowLeft":
    case "ArrowUp":
      target = base <= 0 ? count - 1 : base - 1;
      break;
    case "ArrowRight":
    case "ArrowDown":
      target = base < 0 ? 0 : (base + 1) % count;
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
  // Move focus only; activation waits for Enter/Space.
  e.preventDefault();
  roving.value = target;
  tabRefs.value[target]?.focus();
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
  // guide tabs have no session to terminate but must stay removable (×).
  return s === "starting" || s === "running" || s === "closing" || s === "guide";
}

function canReopen(s: TabSessionState): boolean {
  return s === "exited" || s === "failed" || s === "disconnected";
}
</script>

<template>
  <div class="tabbar" role="tablist" aria-orientation="horizontal" @keydown="onTablistKeydown">
    <!-- S1.6 (F-A06): the tab is a NON-interactive wrapper; the tab activation
         and the close/reopen actions are sibling buttons (no nested button,
         which was invalid and broke focus semantics). The wrapper keeps the
         visual active/hover state; tab-main carries role=tab. -->
    <div
      v-for="(tab, i) in store.tabs"
      :key="tab.tabId"
      class="tab"
      :class="[tab.sessionState, { active: tab.tabId === store.activeTabId }]"
    >
      <button
        :ref="setTabRef(i)"
        role="tab"
        class="tab-main"
        :tabindex="tabIndex(tab, i)"
        :aria-selected="tab.tabId === store.activeTabId"
        :aria-controls="`terminal-${tab.tabId}`"
        :title="tab.title"
        @click="onTabClick(tab.tabId)"
      >
        <span class="title">{{ tab.title }}</span>
        <span v-if="stateLabel(tab)" class="state">{{ stateLabel(tab) }}</span>
      </button>
      <span class="actions" v-if="canClose(tab.sessionState) || canReopen(tab.sessionState)">
        <button
          v-if="canClose(tab.sessionState)"
          class="icon x"
          :title="t('tabbar.closeTitle')"
          :aria-label="t('tabbar.closeTitle')"
          @click="store.removeTab(tab.tabId)"
        >×</button>
        <button
          v-if="canReopen(tab.sessionState)"
          class="icon reopen"
          :title="t('tabbar.reopenTitle')"
          :aria-label="t('tabbar.reopenTitle')"
          @click="store.reopenTab(tab.tabId)"
        >↻</button>
      </span>
    </div>

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
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px 6px 10px;
  background: transparent;
  color: var(--text-muted);
  border-bottom: 2px solid transparent;
}
.tab:hover { background: var(--surface-2); color: var(--text-2); }
.tab.active { color: var(--text-2); border-bottom-color: var(--accent); background: var(--bg); }
.tab-main {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab .title { font-weight: 500; }
.tab .state { font-size: 11px; color: var(--text-muted); }
.tab.idle { color: var(--text-faint); }
.tab.starting .state, .tab.closing .state { color: var(--warn); }
.tab.exited .state { color: var(--text-muted); }
.tab.failed .state { color: var(--error); }
.tab.disconnected .state { color: var(--warn); }
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
.icon:hover { background: var(--surface-hover); color: var(--text); }
.icon.reopen { color: var(--success); }
.icon.add { color: var(--info); font-size: 16px; margin-left: 4px; }
.menu-wrap { position: relative; display: flex; align-items: center; }
.menu {
  position: absolute; top: 100%; left: 0; z-index: 30;
  list-style: none; margin: 2px 0 0; padding: 4px 0;
  background: var(--surface-2); border: 1px solid var(--border-2); border-radius: 4px;
  min-width: 140px;
}
.menu li {
  padding: 6px 12px; font-size: 13px; color: var(--text-2); cursor: pointer;
  outline: none;
}
.menu li:hover, .menu li:focus { background: var(--surface-hover); color: var(--text); }
</style>
