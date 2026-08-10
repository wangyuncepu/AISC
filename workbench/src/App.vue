<script setup lang="ts">
/**
 * S2.1.a startup shell: routes between startup-state views (02 §三) and the
 * terminal workspace. Capability gate on mount.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { getCurrentWindow } from "@tauri-apps/api/window";
import * as ipc from "./lib/ipc";
import { applyLocale } from "./i18n";
import { computeWindowTitle } from "./lib/title";
import { useRuntimeStore } from "./stores/runtime";
import { useSettingsStore } from "./stores/settings";
import { useDoctorStore } from "./stores/doctor";
import { useRuntimePolling } from "./composables/useRuntimePolling";
import { useProviderPolling } from "./composables/useProviderPolling";
import Terminal from "./features/terminal/Terminal.vue";
import GuidePane from "./features/terminal/GuidePane.vue";
import TabBar from "./features/workspace/TabBar.vue";
import RuntimeSidebar from "./features/workspace/RuntimeSidebar.vue";
import LaunchSummary from "./features/startup/LaunchSummary.vue";
import StartProgress from "./features/startup/StartProgress.vue";
import BuildProgress from "./features/startup/BuildProgress.vue";
import ConflictManager from "./features/startup/ConflictManager.vue";
import SettingsDialog from "./features/settings/SettingsDialog.vue";
import DoctorDialog from "./features/doctor/DoctorDialog.vue";

const { t } = useI18n();
const store = useRuntimeStore();
const settingsStore = useSettingsStore();
const doctorStore = useDoctorStore();
const polling = useRuntimePolling();
const providerPolling = useProviderPolling();

// Step 3: settings dialog entry (keyboard-reachable topbar button).
const settingsOpen = ref(false);

// G-01 (Step 7, A-G01-3): ui.font_scale is immediate-effect. Applied as CSS
// zoom on the UI chrome (topbar/picker/summary/sidebar/tabbar/dialog); the
// terminal area is counter-zoomed so xterm stays 1:1 (its own font settings
// govern terminal text). Backend default 1.0 when settings are not loaded.
const uiScale = computed(() => settingsStore.doc?.ui.font_scale ?? 1);
// The effective scale adapts to the window (user request 2026-08-10): the
// chosen value applies only up to what fits the current window - the design
// baseline is the 800x600 default window, so a non-maximized window at 1.5
// never clips (max fit = min(w/800, h/600)). Resizes update the cap live.
const windowSize = ref({ w: window.innerWidth, h: window.innerHeight });
// G-10: debounced geometry capture (300ms, A-G10-5).
let geometryTimer: number | null = null;
function onViewportResize() {
  windowSize.value = { w: window.innerWidth, h: window.innerHeight };
  if (geometryTimer !== null) window.clearTimeout(geometryTimer);
  geometryTimer = window.setTimeout(() => {
    geometryTimer = null;
    void ipc.captureWindowGeometry().catch(() => undefined);
  }, 300);
}
onMounted(() => window.addEventListener("resize", onViewportResize));
const effectiveScale = computed(() =>
  Math.min(uiScale.value, 1.5, windowSize.value.w / 800, windowSize.value.h / 600)
);
// Zoom scales layout too, so the app box must compensate its height/width
// (calc(100vh/scale) zoomed = 100vh) or the content shrinks away from the
// window edges at scale < 1 (observed 2026-08-10: sidebar buttons and the
// terminal area lifted off the bottom edge).
const uiZoom = computed(() => ({
  zoom: String(effectiveScale.value),
  height: `calc(100vh / ${effectiveScale.value})`,
  width: `calc(100vw / ${effectiveScale.value})`,
}));
const terminalZoom = computed(() => ({ zoom: String(1 / effectiveScale.value) }));
// G-11 (2026-08-10): the counter-zoom keeps the terminal visually 1:1 when
// the UI scale changes, preventing the canvas re-fit flicker observed when it
// was removed (real-time font_scale preview flickered). The terminal FILLS
// the terminal-area because .terminal-area is display:flex (term-wrap flex:1
// stretches) and the counter-zoom is 1 at the default scale (1.0). At
// font_scale > 1 the terminal occupies 1/scale of the area by design (it
// stays 1:1 while the chrome grows); terminal.font_size governs text.

// S3.3: aria-live regions (04 §九 - announce semantic changes only, never
// routine polls). Throttled ~1s so a burst of updates coalesces to the latest.
const livePolite = ref("");
const liveAlert = ref("");
let announceTimer: number | null = null;
let pendingAnnounce = "";

function announce(text: string, alert = false) {
  pendingAnnounce = text;
  if (announceTimer !== null) return; // coalesce into the pending tick
  announceTimer = window.setTimeout(() => {
    announceTimer = null;
    const msg = pendingAnnounce;
    pendingAnnounce = "";
    if (alert) liveAlert.value = "";
    liveAlert.value = alert ? msg : liveAlert.value;
    livePolite.value = alert ? livePolite.value : msg;
  }, 1000);
}

const RUNTIME_LABEL_KEY: Record<string, string> = {
  running: "app.running",
  stopped: "app.stopped",
  not_found: "app.notFound",
  unknown: "app.unknown",
  starting: "app.starting",
  stopping: "app.stopping",
  removing: "app.removing",
};

// Announce runtime-state transitions (not every poll - only when the state
// value actually changes).
let lastAnnouncedState: string | null = null;
watch(
  () => store.runtimeState,
  (s) => {
    if (s !== lastAnnouncedState && store.status === "ready") {
      lastAnnouncedState = s;
      announce(`Runtime ${t(RUNTIME_LABEL_KEY[s] ?? s)}`);
    }
  }
);

watch(
  () => store.error?.message,
  (m) => {
    if (m) announce(m, true);
  }
);

// S3.3: focus the terminal of a tab (xterm's own focus) so typing works right
// after switching via Ctrl/Cmd+1..4. nextTick: the target tab becomes visible
// (v-show) on the next render; focusing synchronously would hit a hidden xterm.
function focusTabTerminal(tabId: string): void {
  void nextTick(() => {
    terminalRefs.value.get(tabId)?.focus();
  });
}

// G-08 (2026-08-10): every activation path (click, + menu, empty-state
// button, restore, shortcuts) moves keyboard focus into the terminal - a
// freshly created tab must be typeable without an extra click.
watch(
  () => store.activeTabId,
  (id) => {
    if (id && store.status === "ready") focusTabTerminal(id);
  }
);

// G-15 (Step 14): dynamic window title, driven by the active context (workspace
// + active tab session type), never by a polling ticker (F-5). The pure
// computeWindowTitle is re-derived whenever workspace / activeTabId / the active
// tab's session state changes; setTitle failure only logs (A-G15-3).
const activeTabTitleContext = computed(() => {
  const tab = store.tabs.find((t) => t.tabId === store.activeTabId) ?? null;
  const sessionType = tab && tab.sessionState !== "idle" ? tab.agent : null;
  return computeWindowTitle({ workspace: store.workspace, sessionType });
});
watch(
  activeTabTitleContext,
  (title) => {
    getCurrentWindow()
      .setTitle(title)
      .catch((e) => console.warn("setTitle failed:", e));
  },
  { immediate: true }
);

// G-12 (2026-08-10): 官方账号登录 / 重试 start the session on the ALREADY
// active guide tab - activeTabId does not change, so focus the terminal once
// it mounts after the guide -> starting transition.
watch(
  () => {
    const t = store.tabs.find((x) => x.tabId === store.activeTabId);
    return t?.sessionState;
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
  // G-08 (A-G08-6): Ctrl/Cmd+1..9 map the current committed tab order; the
  // 10th tab and beyond use the tablist arrow/Home/End navigation.
  if (e.key >= "1" && e.key <= "9") {
    if (store.status !== "ready") return;
    e.preventDefault();
    const tab = store.tabs[Number(e.key) - 1];
    if (tab) {
      store.activateTab(tab.tabId);
      focusTabTerminal(tab.tabId);
    }
  } else if (e.key === "Enter" && store.status === "summary") {
    e.preventDefault();
    store.startFromSummary();
  }
}

onMounted(() => {
  store.negotiate();
  // G-09 (02 §3.1): resolve + apply the locale in parallel with capability
  // negotiation - language resolution never blocks it.
  void (async () => {
    if (!settingsStore.loaded) await settingsStore.load();
    const locale = await ipc.resolveLocale(settingsStore.doc?.ui.language ?? "auto");
    applyLocale(locale);
  })();
  // Exit gate (03 §4.3): always prevent the default close. G-07 refinement
  // (2026-08-09): the close feels instant - the window hides and the Rust
  // shutdown coordinator runs in the background (bounded ~12s worst case),
  // then the coordinator exits the process itself. BOTH are fire-and-forget:
  // awaiting hide() here never settles while the close request is pending on
  // this Tauri version (observed 2026-08-09 - the window stayed, the
  // coordinator never ran, no shutdown log). The coordinator exits the app
  // even if hide failed; on coordinator failure, destroy the window as a
  // fallback and let the OS tear the process (and PTY children) down - the
  // runtime container keeps running by design. An unreaped-session report is
  // logged by Rust, not shown. (preventDefault must precede the async
  // confirm, otherwise the default close races it.)
  void getCurrentWindow().onCloseRequested(async (event) => {
    event.preventDefault();
    const allow = await store.confirmExit();
    if (!allow) return;
    const win = getCurrentWindow();
    void win.hide().catch(() => undefined);
    // G-10: flush geometry before shutdown (A-G10-5).
    void ipc.captureWindowGeometry().catch(() => undefined);
    void ipc.shutdownWorkbench().catch((e) => {
      console.error("shutdown_workbench failed, destroying window:", e);
      void win.destroy().catch(() => undefined);
    });
  });
  window.addEventListener("keydown", onKeydown, { capture: true });
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
  window.removeEventListener("resize", onViewportResize);
  window.removeEventListener("keydown", onKeydown, { capture: true });
  if (announceTimer !== null) window.clearTimeout(announceTimer);
  if (geometryTimer !== null) window.clearTimeout(geometryTimer);
});

function isStartingView(s: string): boolean {
  return s === "starting" || s === "cancelled";
}

// S2.2.a: render a Terminal for every live tab; v-show keeps hidden tabs
// (and their PTY) alive so switching back preserves scrollback (03 §六.8).
// G-08 guide tabs render GuidePane instead (no PTY for them, A-G08-2).
const openTabs = computed(() =>
  store.tabs.filter((t) => t.sessionState !== "idle" && t.sessionState !== "guide")
);
const guideTabs = computed(() => store.tabs.filter((t) => t.sessionState === "guide"));

// S3.3: expose each Terminal's focus so the tab shortcut can move keyboard
// focus into the terminal after switching.
const terminalRefs = ref(new Map<string, InstanceType<typeof Terminal>>());
function setTerminalRef(tabId: string) {
  return (el: unknown) => {
    if (el) terminalRefs.value.set(tabId, el as InstanceType<typeof Terminal>);
    else terminalRefs.value.delete(tabId);
  };
}

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
  <div class="app" :style="uiZoom">
    <header class="topbar">
      <span class="brand">AISC Workbench</span>
      <span class="status" :data-status="store.status">{{ store.status }}</span>
      <span class="spacer" />
      <button class="settings-btn" @click="settingsOpen = true">{{ t("app.settings") }}</button>
    </header>

    <!-- Step 3: typed settings dialog (keyboard-accessible modal, A-G01-1) -->
    <SettingsDialog v-if="settingsOpen" @close="settingsOpen = false" />

    <!-- S3.3: screen-reader live regions (04 §九). Visually hidden, announced
         only on semantic changes (throttled). -->
    <div class="sr-only" role="status" aria-live="polite">{{ livePolite }}</div>
    <div class="sr-only" role="alert" aria-live="assertive">{{ liveAlert }}</div>

    <!-- Capability gate -->
    <div v-if="store.status === 'blocked'" class="gate blocked">
      <h2>{{ t("app.blocked.title") }}</h2>
      <p class="err">{{ store.error?.message ?? t("app.blocked.cli") }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <div class="actions">
        <button @click="store.pickAndPinCli()">{{ t("app.blocked.pickCli") }}</button>
        <button class="diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
      </div>
    </div>

    <!-- Loading / stopping -->
    <div v-else-if="['idle', 'negotiating', 'preflight', 'stopping'].includes(store.status)" class="center">
      <p class="msg">{{
        store.status === "stopping"
          ? t("app.stopping")
          : store.status === "preflight"
          ? t("app.preflight")
          : t("app.negotiating")
      }}</p>
    </div>

    <!-- Workspace picker -->
    <div v-else-if="store.status === 'picker'" class="picker">
      <h2>{{ t("picker.title") }}</h2>
      <div class="row">
        <input
          v-model="store.workspace"
          class="workspace"
          :placeholder="t('picker.placeholder')"
          @keyup.enter="store.runPreflight()"
        />
        <button @click="store.pickWorkspace()">{{ t("picker.browse") }}</button>
        <button class="primary" :disabled="!store.workspace.trim()" @click="store.runPreflight()">{{ t("picker.next") }}</button>
      </div>
      <p class="hint">{{ t("picker.hint") }}</p>
      <div v-if="store.recentWorkspaces.length" class="recents">
        <div class="recents-label">{{ t("picker.recents") }}</div>
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
          <!-- G-08 empty state (A-G08-6): focus target for creating the first tab -->
          <div v-if="store.tabs.length === 0" class="empty-tabs">
            <p>{{ t("tabs.empty") }}</p>
            <button class="primary" @click="store.createTab('bash')">{{ t("tabs.newTab") }}</button>
          </div>
          <!-- The 1:1 counter-zoom wraps ONLY the xterm (GuidePane and the
               empty state are UI chrome and must follow the UI scale). -->
          <div
            v-for="t in guideTabs"
            :key="t.tabId"
            class="term-wrap"
            v-show="t.tabId === store.activeTabId"
          >
            <GuidePane :tab-id="t.tabId" />
          </div>
          <div
            v-for="t in openTabs"
            :key="t.tabId"
            class="term-wrap"
            :style="terminalZoom"
            v-show="t.tabId === store.activeTabId"
          >
            <Terminal :ref="setTerminalRef(t.tabId)" :tab-id="t.tabId" />
          </div>
        </main>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="store.status === 'error'" class="gate error">
      <h2>{{ t("app.error.title") }}</h2>
      <p class="err">{{ store.error?.message }}</p>
      <p class="detail">{{ store.error?.technical_detail }}</p>
      <div class="actions">
        <button @click="store.negotiate()">{{ t("app.error.retry") }}</button>
        <button @click="store.backToPicker()">{{ t("app.error.back") }}</button>
        <!-- G-13: one-click diagnosis from the error page (A-G13-1/3) -->
        <button class="diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
      </div>
    </div>

    <!-- G-13: diagnosis dialog, shared by blocked/error/ready entry points -->
    <DoctorDialog v-if="doctorStore.open" />
  </div>
</template>

<style scoped>
/* Visually hidden but screen-reader-visible (S3.3). */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
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
.spacer { flex: 1; }
.status { font-size: 12px; color: #888; }
.status[data-status="ready"] { color: #4caf50; }
.status[data-status="error"], .status[data-status="blocked"] { color: #e57373; }
.settings-btn { padding: 3px 10px; font-size: 12px; }
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
.diagnose { background: #2d3a4a; border-color: #3a4a5a; }
.terminal-area { flex: 1; min-height: 0; padding: 4px; background: #1e1e1e; display: flex; }
.term-wrap { flex: 1; min-height: 0; min-width: 0; }
.empty-tabs {
  height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px; color: #888; font-size: 13px;
}
</style>
