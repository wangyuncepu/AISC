<script setup lang="ts">
/**
 * IDEA-3 (3c): ONE workspace's view — the instance state chain (picker →
 * summary → starting → building → conflict → error → ready) plus the ready
 * workspace's internals (explorer dock, TabBar, PaneTrees, virtual panes,
 * status drawer) moved out of App.vue. 2026-08-18 样式对调: the Explorer is
 * the resident LEFT dock; the runtime status info lives in a right floating
 * drawer (default collapsed, weak ⓘ toggle).
 *
 * Mounts ONLY for the ACTIVE workspace instance (App keys it by instance id
 * so switching remounts). All existing ready-view components stay
 * facade-bound (`useRuntimeStore()` = the active workspace) — remounting is
 * safe by design: Terminal is a pure view over the store-owned stream
 * buffers (S1.3), so a switch preserves scrollback and never re-opens
 * sessions; background workspaces keep buffering through their own channels.
 *
 * The global keyboard handler (pane nav + Ctrl+Tab/Ctrl+1..9) moved here:
 * these are session-layer concerns of the READY view; App keeps only the
 * window-level machinery. One WorkspaceView is mounted at a time, so one
 * capture listener exists at a time.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { leafCount } from "../../stores/paneTree";
import { CC_SWITCH_UI_TAB_ID, useRuntimeStore } from "../../stores/runtime";
import { useDoctorStore } from "../../stores/doctor";
import { useWorkspaceExplorerStore } from "../../stores/workspaceExplorer";
import {
  EXPLORER_COLLAPSED_W,
  appScale,
  panelLayout,
  railIconAction,
  setExplorerCollapsed,
  setExplorerWidth,
  setTabbarHeight,
} from "../../lib/panelLayout";
import type { LayoutTier } from "../../lib/layout";
import PaneTree from "../terminal/PaneTree.vue";
import TabBar from "./TabBar.vue";
import RuntimeSidebar from "./RuntimeSidebar.vue";
import WorkspacePicker from "../startup/WorkspacePicker.vue";
import LaunchSummary from "../startup/LaunchSummary.vue";
import StartProgress from "../startup/StartProgress.vue";
import BuildProgress from "../startup/BuildProgress.vue";
import ConflictManager from "../startup/ConflictManager.vue";
import CcSwitchUiTab from "../ccswitch/CcSwitchUiTab.vue";
import WorkspaceExplorer from "../workspace-explorer/WorkspaceExplorer.vue";

const props = defineProps<{
  /** Terminal counter-zoom style (App owns the zoom machinery, G-11). */
  zoom: Record<string, string>;
  /** Layout tier (FIX-3): compact hands the dock width to the responsive
   * CSS rule (no inline width); standard/wide honor the user's dragged value. */
  tier: LayoutTier;
}>();

const { t } = useI18n();
const store = useRuntimeStore();
const doctorStore = useDoctorStore();
const explorerStore = useWorkspaceExplorerStore();

// --- P2-3 (D-4): the collapsed rail is a real activity bar now ------------
/** One icon per side view; services only when the runtime advertises it
 * (same gate WorkspaceExplorer's tab uses). Click = VS Code semantics via
 * railIconAction (expand+land / toggle-collapse / plain switch). */
const servicesSupported = computed(() => store.capability?.runtime_services ?? false);
const RAIL_ITEMS = [
  { kind: "explorer", labelKey: "explorer.tab.files", icon: "folder" },
  { kind: "conversations", labelKey: "explorer.tab.conversations", icon: "clock" },
  { kind: "artifacts", labelKey: "explorer.tab.artifacts", icon: "box" },
  { kind: "services", labelKey: "explorer.tab.services", icon: "globe" },
] as const;
function onRailIcon(kind: string): void {
  const action = railIconAction(
    panelLayout.explorerCollapsed, explorerStore.activeKind, kind,
  );
  if (action.do === "collapse") {
    setExplorerCollapsed(true);
    return;
  }
  // P2-4: activation side effects centralized in the store's activateView
  // (conversations rescan / services refresh) — shared with the palette.
  explorerStore.activateView(action.kind as typeof explorerStore.activeKind);
  if (action.do === "expand") setExplorerCollapsed(false);
}

/** 2026-08-18 用户决策（样式对调）：资源管理器/产物框固定常驻左侧（原
 * RuntimeSidebar 的固定列样式，无开关），状态信息栏变右侧悬浮抽屉
 * （原资源管理器抽屉样式）——默认收起，右缘弱化 ⓘ 开关 + 抽屉内 ✕ 关闭。 */
const showStatus = ref(false);
/** 10e (B-07): Escape-close returns focus here (opener restore). */
const drawerToggleRef = ref<HTMLButtonElement | null>(null);

// --- FIX-3: Explorer dock geometry (drag-to-resize + VS Code-style collapse) ---
/** Inline width source of truth. P2-3: the 40px activity rail is PERMANENT —
 * the dock is [rail 40px] + [panel explorerWidth]; collapsed = rail only.
 * min-width moves along (the scoped `min-width:240px` floor would otherwise
 * push the rail back open, audit (g)); compact ⇒ undefined so the responsive
 * scoped rule owns the width (audit (d) — the old App.vue override was a
 * dead rule). */
const dockStyle = computed<Record<string, string> | undefined>(() => {
  if (panelLayout.explorerCollapsed) {
    return { width: `${EXPLORER_COLLAPSED_W}px`, minWidth: `${EXPLORER_COLLAPSED_W}px` };
  }
  if (props.tier === "compact") return undefined;
  const w = `${EXPLORER_COLLAPSED_W + panelLayout.explorerWidth}px`;
  return { width: w, minWidth: w };
});
/** Width transition rides ONLY on collapse/expand — during a drag the dock
 * must track the pointer instantly (a live 300ms ease would lag behind the
 * cursor forever, audit (a)). */
const dockAnimating = ref(true);
function withInstantDock(fn: () => void): void {
  dockAnimating.value = false;
  fn();
  requestAnimationFrame(() => { dockAnimating.value = true; });
}
function onDockHandleDown(e: PointerEvent): void {
  if (e.button !== 0) return;
  e.preventDefault(); // keep text selection out; also swallows default focus
  (e.currentTarget as HTMLElement).focus(); // restore it for keyboard nudging
  const startX = e.clientX;
  const startW = panelLayout.explorerWidth;
  const scale = appScale(); // snapshot: visual px → layout px
  dockAnimating.value = false;
  const move = (ev: PointerEvent) => {
    // Incremental, zero-rect (engine-neutral under zoom, audit (b))
    setExplorerWidth(startW + (ev.clientX - startX) / scale);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    dockAnimating.value = true;
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
function onDockHandleKey(e: KeyboardEvent): void {
  const step = 8;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    withInstantDock(() => setExplorerWidth(panelLayout.explorerWidth - step));
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    withInstantDock(() => setExplorerWidth(panelLayout.explorerWidth + step));
  }
}

// --- FIX-3: TabBar ↔ terminal-area horizontal divider (drag = resize the
// tab row, i.e. the terminal's share of the column). ---
const tabbarRef = ref<{ $el?: HTMLElement } | null>(null);
const tabbarStyle = computed<Record<string, string> | undefined>(() =>
  panelLayout.tabbarHeight != null
    ? { height: `${panelLayout.tabbarHeight}px` }
    : undefined);
function onTabDividerDown(e: PointerEvent): void {
  if (e.button !== 0) return;
  e.preventDefault();
  (e.currentTarget as HTMLElement).focus();
  const startY = e.clientY;
  // offsetHeight is LAYOUT px (zoom-immune, unlike getBoundingClientRect) —
  // null height (never dragged) starts from the measured natural bar height.
  const startH = tabbarRef.value?.$el?.offsetHeight ?? 39;
  const scale = appScale();
  const move = (ev: PointerEvent) => {
    setTabbarHeight(startH + (ev.clientY - startY) / scale);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
function onTabDividerKey(e: KeyboardEvent): void {
  const step = 4;
  if (e.key === "ArrowUp") {
    e.preventDefault();
    setTabbarHeight((panelLayout.tabbarHeight ?? tabbarRef.value?.$el?.offsetHeight ?? 39) - step);
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    setTabbarHeight((panelLayout.tabbarHeight ?? tabbarRef.value?.$el?.offsetHeight ?? 39) + step);
  }
}

// Stage 8e: the cc-switch Provider UI virtual pane — kept alive while hidden
// so unsaved state survives switches. (The Settings pane is workspace-layer
// now — App renders it; see stores/workspaces 3d.)
const ccSwitchPaneRef = ref<HTMLElement | null>(null);
const ccSwitchPaneVisible = computed(
  () => store.ccSwitchUiTabOpen && store.activeTabId === CC_SWITCH_UI_TAB_ID
);

// S3.3: focus the terminal of a tab so typing works right after switching
// (clicks, Ctrl+Tab, Ctrl+1..9). nextTick: the target tab becomes visible
// (v-show) on the next render; focusing synchronously would hit a hidden
// xterm.
function focusTabTerminal(tabId: string): void {
  if (tabId === CC_SWITCH_UI_TAB_ID) {
    void nextTick(() => ccSwitchPaneRef.value?.focus({ preventScroll: true }));
    return;
  }
  // G-17: focus the tab's ACTIVE pane terminal (PaneTree exposes it).
  void nextTick(() => {
    paneTreeRefs.value.get(tabId)?.focusActivePane();
  });
}

/** The rendered tab sequence = session tabs + open virtual chips (TabBar's
 * rendering order; drives Ctrl+Tab / Ctrl+1..9). */
function renderedTabIds(): string[] {
  const ids = store.tabs.map((tb) => tb.tabId);
  if (store.ccSwitchUiTabOpen) ids.push(CC_SWITCH_UI_TAB_ID);
  return ids;
}

function activateRenderedTab(id: string): void {
  if (id === CC_SWITCH_UI_TAB_ID) store.openCcSwitchUiTab();
  else store.activateTab(id);
  focusTabTerminal(id);
}

/** 10e r7 (user feedback): tab CONTENT fades in on switch — the v-show
 * panes stay mounted (buffer-safe design), so a display:none -> block swap
 * can't CSS-transition; orchestrate manually: pin opacity 0, then release on
 * the next frame so the ease runs.
 * B-05 手测十二/十三轮: LIVE terminal panes are excluded — the terminal's
 * resize veil owns their switch motion (a second opacity ramp on top read
 * as flicker). GUIDE/IDLE panes and the settings pane have no veil and keep
 * this fade. */
const terminalAreaRef = ref<HTMLElement | null>(null);
watch(
  () => store.activeTabId,
  (id) => {
    if (!id || store.status !== "ready") return;
    void nextTick(() => {
      const area = terminalAreaRef.value;
      if (!area) return;
      const tb = store.tabs.find((x) => x.tabId === id);
      const st = tb ? tb.panes[tb.activePaneId]?.sessionState : undefined;
      const targets: HTMLElement[] = [];
      if (st === undefined || st === "guide" || st === "idle") {
        // No terminal veil on this pane (guide/idle, or a sentinel tab).
        const wrap = area.querySelector<HTMLElement>(
          `.term-wrap[data-tab="${CSS.escape(id)}"]`,
        );
        if (wrap) targets.push(wrap);
        const settings = area.querySelector<HTMLElement>(".settings-pane");
        if (settings) targets.push(settings);
      }
      for (const wrap of targets) {
        wrap.classList.add("pane-fade-in");
        requestAnimationFrame(() =>
          requestAnimationFrame(() => wrap.classList.remove("pane-fade-in")),
        );
      }
    });
  },
);

// G-08: every activation path moves keyboard focus into the terminal.
watch(
  () => store.activeTabId,
  (id) => {
    if (id && store.status === "ready") focusTabTerminal(id);
  }
);

// G-12: 官方账号登录 / 重试 start the session on the ALREADY active guide
// tab — focus the terminal once it mounts after the guide → starting hop.
watch(
  () => {
    const tb = store.tabs.find((x) => x.tabId === store.activeTabId);
    return tb?.sessionState;
  },
  (st, prev) => {
    if (st === "starting" && prev === "guide" && store.activeTabId) {
      window.setTimeout(() => {
        const id = store.activeTabId;
        if (id) focusTabTerminal(id);
      }, 50);
    }
  }
);

function onKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  const key = e.key.toLowerCase();
  // G-17: pane focus navigation + close, scoped to keys originating inside a
  // pane. Consumed keys never reach the PTY. (WebView2 swallows some
  // browser-reserved combos; Ctrl+arrows and Ctrl+Shift+hjkl are page-safe.)
  if (store.status === "ready" && store.activeTabId) {
    const target = e.target as HTMLElement | null;
    if (target?.closest?.(".pane")) {
      if (e.shiftKey && key === "w") {
        const tb = store.tabs.find((x) => x.tabId === store.activeTabId);
        if (tb && leafCount(tb.tree) > 1) {
          e.preventDefault();
          void store.closePane(store.activeTabId, tb.activePaneId);
        }
        return;
      }
      if (!e.altKey) {
        const arrow = !e.shiftKey && e.key.startsWith("Arrow")
          ? (e.key === "ArrowLeft" ? "left"
            : e.key === "ArrowRight" ? "right"
            : e.key === "ArrowUp" ? "up" : "down")
          : null;
        const letter = e.shiftKey && "hjkl".includes(key)
          ? (key === "h" ? "left"
            : key === "j" ? "down"
            : key === "k" ? "up" : "right")
          : null;
        const dir = arrow ?? letter;
        if (dir && store.navigatePane(store.activeTabId, dir)) {
          e.preventDefault();
          focusTabTerminal(store.activeTabId);
          return;
        }
      }
    }
  }
  // S1.6: Ctrl/Cmd+Tab cycles the rendered sequence (incl. virtual chips).
  if (e.key === "Tab") {
    if (store.status !== "ready") return;
    const ids = renderedTabIds();
    if (ids.length === 0) return;
    e.preventDefault();
    const current = ids.indexOf(store.activeTabId ?? "");
    const dir = e.shiftKey ? -1 : 1;
    const base = current < 0 ? 0 : current;
    activateRenderedTab(ids[(base + dir + ids.length) % ids.length]!);
    return;
  }
  // G-08: Ctrl/Cmd+1..9 map the committed tab order.
  if (e.key >= "1" && e.key <= "9") {
    if (store.status !== "ready") return;
    e.preventDefault();
    const id = renderedTabIds()[Number(e.key) - 1];
    if (id) activateRenderedTab(id);
  } else if (e.key === "Enter" && store.status === "summary") {
    // Manual-test r4 #1: Enter must respect the same hard-blocking gate as
    // the (disabled) launch button — a moved workspace folder used to launch
    // straight through this shortcut and docker silently recreated the old
    // path as an empty dir. startFromSummary now self-guards; the early
    // return here keeps preventDefault from eating the keystroke pointlessly.
    if (!store.startEnabled) return;
    e.preventDefault();
    store.startFromSummary();
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown, { capture: true }));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown, { capture: true }));

// 10e (B-07): Escape closes the status drawer — the ghost ⓘ toggle and the
// header ✕ were the only close paths; keyboard users had none.
function onDrawerEscape(e: KeyboardEvent): void {
  if (e.key === "Escape" && showStatus.value) {
    e.preventDefault();
    showStatus.value = false;
    drawerToggleRef.value?.focus();
  }
}
onMounted(() => window.addEventListener("keydown", onDrawerEscape));
onBeforeUnmount(() => window.removeEventListener("keydown", onDrawerEscape));

function isStartingView(s: string): boolean {
  return s === "starting" || s === "cancelled";
}

// G-17: every tab renders its PaneTree; v-show keeps hidden tabs (and their
// PTYs) alive within THIS workspace so tab switching preserves scrollback.
const paneTabs = computed(() => store.tabs);

const paneTreeRefs = ref(new Map<string, InstanceType<typeof PaneTree>>());
function setPaneTreeRef(tabId: string) {
  return (el: unknown) => {
    if (el) paneTreeRefs.value.set(tabId, el as InstanceType<typeof PaneTree>);
    else paneTreeRefs.value.delete(tabId);
  };
}
</script>

<template>
  <div class="view">
    <!-- Preflight / stopping (instance-level centers) -->
    <div v-if="['preflight', 'stopping'].includes(store.status)" class="center">
      <p class="msg">{{
        store.status === "stopping"
          ? t("app.stopping")
          : t("app.preflight")
      }}</p>
    </div>

    <!-- Workspace picker (launcher flow) -->
    <WorkspacePicker v-else-if="store.status === 'picker'" />

    <!-- Launch summary / start progress / build / conflict -->
    <div v-else-if="store.status === 'summary'" class="main">
      <LaunchSummary />
    </div>
    <div v-else-if="isStartingView(store.status)" class="main">
      <StartProgress />
    </div>
    <div v-else-if="store.status === 'building'" class="main">
      <BuildProgress />
    </div>
    <div v-else-if="store.status === 'conflict'" class="main">
      <ConflictManager />
    </div>

    <!-- Terminal workspace -->
    <div v-else-if="store.status === 'ready'" class="ready" :class="{ 'tier-compact': props.tier === 'compact' }">
      <!-- FIX-3: resizable + collapsible left dock (2026-08-18 样式对调 kept:
           Explorer resident on the left; now with drag handle + rail collapse) -->
      <div
        class="explorer-dock"
        :class="{ collapsed: panelLayout.explorerCollapsed, anim: dockAnimating }"
        :style="dockStyle"
      >
        <!-- P2-3 (D-4): the FIX-3 single-« rail is now a PERMANENT ACTIVITY
             BAR — LEFTMOST, VS Code-style (手测 r1: born on the wrong side).
             One icon per side view; click = expand+land / toggle-collapse /
             switch (VS Code semantics); the active view's icon carries the
             accent + left bar. Ctrl+B toggles the panel globally (App.vue). -->
        <nav
          class="explorer-rail"
          :aria-label="t('explorer.railLabel')"
        >
          <template v-for="item in RAIL_ITEMS" :key="item.kind">
            <button
              v-if="item.kind !== 'services' || servicesSupported"
              type="button"
              class="rail-icon"
              :class="{
                active: !panelLayout.explorerCollapsed
                  && explorerStore.activeKind === item.kind,
              }"
              :title="t(item.labelKey)"
              :aria-label="t(item.labelKey)"
              @click="onRailIcon(item.kind)"
            >
              <svg v-if="item.icon === 'folder'" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                <path d="M1.5 4.5A1.5 1.5 0 0 1 3 3h3l1.5 2H13a1.5 1.5 0 0 1 1.5 1.5v6A1.5 1.5 0 0 1 13 14H3a1.5 1.5 0 0 1-1.5-1.5z" />
              </svg>
              <svg v-else-if="item.icon === 'clock'" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                <circle cx="8" cy="8" r="6" />
                <path d="M8 4.5V8l2.5 1.5" />
              </svg>
              <svg v-else-if="item.icon === 'box'" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                <path d="M2 5l6-3 6 3v6l-6 3-6-3z" />
                <path d="M2 5l6 3 6-3M8 8v6" />
              </svg>
              <svg v-else width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                <circle cx="8" cy="8" r="6" />
                <path d="M2.5 6h11M2.5 10h11M8 2c-2 1.7-3 3.7-3 6s1 4.3 3 6c2-1.7 3-3.7 3-6s-1-4.3-3-6z" />
              </svg>
            </button>
          </template>
        </nav>
        <!-- v-show on purpose (audit (c)): remount would drop in-flight
             search/rename state and the tree's scroll position. -->
        <div v-show="!panelLayout.explorerCollapsed" class="explorer-panel">
          <WorkspaceExplorer />
        </div>
      </div>
      <!-- Drag handle: hidden when collapsed (rail must expand first) and in
           compact (the responsive rule owns the width — a dead handle would
           mislead, audit (j)). -->
      <div
        v-if="!panelLayout.explorerCollapsed && props.tier !== 'compact'"
        class="dock-handle"
        role="separator"
        aria-orientation="vertical"
        :aria-label="t('explorer.resizeHandle')"
        :title="t('explorer.resizeHandle')"
        tabindex="0"
        @pointerdown="onDockHandleDown"
        @keydown="onDockHandleKey"
        @dblclick="setExplorerCollapsed(true)"
      ></div>
      <div class="main">
        <TabBar ref="tabbarRef" :style="tabbarStyle" />
        <!-- FIX-3: drag to resize the tab row / terminal split (the divider
             takes over the bar's old bottom border as the visual edge). -->
        <div
          class="tab-divider"
          role="separator"
          aria-orientation="horizontal"
          :aria-label="t('explorer.tabbarResize')"
          :title="t('explorer.tabbarResize')"
          tabindex="0"
          @pointerdown="onTabDividerDown"
          @keydown="onTabDividerKey"
        ></div>
        <main ref="terminalAreaRef" class="terminal-area">
          <div v-if="store.tabs.length === 0 && !ccSwitchPaneVisible" class="empty-tabs">
            <p>{{ t("tabs.empty") }}</p>
            <button class="ui-button primary" @click="store.createTab('bash')">{{ t("tabs.newTab") }}</button>
          </div>
          <div
            v-for="tb in paneTabs"
            :key="tb.tabId"
            :data-tab="tb.tabId"
            class="term-wrap"
            :style="props.zoom"
            v-show="tb.tabId === store.activeTabId"
          >
            <PaneTree :ref="setPaneTreeRef(tb.tabId)" :tab-id="tb.tabId" :tree="tb.tree" />
          </div>
          <div
            v-if="store.ccSwitchUiTabOpen"
            v-show="ccSwitchPaneVisible"
            ref="ccSwitchPaneRef"
            class="settings-pane"
            tabindex="-1"
          >
            <!-- KI-7②: `visible` lets the pane refetch when the user returns
                 from a bash tab — the pane is kept alive (v-show), so mounts
                 never re-run and external cc-switch edits stayed invisible. -->
            <CcSwitchUiTab :visible="ccSwitchPaneVisible" />
          </div>
        </main>
      </div>
      <!-- 弱化开关：右缘幽灵 ⓘ（抽屉打开时被抽屉覆盖，经抽屉内 ✕ 关闭） -->
      <button
        ref="drawerToggleRef"
        class="status-toggle"
        :title="t('sidebar.drawerOpen')"
        :aria-label="t('sidebar.drawerOpen')"
        :aria-pressed="showStatus"
        @click="showStatus = true"
      >
        ⓘ
      </button>
      <!-- 状态信息栏：右侧悬浮抽屉（原资源管理器抽屉样式），默认收起 -->
      <!-- 10e: unified slide-right motion (D10-09). -->
      <Transition name="slide-right">
      <div v-show="showStatus" class="status-drawer">
        <div class="status-head">
          <span>{{ t("sidebar.drawerTitle") }}</span>
          <button
            class="status-close"
            :title="t('sidebar.drawerClose')"
            :aria-label="t('sidebar.drawerClose')"
            @click="showStatus = false"
          >
            ✕
          </button>
        </div>
        <RuntimeSidebar />
      </div>
      </Transition>
    </div>

    <!-- Instance error gate -->
    <div v-else-if="store.status === 'error'" class="gate error">
      <h2>{{ t("app.error.title") }}</h2>
      <p class="err">{{ store.error?.message }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <div class="actions">
        <button class="ui-button" @click="store.negotiate()">{{ t("app.error.retry") }}</button>
        <button class="ui-button" @click="store.backToPicker()">{{ t("app.error.back") }}</button>
        <button class="ui-button diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.gate.error, .center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-2);
}
.gate .err { color: var(--text-2); }
.gate .detail { font-size: var(--font-sm); color: var(--text-muted); }
.center .msg { color: var(--text-muted); }
/* B-05: min-width:0 is LOAD-BEARING on both — without it the flex
 * min-width:auto floor makes the terminal column content-sized by the
 * xterm screen, so a shrinking window could only release layout ONE FIT
 * AT A TIME (the 14px-per-150ms staircase squeeze; growing snapped
 * instantly, which is why the two directions behaved differently). */
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.ready { flex: 1; display: flex; min-height: 0; min-width: 0; position: relative; }
.terminal-area { flex: 1; min-height: 0; padding: 4px; background: var(--bg); display: flex; }
.term-wrap { flex: 1; min-height: 0; min-width: 0; }
/* 10e: content fade on tab switch (opacity only — D10-09). Applied to
 * guide/idle panes and the settings pane only (B-05 手测十二轮): live
 * terminal panes are faded by the terminal's own resize veil instead. */
.term-wrap, .settings-pane { transition: opacity var(--duration-normal) var(--ease); }
.term-wrap.pane-fade-in, .settings-pane.pane-fade-in { opacity: 0; }
.settings-pane { flex: 1; min-height: 0; min-width: 0; display: flex; outline: none; }
/* 2026-08-18 样式对调：Explorer 固定停靠左列（原 RuntimeSidebar 的 dock 样式）
 * FIX-3: width comes from the inline dockStyle (user value) or, in compact,
 * the responsive rule below — the 320px here is only the no-JS fallback. */
.explorer-dock {
  width: 320px;
  min-width: 240px;
  flex-shrink: 0;
  display: flex;
  background: var(--surface);
}
/* P2-3: the dock is [40px activity rail][panel]. */
.explorer-panel { flex: 1; min-width: 0; }
/* Collapse/expand animation (audit (a)): the terminal's 150ms settle-once
 * debounce rides out the 300ms transition and fits exactly once at the end.
 * Global reduced-motion collapses this to nothing (styles.css). */
.explorer-dock.anim {
  transition: width var(--duration-slow) var(--ease),
    min-width var(--duration-slow) var(--ease);
}
.explorer-dock > * { flex: 1; min-height: 0; min-width: 0; }
/* FIX-3 compact tier — responsive dock width (migrated from App.vue where
 * the scoped rule never matched, audit (d)). */
.tier-compact .explorer-dock:not(.collapsed) { width: min(280px, 45%); min-width: 200px; }
.tier-compact .status-drawer { width: min(300px, 100%); }
/* FIX-3: collapsed rail — the dock's right edge IS the border; the handle
 * is hidden while collapsed. */
.explorer-dock.collapsed { border-right: var(--border-w) solid var(--border); }
.explorer-dock:not(.collapsed) { border-right: none; }
/* P2-3 (D-4): the collapsed rail as an activity bar — vertical icon stack
 * (VS Code language: quiet glyphs, hover lift, active = accent + left bar). */
.explorer-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  /* 40px = EXPLORER_COLLAPSED_W (panelLayout.ts). FIXED, flex-none — the
   * old single-button rail used width:100% (= the 40px dock); as a direct
   * dock child that would grab container width and squeeze the panel
   * (手测 r1: misaligned hover rect, panel/rail split). */
  width: 40px;
  flex: none;
  padding: var(--space-2) 0;
  border-right: var(--border-w) solid var(--border);
  box-sizing: border-box;
}
.rail-icon {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-faint);
  cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.rail-icon:hover { background: var(--surface-hover); color: var(--text); }
.rail-icon:focus-visible { outline: var(--focus) solid var(--focus-ring-width); outline-offset: -2px; }
/* Active view: accent glyph + VS Code's left activity indicator bar. Only
 * meaningful while the dock is OPEN (the rail is hidden then, but the class
 * stays correct for the moment of expansion). */
.rail-icon.active { color: var(--accent); }
.rail-icon.active::before {
  content: "";
  position: absolute;
  left: -4px;
  top: 4px;
  bottom: 4px;
  width: 2px;
  border-radius: 1px;
  background: var(--accent);
}
.explorer-rail:hover { background: var(--surface-hover); color: var(--text-2); }
.explorer-rail:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
/* FIX-3: drag handle (PaneTree divider visual recipe) */
.dock-handle {
  flex-shrink: 0;
  width: 6px;
  cursor: col-resize;
  background: transparent;
  touch-action: none; /* pointer drag owns the gesture */
  display: flex;
  align-items: center;
  justify-content: center;
}
.dock-handle::after {
  content: "";
  width: 2px;
  height: 24px;
  border-radius: var(--radius-sm);
  background: var(--border-2);
  transition: background-color var(--duration-normal) var(--ease);
}
.dock-handle:hover::after, .dock-handle:focus-visible::after { background: var(--accent); }
.dock-handle:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: -2px;
}
/* FIX-3: TabBar↔terminal horizontal divider (mirrors the dock handle) */
.tab-divider {
  flex-shrink: 0;
  height: 6px;
  cursor: row-resize;
  background: transparent;
  touch-action: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
.tab-divider::after {
  content: "";
  width: 24px;
  height: 2px;
  border-radius: var(--radius-sm);
  background: var(--border-2);
  transition: background-color var(--duration-normal) var(--ease);
}
.tab-divider:hover::after, .tab-divider:focus-visible::after { background: var(--accent); }
.tab-divider:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: -2px;
}
/* 右缘弱化开关：幽灵样式，hover 才浮出 */
.status-toggle {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  margin-top: var(--space-1);
  padding: var(--space-1) var(--space-2);
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-faint);
  cursor: pointer;
  font-size: var(--font-md);
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.status-toggle:hover { background: var(--surface-hover); color: var(--text-2); }
.status-toggle:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
/* 状态信息栏：右侧悬浮抽屉（原资源管理器抽屉的浮层样式） */
.status-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 300px;
  max-width: 100%;
  z-index: var(--z-drawer);
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  border-left: var(--border-w) solid var(--border-2);
  box-shadow: var(--shadow-2);
}
.status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
  border-bottom: var(--border-w) solid var(--border);
  color: var(--text-faint);
  font-size: var(--font-xs);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.status-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  min-height: 20px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--font-sm);
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
.status-close:hover { background: var(--surface-hover); color: var(--text); }
.status-close:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
.empty-tabs {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px; color: var(--text-muted); font-size: var(--font-md);
}
</style>
