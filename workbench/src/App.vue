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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
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
import { layoutTierFor, type LayoutTier } from "./lib/layout";
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
import WorkspaceBar from "./features/workspace/WorkspaceBar.vue";
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

// IDEA-3 (3d): Settings is a WORKSPACE-layer tab (the strip's sentinel) —
// the topbar gear and the pre-ready modal dialog are both retired. Entries:
// the strip's Settings chip, the picker's embedded button, and Ctrl+, from
// ANY post-onboarding state. When active, the settings pane fills the
// content area (the last workspace stays a keyed-remount away).
const settingsPaneRef = ref<HTMLElement | null>(null);
function toggleSettings(): void {
  if (ws.settingsTabActive) {
    settingsStore.cancel(); // revert unsaved edits, same contract as the chip ×
    ws.closeSettingsTab();
  } else {
    ws.openSettingsTab();
    void nextTick(() => settingsPaneRef.value?.focus({ preventScroll: true }));
  }
}

// IDEA-2 (2d): the「网络与用量」pane — same slot as Settings. It opens from
// the strip chip / ▾ menu (no shortcut in v1), so focus follows activation.
const networkUsagePaneRef = ref<HTMLElement | null>(null);
watch(
  () => ws.networkUsageTabActive,
  (active) => {
    if (active) void nextTick(() => networkUsagePaneRef.value?.focus({ preventScroll: true }));
  },
);

// The ONE app-level keydown (workspace layer): Ctrl/Cmd+, toggles Settings
// everywhere after onboarding; Ctrl/Cmd+PgUp/PgDn cycles workspaces;
// Ctrl/Cmd+Alt+1..9 activates the nth workspace (VSCode-style groups are a
// different metaphor — Ctrl+1..9 keep their SESSION-tab meaning in
// WorkspaceView). If a WebView2 build swallows a combo, the strip chips
// remain the fallback (same philosophy as the Ctrl+Tab comment).
function onAppKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  if (e.key === "," && !showOnboarding.value) {
    e.preventDefault();
    toggleSettings();
    return;
  }
  if (showOnboarding.value || !workspaceLayerVisible.value) return;
  if (e.key === "PageUp" && !e.altKey && !e.shiftKey) {
    e.preventDefault();
    ws.cycle(-1);
  } else if (e.key === "PageDown" && !e.altKey && !e.shiftKey) {
    e.preventDefault();
    ws.cycle(1);
  } else if (e.altKey && e.key >= "1" && e.key <= "9") {
    const target = ws.runtimes[Number(e.key) - 1];
    if (target) {
      e.preventDefault();
      ws.activate(target.id);
    }
  }
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

// Stage 6 (UX-04): topbar status label (store.status, never a raw enum).
const STATUS_KEY: Record<string, string> = {
  idle: "app.status.idle",
  negotiating: "app.negotiating",
  preflight: "app.preflight",
  picker: "app.status.picker",
  summary: "app.status.summary",
  starting: "app.starting",
  cancelled: "app.status.cancelled",
  building: "app.status.building",
  conflict: "app.status.conflict",
  ready: "app.status.ready",
  stopping: "app.stopping",
  blocked: "app.status.blocked",
  error: "app.error.title",
};

// KI-1 UX: while the Docker boot loop runs, the topbar leads with the wake-up.
const statusLabel = computed(() =>
  store.dockerStarting
    ? t("app.dockerStartingStatus")
    : t(STATUS_KEY[store.status] ?? "app.unknown")
);

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
 * 3d; today the topbar gear covers it). */
const booting = computed(() => ["idle", "negotiating"].includes(store.status));
const workspaceLayerVisible = computed(() => !booting.value);

// G-16 (Step 15): tray availability gate.
const trayAvailable = ref(false);

// Shared quit flow: window close confirm + hide + geometry flush + shutdown
// coordinator (A-G16-3: the tray 退出 menu shares it).
async function runExitFlow(): Promise<void> {
  const allow = await store.confirmExit();
  if (!allow) return;
  const win = getCurrentWindow();
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

onMounted(() => {
  // PP r8 (user request): kill the WebView2 default context menu app-wide —
  // the only context menus in the Workbench are our own Vue ones.
  blockNativeContextMenu();
  // v2.1.7 S3: the wizard never gates startup anymore — negotiate ALWAYS
  // runs; a CLI discovery failure surfaces through the global blocked gate
  // instead of stranding the user on a wizard (A-21735).
  void (async () => {
    await onboardingStore.load();
    store.negotiate();
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
    <header class="topbar">
      <span class="brand">AISC Workbench</span>
      <span class="status" :data-status="store.status">{{ statusLabel }}</span>
      <span class="spacer" />
    </header>

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
      <WorkspaceBar v-if="workspaceLayerVisible" />

      <!-- IDEA-3 (3d): the workspace-level Settings page — rendered AFTER the
           strip (round-3 fix: it used to sit above it, pushing the strip to
           the window bottom) and taking the content area only. -->
      <div v-if="ws.settingsTabActive" ref="settingsPaneRef" class="settings-pane" tabindex="-1">
        <SettingsTab />
      </div>

      <!-- IDEA-2 (2d): the workspace-level「网络与用量」panel — same content
           area takeover semantics as the settings pane. -->
      <div v-if="ws.networkUsageTabActive" ref="networkUsagePaneRef" class="settings-pane" tabindex="-1">
        <NetworkUsageTab />
      </div>

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
      <div v-else-if="booting" class="center">
        <p class="msg">{{ t("app.negotiating") }}</p>
      </div>

      <!-- The ACTIVE workspace's view (keyed remount on switch); yields to
           the Settings / 网络与用量 panes while either is active. -->
      <WorkspaceView
        v-else-if="!ws.settingsTabActive && !ws.networkUsageTabActive"
        :key="ws.activeRuntime.id"
        :zoom="terminalZoom"
      />
    </template>

    <!-- G-13: diagnosis dialog, shared by blocked/error/ready entry points.
         10e: unified fade motion (D10-09). -->
    <Transition name="fade">
      <DoctorDialog v-if="doctorStore.open" />
    </Transition>
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
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--font-base);
  border-bottom: var(--border-w) solid var(--border);
}
.brand { font-weight: 600; }
.spacer { flex: 1; }
/* 10c round 2: quiet colored text — the badge pill was too heavy up here. */
.status { font-size: var(--font-sm); color: var(--text-muted); }
.status[data-status="ready"] { color: var(--success); }
.status[data-status="error"], .status[data-status="blocked"] { color: var(--error); }
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

/* Stage 6 (UX-02): layout tiers driven by the effective app-box width. */
.app[data-tier="compact"] .topbar { gap: var(--space-2); padding: 4px var(--space-2); }
.app[data-tier="compact"] .topbar .status { display: none; } /* keep the brand readable */
.app[data-tier="compact"] .sidebar { padding: var(--space-2); }
.app[data-tier="compact"] .explorer-dock { width: min(280px, 45%); min-width: 200px; }
.app[data-tier="compact"] .status-drawer { width: min(300px, 100%); }
</style>
