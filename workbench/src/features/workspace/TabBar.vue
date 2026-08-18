<script setup lang="ts">
/**
 * TabBar (G-08, Step 5): dynamic tabs over the shared runtime. A + split
 * button (IDEA-1, Windows Terminal style): the main + creates the DEFAULT
 * agent tab immediately (ui.default_tab_agent); the ▾ caret opens the full
 * menu (any agent + 设置). × removes a tab entirely (live sessions close
 * best-effort); exited/failed/disconnected tabs reopen with a fresh session
 * id. ARIA tablist with arrow/Home/End navigation; the ▾ menu is a
 * keyboard-reachable popup.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  CC_SWITCH_UI_TAB_ID,
  SETTINGS_TAB_ID,
  useRuntimeStore,
} from "../../stores/runtime";
import { useSettingsStore } from "../../stores/settings";
import { AGENTS } from "../../stores/tabLayout";
import type { LaunchAgent, Tab, TabSessionState } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();
const settingsStore = useSettingsStore();

// --- G-08 + menu (aria-haspopup; Enter/Space opens, arrows move, Enter picks) ---
const menuOpen = ref(false);
const menuRef = ref<HTMLUListElement | null>(null);
const addBtnRef = ref<HTMLButtonElement | null>(null);
const caretBtnRef = ref<HTMLButtonElement | null>(null);
const menuPos = ref({ x: 0, y: 0 });

/** IDEA-1: the + main button creates this agent directly (ui.default_tab_agent;
 * unknown/missing values fall back to bash, mirroring the Rust default). */
const defaultAgent = computed<LaunchAgent>(() => {
  const a = settingsStore.doc?.ui.default_tab_agent;
  return AGENTS.includes(a as LaunchAgent) ? (a as LaunchAgent) : "bash";
});

function createDefaultTab() {
  store.createTab(defaultAgent.value);
}

/**
 * The menu is teleported to <body> with fixed positioning: the tabbar is an
 * `overflow-x: auto` scroll container (UX-02), which CLIPS an absolutely
 * positioned dropdown that drops below the bar (Stage 6 regression — the
 * agent list appeared cut off). The app chrome is CSS-zoomed
 * (`ui.font_scale` → `.app { zoom }`), so button-rect coordinates must be
 * divided by the live zoom — same pattern as the Explorer context menu.
 */
function appZoom(): number {
  const app = document.querySelector<HTMLElement>(".app");
  if (!app) return 1;
  const w = app.offsetWidth || 0;
  return w > 0 ? app.getBoundingClientRect().width / w : 1;
}

function placeMenu() {
  const btn = caretBtnRef.value ?? addBtnRef.value;
  if (!btn) return;
  const zoom = appZoom();
  const rect = btn.getBoundingClientRect();
  const menuWidth = 160;
  menuPos.value = {
    x: Math.max(4, Math.min(rect.left / zoom, window.innerWidth / zoom - menuWidth)),
    y: rect.bottom / zoom + 2,
  };
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
  if (menuOpen.value) {
    placeMenu();
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
    if (idx >= 0) {
      // The settings entry carries data-agent="settings"; agents create a tab.
      if (items[idx].dataset.agent === "settings") chooseSettings();
      else if (items[idx].dataset.agent === "cc-switch-ui") chooseCcSwitchUi();
      else choose(items[idx].dataset.agent as LaunchAgent);
    }
  }
}

function choose(agent: LaunchAgent) {
  menuOpen.value = false;
  store.createTab(agent);
}

function chooseSettings() {
  menuOpen.value = false;
  store.openSettingsTab();
}

function chooseCcSwitchUi() {
  menuOpen.value = false;
  store.openCcSwitchUiTab();
}

function onDocMousedown(e: MouseEvent) {
  // The menu is teleported to <body>, so the containment check covers BOTH
  // the anchor button and the teleported menu itself (a mousedown on a menu
  // item must not close the menu before the click lands).
  const target = e.target as HTMLElement;
  if (menuOpen.value && !target.closest(".menu-wrap") && !target.closest(".tab-new-menu")) {
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
/** IDEA-1 + Stage 8e: virtual (session-less) tabs render after the session
 * tabs, in this fixed order — the roving/focus model appends them as indexes
 * `store.tabs.length + n`. */
const virtualTabs = computed(() => {
  const out: { id: string; labelKey: string; icon: string }[] = [];
  if (store.settingsTabOpen)
    out.push({ id: SETTINGS_TAB_ID, labelKey: "tabbar.settings", icon: "⚙" });
  if (store.ccSwitchUiTabOpen)
    out.push({ id: CC_SWITCH_UI_TAB_ID, labelKey: "tabbar.ccSwitchUi", icon: "⇄" });
  return out;
});
const virtualBtnRefs = new Map<string, HTMLButtonElement>();
function setVirtualRef(id: string) {
  return (el: unknown) => {
    if (el) virtualBtnRefs.set(id, el as HTMLButtonElement);
    else virtualBtnRefs.delete(id);
  };
}

/** Rendered tab count: session tabs + the open virtual tabs. */
const tabCount = computed(() => store.tabs.length + virtualTabs.value.length);

/** Index of the active chip in the rendered sequence (-1 = none). */
function activeIndex(): number {
  const i = store.tabs.findIndex((t) => t.tabId === store.activeTabId);
  if (i >= 0) return i;
  const v = virtualTabs.value.findIndex((v) => v.id === store.activeTabId);
  return v >= 0 ? store.tabs.length + v : -1;
}

/** Focus chip `i` (session tab or a virtual chip). */
function focusChip(i: number): void {
  if (i < store.tabs.length) tabRefs.value[i]?.focus();
  else virtualBtnRefs.get(virtualTabs.value[i - store.tabs.length]?.id ?? "")?.focus();
}

/** Activate a chip index (Enter/Space on the roving focus). */
function activateChip(i: number): void {
  if (i < store.tabs.length) {
    store.activateTab(store.tabs[i].tabId);
  } else {
    const id = virtualTabs.value[i - store.tabs.length]?.id;
    if (id === SETTINGS_TAB_ID) store.openSettingsTab();
    else if (id === CC_SWITCH_UI_TAB_ID) store.openCcSwitchUiTab();
  }
}

function setTabRef(i: number) {
  return (el: unknown) => {
    tabRefs.value[i] = (el as HTMLButtonElement | null) ?? null;
  };
}

function tabIndex(tab: Tab, i: number): string {
  if (roving.value >= 0) return roving.value === i ? "0" : "-1";
  return tab.tabId === store.activeTabId ? "0" : "-1";
}

/** roving tabindex for one virtual chip at rendered index `i`. */
function virtualTabIndex(i: number): string {
  if (roving.value >= 0) return roving.value === i ? "0" : "-1";
  return virtualTabs.value[i - store.tabs.length]?.id === store.activeTabId ? "0" : "-1";
}

function onVirtualClick(id: string) {
  roving.value = -1;
  if (id === SETTINGS_TAB_ID) store.openSettingsTab();
  else if (id === CC_SWITCH_UI_TAB_ID) store.openCcSwitchUiTab();
}

/** × on the Settings chip: revert unsaved edits (dialog-Cancel contract),
 * then close the virtual tab. */
function closeSettings() {
  settingsStore.cancel();
  store.closeSettingsTab();
}

/** × on the cc-switch UI chip (no unsaved-state contract — forms are
 * per-operation and the key field is transient). */
function closeCcSwitchUi() {
  store.closeCcSwitchUiTab();
}

function onTabClick(tabId: string) {
  roving.value = -1;
  store.activateTab(tabId);
}

function onTablistKeydown(e: KeyboardEvent) {
  const count = tabCount.value;
  if (count === 0) return;
  const activeIdx = activeIndex();
  const base = roving.value >= 0 ? roving.value : activeIdx;

  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    const pick = roving.value >= 0 ? roving.value : activeIdx;
    if (pick >= 0) {
      activateChip(pick);
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
  focusChip(target);
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

    <!-- IDEA-1 + Stage 8e: virtual session-less tabs (Settings, cc-switch
         Provider UI). Keyboard model: appended after the session tabs. -->
    <div
      v-for="(v, vi) in virtualTabs"
      :key="v.id"
      class="tab virtual-chip"
      :class="{ active: store.activeTabId === v.id }"
    >
      <button
        :ref="setVirtualRef(v.id)"
        role="tab"
        class="tab-main"
        :tabindex="virtualTabIndex(store.tabs.length + vi)"
        :aria-selected="store.activeTabId === v.id"
        :title="t(v.labelKey)"
        @click="onVirtualClick(v.id)"
      >{{ v.icon }} {{ t(v.labelKey) }}</button>
      <span class="actions">
        <button
          class="icon x"
          :title="t('tabbar.closeVirtual')"
          :aria-label="t('tabbar.closeVirtual')"
          @click="v.id === 'settings-tab' ? closeSettings() : closeCcSwitchUi()"
        >×</button>
      </span>
    </div>

    <!-- G-08 + IDEA-1: + split button. Main + creates the DEFAULT agent tab
         (ui.default_tab_agent) immediately; ▾ opens the full menu (any agent
         duplicates allowed — cap enforced by the store — plus 设置). The menu
         is teleported to <body>: the tabbar's overflow-x scroll container
         would clip an in-flow dropdown (Stage 6 UX-02 regression). -->
    <div class="menu-wrap">
      <button
        ref="addBtnRef"
        class="icon add"
        :aria-label="t('tabbar.newTabDefault', { agent: t(`tabbar.menu.${defaultAgent}`) })"
        :title="t('tabbar.newTabDefault', { agent: t(`tabbar.menu.${defaultAgent}`) })"
        @click="createDefaultTab"
      >+</button>
      <button
        ref="caretBtnRef"
        class="icon add-caret"
        :aria-label="t('tabbar.newTabChoose')"
        :title="t('tabbar.newTabChoose')"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
        @keydown="onMenuKeydown"
      >▾</button>
      <Teleport to="body">
        <ul
          v-if="menuOpen"
          ref="menuRef"
          class="menu tab-new-menu"
          role="menu"
          :style="{ left: `${menuPos.x}px`, top: `${menuPos.y}px` }"
          @keydown="onMenuKeydown"
        >
          <li
            v-for="a in AGENTS.filter((x) => x !== 'cc-switch')"
            :key="a"
            role="menuitem"
            tabindex="0"
            :data-agent="a"
            @click="choose(a)"
          >{{ t(`tabbar.menu.${a}`) }}</li>
          <li class="sep" role="separator" />
          <li
            role="menuitem"
            tabindex="0"
            data-agent="settings"
            @click="chooseSettings"
          >{{ t("tabbar.settings") }}</li>
          <li
            role="menuitem"
            tabindex="0"
            data-agent="cc-switch-ui"
            @click="chooseCcSwitchUi"
          >{{ t("tabbar.ccSwitchUi") }}</li>
        </ul>
      </Teleport>
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
  /* UX-02: many tabs at a narrow tier scroll instead of squishing */
  overflow-x: auto;
  scrollbar-width: thin;
}
.tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px 6px 10px;
  background: transparent;
  color: var(--text-muted);
  border-bottom: 2px solid transparent;
  flex-shrink: 0; /* UX-02: keep tab content, let the bar scroll */
  white-space: nowrap;
}
.tab:hover { background: var(--surface-2); color: var(--text-2); }
.tab.active { color: var(--text-2); border-bottom-color: var(--accent); background: var(--bg); }
.tab-main {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-size: var(--font-md);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab .title { font-weight: 500; }
.tab .state { font-size: var(--font-xs); color: var(--text-muted); }
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
  font-size: var(--font-base);
  line-height: 1;
  cursor: pointer;
  border-radius: 3px;
}
.icon:hover { background: var(--surface-hover); color: var(--text); }
.icon.reopen { color: var(--success); }
.icon.add { color: var(--info); font-size: var(--font-lg); margin-left: 4px; }
/* IDEA-1: split-button caret — visually attached to the + button. */
.icon.add-caret { color: var(--info); font-size: var(--font-sm); padding: 0 2px; }
.menu-wrap { position: relative; display: flex; align-items: center; }
/* Teleported to <body>: fixed + zoom-compensated coordinates (see placeMenu);
   scoped styles still apply because Teleport preserves scope ids. */
.menu {
  position: fixed; z-index: var(--z-drawer);
  list-style: none; margin: 0; padding: 4px 0;
  background: var(--surface-2); border: 1px solid var(--border-2); border-radius: var(--radius-md);
  min-width: 140px;
}
.menu li {
  padding: 6px 12px; font-size: var(--font-md); color: var(--text-2); cursor: pointer;
  outline: none;
}
.menu li:hover, .menu li:focus { background: var(--surface-hover); color: var(--text); }
.menu .sep { padding: 0; height: 1px; margin: 4px 8px; background: var(--border); cursor: default; }
.menu .sep:hover, .menu .sep:focus { background: var(--border); }
</style>
