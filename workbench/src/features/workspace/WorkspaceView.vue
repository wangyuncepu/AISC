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
}>();

const { t } = useI18n();
const store = useRuntimeStore();
const doctorStore = useDoctorStore();

/** 2026-08-18 用户决策（样式对调）：资源管理器/产物框固定常驻左侧（原
 * RuntimeSidebar 的固定列样式，无开关），状态信息栏变右侧悬浮抽屉
 * （原资源管理器抽屉样式）——默认收起，右缘弱化 ⓘ 开关 + 抽屉内 ✕ 关闭。 */
const showStatus = ref(false);

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
    e.preventDefault();
    store.startFromSummary();
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown, { capture: true }));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown, { capture: true }));

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
    <div v-else-if="store.status === 'ready'" class="ready">
      <!-- 2026-08-18 样式对调：Explorer 固定常驻左侧（dock，无开关） -->
      <div class="explorer-dock">
        <WorkspaceExplorer />
      </div>
      <div class="main">
        <TabBar />
        <main class="terminal-area">
          <div v-if="store.tabs.length === 0 && !ccSwitchPaneVisible" class="empty-tabs">
            <p>{{ t("tabs.empty") }}</p>
            <button class="ui-button primary" @click="store.createTab('bash')">{{ t("tabs.newTab") }}</button>
          </div>
          <div
            v-for="tb in paneTabs"
            :key="tb.tabId"
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
        class="status-toggle"
        :title="t('sidebar.drawerOpen')"
        :aria-label="t('sidebar.drawerOpen')"
        :aria-pressed="showStatus"
        @click="showStatus = true"
      >
        ⓘ
      </button>
      <!-- 状态信息栏：右侧悬浮抽屉（原资源管理器抽屉样式），默认收起 -->
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
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.ready { flex: 1; display: flex; min-height: 0; position: relative; }
.terminal-area { flex: 1; min-height: 0; padding: 4px; background: var(--bg); display: flex; }
.term-wrap { flex: 1; min-height: 0; min-width: 0; }
.settings-pane { flex: 1; min-height: 0; min-width: 0; display: flex; outline: none; }
/* 2026-08-18 样式对调：Explorer 固定停靠左列（原 RuntimeSidebar 的 dock 样式） */
.explorer-dock {
  width: 320px;
  min-width: 240px;
  flex-shrink: 0;
  display: flex;
  background: var(--surface);
  border-right: var(--border-w) solid var(--border);
}
.explorer-dock > * { flex: 1; min-height: 0; min-width: 0; }
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
