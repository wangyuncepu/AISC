<script setup lang="ts">
/**
 * S2.1.a startup shell. IDEA-3 (3c): App is now the app-level shell only —
 * topbar, onboarding gate, boot/blocked gates, the workspace strip
 * (WorkspaceBar) and ONE active WorkspaceView (keyed by instance id; switching
 * remounts, which is safe by design — Terminals replay from store-owned
 * buffers and sessions never re-open). Instance state machines, the ready
 * workspace internals and the session-layer shortcuts all live in
 * WorkspaceView now; workspace concurrency lives in stores/workspaces.ts.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { listen } from "@tauri-apps/api/event";
import {
  captureWindowGeometry,
  resolveLocale,
  shutdownWorkbenchV2,
  trayAvailable as trayAvailableIpc,
  trayRemove,
} from "./lib/ipc";
import { applyLocale } from "./i18n";
import { applyTheme, createSystemListener } from "./theme";
import { blockNativeContextMenu } from "./lib/contextMenu";
import ToastHost from "./components/ToastHost.vue";
import { layoutTierFor, type LayoutTier } from "./lib/layout";
import { toggleExplorerCollapsed } from "./lib/panelLayout";
import { setExplorerCollapsed } from "./lib/panelLayout";
import type { CommandCtx } from "./lib/commands";
import CommandPalette from "./components/CommandPalette.vue";
import FloatingPane from "./components/FloatingPane.vue";
import MenuBar from "./components/MenuBar.vue";
import { computeWindowTitle } from "./lib/title";
import { useRuntimeStore } from "./stores/runtime";
import { useWorkspacesStore } from "./stores/workspaces";
import { useSettingsStore } from "./stores/settings";
import { useDoctorStore } from "./stores/doctor";
import { useRuntimePolling } from "./composables/useRuntimePolling";
import { useProviderPolling } from "./composables/useProviderPolling";
import SettingsTab from "./features/settings/SettingsTab.vue";
import NetworkUsageTab from "./features/usage/NetworkUsageTab.vue";
import DoctorDialog from "./features/doctor/DoctorDialog.vue";
import OnboardingWizard from "./features/onboarding/OnboardingWizard.vue";
import InvalidPathDialog from "./features/startup/InvalidPathDialog.vue";
import WorkspaceView from "./features/workspace/WorkspaceView.vue";
import { useWorkspaceExplorerStore } from "./stores/workspaceExplorer";
import { useOnboardingStore } from "./stores/onboarding";

const { t } = useI18n();
const store = useRuntimeStore();
const ws = useWorkspacesStore();
const settingsStore = useSettingsStore();
const doctorStore = useDoctorStore();
const explorerStore = useWorkspaceExplorerStore();
const onboardingStore = useOnboardingStore();
const polling = useRuntimePolling();
const providerPolling = useProviderPolling();

// v2.1.7 S3 (⑥/D3): the wizard is MANUAL-ONLY — startup always lands on
// the picker; the overlay appears exclusively when opened from Settings and
// lowers again when the wizard finishes/skips (the store watches isFinished).
const showOnboarding = computed(() => onboardingStore.wizardOpen);

// Stage 5 (ONB-07) belt-and-suspenders: if a manually-opened wizard finishes
// while negotiate somehow never ran (idle), start it now. Normally boot
// already negotiated unconditionally (see onMounted, A-21735).
watch(
  () => onboardingStore.isFinished,
  (finished) => {
    if (finished && store.status === "idle") {
      store.negotiate();
    }
  }
);

// Stage 3: keep the workspace watcher alive even when the Explorer rail is
// hidden, so agent-created files are captured while the panel is closed.
// Follows the ACTIVE workspace (the explorer is a single instance; per-path
// tree caching is 3e).
watch(
  [() => store.workspace, () => store.status],
  ([w, status]) => {
    if (w && status === "ready") {
      explorerStore.setWorkspace(w);
    }
  },
  { immediate: true }
);

// IDEA-3 (3d) → W1 (shell-redesign): Settings & the data dashboard are
// FLOATING panes now (FloatingPane owns focus/Esc/×). Entries: the
// rail-bottom icons, the palette, and Ctrl+, from any post-onboarding
// state.
function toggleSettings(): void {
  if (ws.settingsTabActive) {
    settingsStore.cancel(); // revert unsaved edits, same contract as before
    ws.closeSettingsTab();
  } else {
    ws.openSettingsTab();
  }
}

// W3 手测 r10/r11: the dead-recent remediation dialog — app-level FLOATING
// mount (never hijacks the launcher/active workspace; the boot-param path
// in a fresh window lands the same overlay above its picker).
const overlayInvalidPath = ref<string | null>(null);
const overlayExportBusy = ref(false);
watch(
  () => ws.pendingInvalidPath,
  (p) => {
    if (p) overlayInvalidPath.value = ws.consumeInvalidPath();
  },
  { immediate: true },
);
async function onOverlayClear(purgeData: boolean): Promise<void> {
  const path = overlayInvalidPath.value;
  overlayInvalidPath.value = null;
  if (path) await ws.clearInvalidRecent(path, purgeData);
}
async function onOverlayExport(): Promise<void> {
  const path = overlayInvalidPath.value;
  if (!path) return;
  overlayExportBusy.value = true;
  try {
    await ws.exportInvalidRecent(path);
  } finally {
    overlayExportBusy.value = false;
  }
}

// IDEA-2 (2d): the「网络与用量」pane — same floating treatment (W1).

// P2-4 (D-4): the command palette — Ctrl+Shift+P (the r5 print-block used
// to swallow this combo dead; it now opens the palette instead).
const paletteOpen = ref(false);
// W2: the menu bar (and future surfaces) reach the palette through this
// window event — one owner, no prop drilling.
function onOpenPalette(): void {
  if (!paletteOpen.value) paletteOpen.value = true;
}
onMounted(() => window.addEventListener("aisc:open-palette", onOpenPalette));
onBeforeUnmount(() => window.removeEventListener("aisc:open-palette", onOpenPalette));
const explorerForPalette = useWorkspaceExplorerStore();
function paletteCtx(): CommandCtx {
  return {
    active: {
      createTab: (agent) => store.createTab(agent),
      splitPane: (dir, agent) => {
        if (!store.activeTabId) return;
        store.splitTabPane(
          store.activeTabId,
          dir === "h" ? "horizontal" : "vertical",
          agent,
        );
      },
      status: store.status,
      workspace: store.workspace,
    },
    app: {
      openSettings: () => ws.openSettingsTab(),
      openNetworkUsage: () => ws.openNetworkUsageTab(),
      openPicker: () => ws.openLauncher(),
      runDoctor: () => doctorStore.openDialog(),
      toggleSidebar: () => toggleExplorerCollapsed(),
      showView: (kind) => {
        setExplorerCollapsed(false);
        explorerForPalette.activateView(kind);
      },
      servicesSupported: () => store.capability?.runtime_services ?? false,
    },
  };
}

// The ONE app-level keydown (workspace layer): Ctrl/Cmd+, toggles Settings
// everywhere after onboarding; Ctrl/Cmd+PgUp/PgDn cycles workspaces;
// Ctrl/Cmd+Alt+1..9 activates the nth workspace (VSCode-style groups are a
// different metaphor — Ctrl+1..9 keep their SESSION-tab meaning in
// WorkspaceView). If a WebView2 build swallows a combo, the strip chips
// remain the fallback (same philosophy as the Ctrl+Tab comment).
function onAppKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  // Manual-test r5 #1: WebView2 leaks the browser print surfaces — Ctrl+P
  // opens 打印, Ctrl+Shift+P opens 打印设置. Neither belongs in a terminal
  // workbench; P2-4: Ctrl+Shift+P now OPENS THE COMMAND PALETTE, plain
  // Ctrl+P stays swallowed.
  if ((e.key === "p" || e.key === "P") && e.shiftKey && !e.altKey) {
    e.preventDefault();
    paletteOpen.value = !paletteOpen.value;
    return;
  }
  if (e.key === "p" || e.key === "P") {
    e.preventDefault();
    e.stopPropagation();
    return;
  }
  if (e.key === "," && !showOnboarding.value) {
    e.preventDefault();
    toggleSettings();
    return;
  }
  // P2-3 (D-4): VS Code's Ctrl+B — toggle the side panel; the activity rail
  // stays (panelLayout is the module singleton, so this reaches the layout
  // regardless of which layer holds focus).
  if ((e.key === "b" || e.key === "B") && !showOnboarding.value) {
    e.preventDefault();
    toggleExplorerCollapsed();
    return;
  }
  // W3 (ruling c): cross-workspace cycling left with the strip — the OS
  // taskbar owns window switching now.
}
onMounted(() => window.addEventListener("keydown", onAppKeydown, { capture: true }));

// G-01 (Step 7, A-G01-3): ui.font_scale is immediate-effect. Applied as CSS
// zoom on the UI chrome; the terminal area is counter-zoomed so xterm stays
// 1:1 (WorkspaceView receives the counter-zoom style).
const uiScale = computed(() => settingsStore.doc?.ui.font_scale ?? 1);
// G-04 (Step 17, A-G04-1/2): apply the persisted theme mode as soon as it is
// known; main.ts already painted the system default before the first frame.
watch(
  () => settingsStore.doc?.ui.theme,
  (mode) => applyTheme(mode ?? "system"),
  { immediate: true }
);
// A-G04-4: `system` (or unset) re-resolves on OS dark/light changes.
const stopSystemTheme = createSystemListener(() => {
  const mode = settingsStore.doc?.ui.theme;
  if (!mode || mode === "system") applyTheme("system");
});
const windowSize = ref({ w: window.innerWidth, h: window.innerHeight });
// G-10: debounced geometry capture (300ms, A-G10-5).
let geometryTimer: number | null = null;
function onViewportResize() {
  windowSize.value = { w: window.innerWidth, h: window.innerHeight };
  if (geometryTimer !== null) window.clearTimeout(geometryTimer);
  geometryTimer = window.setTimeout(() => {
    geometryTimer = null;
    void captureWindowGeometry().catch(() => undefined);
  }, 300);
}
onMounted(() => window.addEventListener("resize", onViewportResize));
const effectiveScale = computed(() =>
  Math.min(uiScale.value, 1.5, windowSize.value.w / 800, windowSize.value.h / 600)
);
// Zoom scales layout too, so the app box must compensate its height/width.
const uiZoom = computed(() => ({
  zoom: String(effectiveScale.value),
  height: `calc(100vh / ${effectiveScale.value})`,
  width: `calc(100vw / ${effectiveScale.value})`,
}));
// Stage 6 (UX-02): layout tier by the EFFECTIVE layout width.
const layoutTier = computed<LayoutTier>(
  () => layoutTierFor(window.innerWidth / (effectiveScale.value || 1))
);
const terminalZoom = computed(() => ({ zoom: String(1 / effectiveScale.value) }));

// S3.3: aria-live regions. Throttled ~1s so bursts coalesce to the latest.
const livePolite = ref("");
const liveAlert = ref("");
let announceTimer: number | null = null;
let pendingAnnounce = "";

function announce(text: string, alert = false) {
  pendingAnnounce = text;
  if (announceTimer !== null) return;
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

// P2-2 (D-2): the topbar status label moved into WorkspaceBar (.bar-status);
// nothing here renders it anymore. The window title watcher below already
// carries the workspace identity (computeWindowTitle) — the static brand
// row's last duty is gone with the row.

// KI-1 UX: announce the wake-up start and its SUCCESS.
watch(
  () => store.dockerStarting,
  (starting, prev) => {
    if (starting) {
      announce(t("app.dockerStartingStatus"));
    } else if (prev) {
      const dockerOk = store.preflight?.checks.some(
        (c) => c.id === "docker" && c.status === "pass"
      );
      if (dockerOk) announce(t("app.dockerReady"));
    }
  }
);

// Announce runtime-state transitions (only when the value actually changes).
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

// G-15 (Step 14): dynamic window title, driven by the active context.
const activeTabTitleContext = computed(() => {
  const tab = store.tabs.find((tb) => tb.tabId === store.activeTabId) ?? null;
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

/** Boot states live on the launcher until negotiate settles; after that the
 * workspace layer (strip + views) owns the surface. Blocked renders the
 * app gate UNDER the strip (settings must stay reachable — the chip lands
 * 3d; today the topbar gear covers it).
 * W3 手测 r7: a param-booted window ALSO waits for consumeBootParams —
 * otherwise the picker flashes for a frame before selectRecentWorkspace
 * lands the instance on preflight/summary. */
const booting = computed(() => ["idle", "negotiating"].includes(store.status));
const bootParamsSettled = ref(true);
const workspaceLayerVisible = computed(
  () => !booting.value && bootParamsSettled.value);

// G-16 (Step 15): tray availability gate.
const trayAvailable = ref(false);

// Shared quit flow: window close confirm + hide + geometry flush + shutdown
// coordinator (A-G16-3: the tray 退出 menu shares it).
async function runExitFlow(): Promise<void> {
  const allow = await store.confirmExit();
  if (!allow) return;
  const win = getCurrentWindow();
  // W3 手测 r4#3: a spawned window closes ALONE. The process-global
  // coordinator is FORBIDDEN here — run_shutdown hides the MAIN window and
  // sweeps EVERY window's session registry (field evidence: closing one
  // window closed both). Scoped teardown: this window's sessions, then
  // stop→remove its runtimes (lease release rides remove), then destroy.
  if (win.label !== "main") {
    // 手测 r6: the JS-side win.hide() IPC NO-OPS while a close request is
    // pending (G-07) — the window lingered visually through the whole
    // teardown. Rust-side hide (direct win32) is the reliable instant one.
    ws.hideWindowForExit();
    void ws
      .closeWindowScoped()
      .catch(() => undefined)
      .finally(() => {
        void win.destroy().catch(() => undefined);
      });
    return;
  }
  void win.hide().catch(() => undefined);
  void trayRemove().catch(() => undefined);
  void captureWindowGeometry().catch(() => undefined);
  // G-17: flush the debounced history save so a split/pane-close inside the
  // 300ms window survives layout restore on the next launch (feedback 2026-08-10).
  await store.flushSave();
  // runtime-lifecycle-ux Stage 3 (02 §4): structured shutdown — sessions,
  // then per-runtime stop→remove for every materialized workspace, then
  // lease release, all inside the Rust coordinator.
  void shutdownWorkbenchV2({
    workspaces: store.shutdownTargets(),
    reason: "window_close",
  }).catch((e) => {
    console.error("shutdown_workbench_v2 failed, destroying window:", e);
    void win.destroy().catch(() => undefined);
  });
}

/** W3 (ruling c): a window spawned with ?workspace= (POSIX ⇒ remote,
 * ?machine names the drive) boots STRAIGHT into its workspace — one
 * window, one workspace; the OS taskbar owns cross-workspace switching. */
async function consumeBootParams(): Promise<void> {
  const params = new URLSearchParams(location.search);
  const wsPath = params.get("workspace");
  const machine = params.get("machine");
  if (!wsPath && !machine) return;
  bootParamsSettled.value = false;
  await settingsStore.refreshTarget();
  if (machine) {
    await settingsStore.switchTarget(machine);
  } else if (wsPath?.startsWith("/")) {
    const name = settingsStore.target?.machine?.name
      ?? settingsStore.doc?.remoteMachines?.[0]?.name ?? null;
    if (settingsStore.target?.kind !== "remote") await settingsStore.switchTarget(name);
  }
  if (!ws.openLauncher()) return; // cap guard (harmless in a fresh window)
  if (!wsPath) return; // remote launcher window — the picker carries on
  if (!(await ws.workspacePathExists(wsPath))) {
    // Same remediation as the picker's own dead-recent click (手测 r10) —
    // silently parking on the launcher left the dead record unexplained.
    ws.surfaceInvalidPath(wsPath);
    return;
  }
  store.selectRecentWorkspace(wsPath);
}

onMounted(() => {
  // PP r8 (user request): kill the WebView2 default context menu app-wide —
  // the only context menus in the Workbench are our own Vue ones.
  blockNativeContextMenu();
  // v2.1.7 S3: the wizard never gates startup anymore — negotiate ALWAYS
  // runs; a CLI discovery failure surfaces through the global blocked gate
  // instead of stranding the user on a wizard (A-21735).
  void (async () => {
    await onboardingStore.load();
    await store.negotiate();
    try {
      await consumeBootParams();
    } finally {
      bootParamsSettled.value = true;
    }
  })();
  // G-09 (02 §3.1): resolve + apply the locale in parallel.
  void (async () => {
    if (!settingsStore.loaded) await settingsStore.load();
    const locale = await resolveLocale(settingsStore.doc?.ui.language ?? "auto");
    applyLocale(locale);
  })();
  // G-16: query tray availability once (Rust setup already ran).
  void trayAvailableIpc()
    .then((ok: boolean) => (trayAvailable.value = ok))
    .catch(() => undefined);
  // Exit gate (03 §4.3): always prevent the default close; hide first, the
  // Rust shutdown coordinator runs in the background and exits the process.
  void getCurrentWindow().onCloseRequested(async (event) => {
    event.preventDefault();
    const behavior = settingsStore.doc?.window.close_behavior ?? "quit";
    if (behavior === "minimize-to-tray" && trayAvailable.value) return;
    await runExitFlow();
  });
  // G-16: tray 退出 uses the same confirm + shutdown (A-G16-3).
  void listen("exit-requested", () => {
    void runExitFlow();
  });
  // PERF P8 (D-13): the one-time low-spec auto-enable notification — the
  // Rust setup thread emits after persisting performance.lowSpec=true.
  // System notification (same degrade-silently semantics as build toasts);
  // the Settings > performance page carries the durable explanation.
  void listen("low-spec-enabled", async () => {
    try {
      const { isPermissionGranted, requestPermission, sendNotification } =
        await import("@tauri-apps/plugin-notification");
      let granted = await isPermissionGranted();
      if (!granted) granted = (await requestPermission()) === "granted";
      if (!granted) return;
      sendNotification({
        title: t("notification.title"),
        body: t("toast.lowSpecEnabled"),
      });
    } catch {
      /* advisory only — never blocks startup */
    }
  });
});

// S2.3.a/b: poll runtimes while ANY workspace is open (真并行: the loop
// refreshes the active one at full cadence and downshifts background ones —
// see useRuntimePolling); provider status still follows the ACTIVE tab.
watch(
  () => ws.runtimes.length > 0,
  (any) => {
    if (any) polling.start();
    else polling.stop();
  }
);
watch(
  () => store.status,
  (s) => {
    if (s === "ready") providerPolling.start();
    else providerPolling.stop();
  }
);

onBeforeUnmount(() => {
  polling.stop();
  providerPolling.stop();
  stopSystemTheme();
  window.removeEventListener("resize", onViewportResize);
  window.removeEventListener("keydown", onAppKeydown, { capture: true });
  if (announceTimer !== null) window.clearTimeout(announceTimer);
  if (geometryTimer !== null) window.clearTimeout(geometryTimer);
});
</script>

<template>
  <div class="app" :style="uiZoom" :data-tier="layoutTier">
    <!-- P2-2 (D-2, user ruling A): the topbar ROW is GONE — the static
         「AISC Workbench」 carried zero information and duplicated the strip.
         The status label moved into WorkspaceBar's right end; the window
         title is now dynamic (workspace name, watcher below). -->

    <!-- Stage 5 (ONB-01): first-run wizard overlay. -->
    <div v-if="showOnboarding" class="onboarding-gate">
      <OnboardingWizard />
    </div>

    <!-- S3.3: screen-reader live regions. -->
    <div class="sr-only" role="status" aria-live="polite">{{ livePolite }}</div>
    <div class="sr-only" role="alert" aria-live="assertive">{{ liveAlert }}</div>

    <template v-if="!showOnboarding">
      <!-- IDEA-3 (3c/3f round 2): the workspace strip stays mounted in EVERY
           post-onboarding state — including while the Settings tab fills the
           content area — so the chip × (and the + ▾ menu) are always an exit
           path. Only the WorkspaceView yields to the settings pane. -->
      <!-- W2 (shell-redesign, ruling a): the in-window menu bar. The strip
           below still carries multi-workspace chips until W3 retires it. -->
      <MenuBar v-if="workspaceLayerVisible" />

      <!-- W1 (shell-redesign): Settings & the data dashboard are FLOATING
           panes now (rail-bottom icons / Ctrl+, / palette) — the workspace
           keeps rendering underneath. -->
      <FloatingPane
        v-if="ws.settingsTabActive"
        :title="t('workspbar.settings')"
        wide
        height="min(680px, 84vh)"
        @close="ws.closeSettingsTab()"
      >
        <SettingsTab />
      </FloatingPane>
      <FloatingPane
        v-if="ws.networkUsageTabActive"
        :title="t('workspbar.networkUsage')"
        wide
        @close="ws.closeNetworkUsageTab()"
      >
        <NetworkUsageTab />
      </FloatingPane>

      <!-- Capability gate (app-level; strip stays for reachability) -->
      <div v-if="store.status === 'blocked'" class="gate blocked">
        <h2>{{ t("app.blocked.title") }}</h2>
        <p class="err">{{ store.error?.message ?? t("app.blocked.cli") }}</p>
        <p class="detail">{{ store.error?.technical_detail }}</p>
        <div class="actions">
          <button class="ui-button" @click="store.pickAndPinCli()">{{ t("app.blocked.pickCli") }}</button>
          <button class="ui-button diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
        </div>
      </div>

      <!-- Boot (idle/negotiating) -->
      <div v-else-if="booting || !bootParamsSettled" class="center">
        <p class="msg">{{ t("app.negotiating") }}</p>
      </div>

      <!-- The ACTIVE workspace's view (keyed remount on switch). W1: the
           floating panes overlay it instead of replacing it. -->
      <!-- The condition rides the TRANSITION itself — a wrapper between the
           v-else-if chain and its v-else breaks chain adjacency (Vue
           compile error; 手测 r9). -->
      <Transition v-else name="fade" mode="out-in">
        <WorkspaceView
          :key="ws.activeRuntime.id"
          :zoom="terminalZoom"
          :tier="layoutTier"
        />
      </Transition>
    </template>

    <!-- G-13: diagnosis dialog, shared by blocked/error/ready entry points.
         10e: unified fade motion (D10-09). -->
    <Transition name="fade">
      <DoctorDialog v-if="doctorStore.open" />
    </Transition>

    <!-- W3 手测 r11: dead-recent remediation floats over ANY state. -->
    <InvalidPathDialog
      v-if="overlayInvalidPath"
      :path="overlayInvalidPath"
      :busy="overlayExportBusy"
      @close="overlayInvalidPath = null"
      @clear="onOverlayClear"
      @export="onOverlayExport"
    />

    <!-- P2-1 (A2 反馈语法): the ONE global toast host — body-teleported,
         above every layer. Features push through useToastStore. -->
    <ToastHost />

    <!-- P2-4 (A1): the command palette (Ctrl+Shift+P). -->
    <CommandPalette v-if="paletteOpen" :make-ctx="paletteCtx" @close="paletteOpen = false" />
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
/* P2-2 (D-2): the .topbar block/brand/spacer/status styles are retired with
 * the row itself — the status label now lives in WorkspaceBar (.bar-status),
 * the window title carries the identity instead of a static brand. */
.settings-pane { flex: 1; min-height: 0; min-width: 0; display: flex; outline: none; }
.gate.blocked, .center {
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
.onboarding-gate {
  position: fixed;
  inset: 0;
  z-index: var(--z-onboarding);
  background: var(--surface);
  display: flex;
}
.actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
/* 10c: buttons are .ui-button primitives now; only the info-tinted diagnose
 * variant stays local. */
.diagnose { background: var(--info-bg); border-color: var(--info-border); color: var(--text); }

/* Stage 6 (UX-02): layout tiers driven by the effective app-box width.
 * P2-2: the compact topbar rules left with the row; the bar-status label's
 * compact rule lives unscoped at the bottom of this file (WorkspaceBar's
 * own style block is scoped and cannot match its own element from here,
 * nor can this scoped block reach into the child — FIX-3 audit (d) lesson).
 */
/* FIX-3 audit (d): the three rules below (sidebar/explorer-dock/status-drawer)
 * were DEAD since birth — this style block is scoped, so they compiled to
 * `[data-v-app]` selectors that can never match elements rendered by child
 * components. The compact explorer/status rules now live (alive) in
 * WorkspaceView.vue's own scoped styles via the :tier prop. */
</style>

<style>
/* P2-2 → W3: the strip's compact rule left with the strip (the status
 * label now rides the menu bar, hidden on compact in MenuBar's own styles). */
</style>
