<script setup lang="ts">
/**
 * IDEA-3 (3c): ONE workspace's view — the instance state chain (picker →
 * summary → starting → building → conflict → error → ready) plus the ready
 * workspace's internals (sidebar, TabBar, PaneTrees, virtual panes, explorer
 * drawer) moved out of App.vue.
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

const showExplorer = ref(true);

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
      <RuntimeSidebar />
      <button
        class="explorer-toggle"
        :title="t('explorer.tab.files')"
        :aria-pressed="showExplorer"
        @click="showExplorer = !showExplorer"
      >
        ☰
      </button>
      <div class="main">
        <TabBar />
        <main class="terminal-area">
          <div v-if="store.tabs.length === 0 && !ccSwitchPaneVisible" class="empty-tabs">
            <p>{{ t("tabs.empty") }}</p>
            <button class="primary" @click="store.createTab('bash')">{{ t("tabs.newTab") }}</button>
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
            <CcSwitchUiTab />
          </div>
        </main>
      </div>
      <div v-show="showExplorer" class="explorer-drawer">
        <WorkspaceExplorer />
      </div>
    </div>

    <!-- Instance error gate -->
    <div v-else-if="store.status === 'error'" class="gate error">
      <h2>{{ t("app.error.title") }}</h2>
      <p class="err">{{ store.error?.message }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <div class="actions">
        <button @click="store.negotiate()">{{ t("app.error.retry") }}</button>
        <button @click="store.backToPicker()">{{ t("app.error.back") }}</button>
        <button class="diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
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
.explorer-toggle {
  align-self: flex-start;
  margin-top: 4px;
  padding: 4px 6px;
  background: var(--surface-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-2);
  cursor: pointer;
  font-size: var(--font-sm);
}
.explorer-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  max-width: 100%;
  z-index: var(--z-drawer);
  display: flex;
  background: var(--surface);
  border-left: 1px solid var(--border-strong);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.25);
}
.explorer-drawer > * { flex: 1; min-height: 0; min-width: 0; }
.empty-tabs {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px; color: var(--text-muted); font-size: var(--font-md);
}
</style>
