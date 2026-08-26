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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { CC_SWITCH_UI_TAB_ID, useRuntimeStore } from "../../stores/runtime";
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
function placeMenu(): boolean {
  const btn = caretBtnRef.value ?? addBtnRef.value;
  if (!btn) return false;
  const rect = btn.getBoundingClientRect();
  // 10d: a detached / not-yet-laid-out ref reports an all-zero rect, and the
  // clamped minimum then parked the menu at the window's top-left corner
  // (user evidence 2.png). Refuse to open instead.
  if (rect.width === 0 && rect.height === 0) return false;
  // The teleported menu lives OUTSIDE the zoomed .app, so its fixed px are
  // viewport (VISUAL) px. r4: .app is sized width:100vw/scale, so the live
  // scale is innerWidth / app.offsetWidth regardless of engine. A visual-space
  // rect (modern engines: ratio == scale) is already correct; a layout-space
  // rect (legacy: ratio == 1) must be MULTIPLIED by the scale. Never divided —
  // dividing made the offset grow with the caret's distance from the left
  // edge (user evidence: more tabs → bigger drift at font_scale 1.5).
  const app = document.querySelector<HTMLElement>(".app");
  const scale = app && app.offsetWidth > 0 ? window.innerWidth / app.offsetWidth : 1;
  const ratio = btn.offsetWidth > 0 ? rect.width / btn.offsetWidth : 1;
  const z = Math.abs(scale - 1) < 0.02 ? 1 : (Math.abs(ratio - scale) < 0.05 ? 1 : scale);
  const menuWidth = 160;
  menuPos.value = {
    x: Math.max(4, Math.min(rect.left * z, window.innerWidth - menuWidth)),
    y: rect.bottom * z + 2,
  };
  return true;
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
  if (menuOpen.value) {
    // Place after the menu mounts AND after the next paint: opening the
    // menu right after closing a tab catches the +/▾ mid-FLIP, and transforms
    // DO land in getBoundingClientRect — the menu then anchored at the
    // transient position (occasional repro, user evidence 1.png). Double
    // rAF measures the settled layout.
    void nextTick(() => {
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (!placeMenu()) {
            menuOpen.value = false;
            return;
          }
          menuRef.value?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
        }),
      );
    });
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
      if (items[idx].dataset.agent === "cc-switch-ui") chooseCcSwitchUi();
      else choose(items[idx].dataset.agent as LaunchAgent);
    }
  }
}

function choose(agent: LaunchAgent) {
  menuOpen.value = false;
  store.createTab(agent);
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
  // IDEA-3 (3d): the Settings tab moved to the WORKSPACE strip; the only
  // session-layer virtual tab left is the cc-switch Provider UI.
  const out: { id: string; labelKey: string; icon: string }[] = [];
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
    if (id === CC_SWITCH_UI_TAB_ID) store.openCcSwitchUiTab();
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
  if (id === CC_SWITCH_UI_TAB_ID) store.openCcSwitchUiTab();
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
    case "dormant":
      // Stage 5: lazy-restored placeholder — muted, distinct from exited.
      return t("tabbar.dormant");
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

/** 10e r6 (probe-confirmed): a bash tab flashes「启动中」for ~2 frames
 * before the session turns running — the label widened the pill (118.9px)
 * which then snapped back (79.9px) and read as an ugly right-then-left
 * "jump". Only surface a state label once it has PERSISTED 150ms; the pill
 * width then never breathes for transient states. */
const STICKY_LABEL_DELAY = 150;
const stickyLabels = ref(new Map<string, string>());
const stickyTimers = new Map<string, number>();

watch(
  () => store.tabs.map((tb) => ({ id: tb.tabId, label: stateLabel(tb) })),
  (entries) => {
    const live = new Set(entries.map((e) => e.id));
    for (const [id, timer] of stickyTimers) {
      if (!live.has(id)) {
        window.clearTimeout(timer);
        stickyTimers.delete(id);
        stickyLabels.value.delete(id);
      }
    }
    for (const { id, label } of entries) {
      if (label === stickyLabels.value.get(id)) continue;
      if (label === "") {
        // cleared state: drop immediately (running needs no residue)
        window.clearTimeout(stickyTimers.get(id));
        stickyTimers.delete(id);
        stickyLabels.value.delete(id);
      } else if (!stickyTimers.has(id)) {
        const timer = window.setTimeout(() => {
          stickyTimers.delete(id);
          const tb = store.tabs.find((x) => x.tabId === id);
          const current = tb ? stateLabel(tb) : "";
          if (current) stickyLabels.value.set(id, current);
        }, STICKY_LABEL_DELAY);
        stickyTimers.set(id, timer);
      }
    }
  },
  { deep: false, immediate: true },
);

onBeforeUnmount(() => {
  for (const timer of stickyTimers.values()) window.clearTimeout(timer);
  stickyTimers.clear();
});

function canClose(s: TabSessionState): boolean {
  // guide/dormant tabs have no session to terminate but must stay
  // removable (×) — closing a dormant placeholder only touches history
  // (runtime-lifecycle-ux 01 §4.2.5).
  return (
    s === "starting" || s === "running" || s === "closing" ||
    s === "guide" || s === "dormant"
  );
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
    <!-- 10e: tab motion — fade-in enter, out-of-flow leave so siblings FLIP at once. -->
    <TransitionGroup tag="div" class="tab-group" name="tab-anim">
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
        <span v-if="stickyLabels.get(tab.tabId)" class="state">{{ stickyLabels.get(tab.tabId) }}</span>
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
    </TransitionGroup>

    <!-- IDEA-1 + Stage 8e: virtual session-less tabs (Settings, cc-switch
         Provider UI). Keyboard model: appended after the session tabs. -->
    <TransitionGroup tag="div" class="tab-group" name="tab-anim">
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
          @click="closeCcSwitchUi()"
        >×</button>
      </span>
    </div>
    </TransitionGroup>

    <!-- G-08 + IDEA-1: + split button. Main + creates the DEFAULT agent tab
         (ui.default_tab_agent) immediately; ▾ opens the full menu (any agent
         duplicates allowed — cap enforced by the store — plus the Provider
         page). The menu
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
        <Transition name="pop">
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
            data-agent="cc-switch-ui"
            @click="chooseCcSwitchUi"
          >{{ t("tabbar.ccSwitchUi") }}</li>
        </ul>
        </Transition>
      </Teleport>
    </div>
  </div>
</template>

<style scoped>
.tabbar {
  position: relative; /* 10e: tab-anim leave anchors here (position:absolute) */
  display: flex;
  align-items: center;
  align-items: center;
  gap: 2px;
  padding: 3px 6px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  /* UX-02: many tabs at a narrow tier scroll instead of squishing */
  overflow-x: auto;
  scrollbar-width: thin;
}
/* 10c: pill tabs (D10-14) — the Stage 6 underline treatment gives way to
 * rounded fills; min-height doubles the hit area (baseline B-04). */
.tab-group { display: flex; align-items: center; gap: 2px; min-width: 0; }
.tab {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: var(--control-h-md);
  padding: 0 6px 0 12px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  flex-shrink: 0; /* UX-02: keep tab content, let the bar scroll */
  white-space: nowrap;
  /* opacity/transform ride the BASE rule: scoped `.tab[data-v]` specificity
   * (0,2,0) out-cases the global motion classes (0,1,0) — a transition on
   * .tab-anim-enter-active alone never applied (10e r3 root cause).
   * background/color deliberately NOT transitioned (10e r7): the active
   * highlight hand-off between tabs cross-faded for 200ms — two accent pills
   * coexisting read as a smeared moving blob (user feedback). State changes
   * snap; only real motion animates. */
  transition: opacity var(--duration-slow) var(--ease-pop),
    transform var(--duration-slow) var(--ease-pop);
}
.tab:hover { background: var(--surface-hover); color: var(--text-2); }
.tab.active { background: var(--accent-soft); color: var(--text); }
.tab-main {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-size: var(--font-base);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab-main:focus-visible,
.icon:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
.tab .title {
  font-weight: 500;
  max-width: 18ch; /* B-02: long workspace names must not eat the bar */
  overflow: hidden;
  text-overflow: ellipsis;
}
.tab .state { font-size: var(--font-xs); color: var(--text-muted); }
.tab.idle { color: var(--text-faint); }
.tab.dormant { color: var(--text-faint); font-style: italic; }
.tab.starting .state, .tab.closing .state { color: var(--warn); }
.tab.exited .state { color: var(--text-muted); }
.tab.failed .state { color: var(--error); }
.tab.disconnected .state { color: var(--warn); }
.actions { display: flex; gap: 2px; margin-left: 2px; }
.icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  background: transparent;
  border: none;
  color: inherit;
  padding: 0 4px;
  font-size: var(--font-base);
  line-height: 1;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
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
