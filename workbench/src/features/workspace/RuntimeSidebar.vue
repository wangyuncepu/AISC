<script setup lang="ts">
/**
 * RuntimeSidebar (G-05, Step 8; 04-observability.md §二): two-layer P0
 * observability for the ready view.
 *
 * User layer (always visible, semantic view model - sections are keyed so an
 * unchanged semantic key leaves the subtree untouched, A-G05-1): workspace,
 * runtime state (stale -> "last known" styling, never deterministic green),
 * provider name, auth with an action when unconfigured, session count.
 *
 * Developer details (collapsed by default, native <details> - keyboard
 * reachable): exact IDs/container/owner/fingerprint, freshness, relative +
 * absolute observed time, image/network/scope, raw route/auth. Nothing is
 * deleted, only layered (04 §2.2). The 1-second ticker is gone: relative time
 * is recomputed per snapshot and when the details expand.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkspacesStore } from "../../stores/workspaces";
import { useDoctorStore } from "../../stores/doctor";
import { i18n as i18nLocale } from "../../i18n";
import type { RuntimeState } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();
const workspaces = useWorkspacesStore();
const doctorStore = useDoctorStore();

const snap = computed(() => store.runtimeSnapshot);

/** runtime-lifecycle-ux 3a: policy label (persistent | ephemeral toolchain). */
const dependencyPolicyLabel = computed(() => {
  const policy = snap.value?.dependency_policy;
  if (!policy) return "";
  return policy === "persistent_toolchain"
    ? t("sidebar.toolchainPersistent")
    : t("sidebar.toolchainEphemeral");
});

// --- observed time: no ticker; cached per snapshot, refreshed on details open
const agoCache = new Map<string, string>();
function agoFor(iso: string | undefined): string {
  if (!iso) return "-";
  const cached = agoCache.get(iso);
  if (cached) return cached;
  const ts = Date.parse(iso);
  let out = "-";
  if (!Number.isNaN(ts)) {
    const sec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    out =
      sec < 60 ? `${sec}s ago` : sec < 3600 ? `${Math.floor(sec / 60)}m ago` : `${Math.floor(sec / 3600)}h ago`;
  }
  agoCache.set(iso, out);
  return out;
}
const observedAgoText = computed(() => agoFor(snap.value?.observed_at));

const detailsOpen = ref(false);
const observedAbsText = computed(() => {
  const iso = snap.value?.observed_at;
  if (!iso) return "-";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  // Recompute relative time when details expand (04 §4.1).
  agoCache.delete(iso);
  return new Date(ts).toLocaleString(i18nLocale.global.locale.value);
});

const workspaceName = computed(() => {
  const p = store.workspace;
  if (!p) return "-";
  const parts = p.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || p;
});

const STATE_LABEL_KEY: Record<RuntimeState, string> = {
  running: "app.running",
  stopped: "app.stopped",
  not_found: "app.notFound",
  unknown: "app.unknown",
  starting: "app.starting",
  stopping: "app.stopping",
  removing: "app.removing",
};

/** Stage 6 (UX-04): session-state label in the mini list (never a raw enum). */
const SESSION_LABEL_KEY: Record<string, string> = {
  idle: "session.state.idle",
  guide: "session.state.guide",
  starting: "session.state.starting",
  running: "session.state.running",
  closing: "session.state.closing",
  exited: "session.state.exited",
  failed: "session.state.failed",
  disconnected: "session.state.disconnected",
};

/** Semantic keys (04 §4.2): stable key -> untouched DOM subtree.
 *  2.1.9 T4 (#28): `freshness` is deliberately OUT — on slow-Docker hosts
 *  (nested-virt VMs over RDP) the stale↔fresh flap used to destroy and
 *  rebuild the whole section every poll cycle (a :key change remounts the
 *  subtree). The stale badge itself renders fine off-key. */
const runtimeKey = computed(
  () => `${snap.value?.state ?? "none"}|${store.runtimeState}`
);
const sessionsKey = computed(
  () =>
    store.tabs.map((x) => `${x.tabId}:${x.sessionState}`).join(",") +
    "|" +
    (store.activeTabId ?? "")
);

// --- provider / auth (user layer)
const providerSupported = computed(() => store.capability?.provider_status ?? false);
const activeTab = computed(() => store.tabs.find((x) => x.tabId === store.activeTabId) ?? null);
const activeAgent = computed(() => activeTab.value?.agent ?? null);
const providerStatus = computed(() => {
  const a = activeAgent.value;
  if (a === "claude" || a === "codex") return store.providerStatuses[a];
  return null;
});
const providerKey = computed(
  () =>
    `${snap.value?.runtime_id}|${activeAgent.value ?? "none"}|${providerStatus.value?.provider_name ?? ""}|${providerStatus.value?.route_mode ?? ""}|${providerStatus.value?.auth_status ?? ""}`
);
const providerInFlightLabel = computed(() => {
  const a = activeAgent.value;
  if (a && store.providerInFlight === a) return t("sidebar.loading");
  return t("sidebar.unknown");
});

const AUTH_LABEL_KEY: Record<string, string> = {
  configured: "sidebar.authConfigured",
  login_required: "sidebar.authLoginRequired",
  not_configured: "sidebar.authNotConfigured",
  unknown: "sidebar.authUnknown",
};
const authLabel = computed(() => {
  const st = providerStatus.value?.auth_status;
  if (!st) return null;
  return t(AUTH_LABEL_KEY[st] ?? "sidebar.authUnknown");
});
/** 04 §三: not_configured/login_required show the cc-switch action. */
const authAction = computed(() => {
  const st = providerStatus.value?.auth_status;
  return st === "not_configured" || st === "login_required";
});

const sessionsText = computed(() => {
  const n = store.tabs.length;
  const active = activeTab.value?.title ?? null;
  return t("sidebar.sessionsCount", { count: n, type: active ?? "-" });
});

function short(id: string): string {
  return id.slice(0, 8);
}

// Click-to-copy for exact IDs (hover tooltips can't be selected).
// A-G11-3: goes through the same Tauri clipboard plugin as terminal copy.
const copiedKey = ref("");
let copiedTimer: number | null = null;
function copy(key: string, text: string): void {
  if (!text) return;
  void writeText(text)
    .then(() => {
      copiedKey.value = key;
      if (copiedTimer !== null) window.clearTimeout(copiedTimer);
      copiedTimer = window.setTimeout(() => {
        copiedKey.value = "";
      }, 1500);
    })
    .catch(() => {
      /* clipboard unavailable */
    });
}
function copyDone(key: string): boolean {
  return copiedKey.value === key;
}
</script>

<template>
  <aside class="sidebar" :aria-label="t('sidebar.runtime')">
    <!-- User layer: semantic-keyed sections (A-G05-1) -->

    <section class="block" :key="`ws|${store.workspace}`">
      <div class="label">{{ t("sidebar.workspace") }}</div>
      <div
        class="value copyable"
        :title="t('sidebar.copyWorkspace', { path: store.workspace })"
        @click="copy('ws', store.workspace)"
      >{{ workspaceName }}<span v-if="copyDone('ws')" class="copied">{{ t("sidebar.copied") }}</span></div>
    </section>

    <section class="block" :key="runtimeKey">
      <div class="label">{{ t("sidebar.runtime") }}</div>
      <div class="runtime-row">
        <span
          class="state"
          :data-state="store.runtimeState"
          :data-fresh="store.freshness"
          :aria-label="`Runtime ${t(STATE_LABEL_KEY[store.runtimeState])}`"
        >{{ t(STATE_LABEL_KEY[store.runtimeState]) }}</span>
        <span v-if="store.freshness === 'stale'" class="last-known">{{ t("sidebar.lastKnown") }}</span>
      </div>
      <div class="actions-row">
        <button :disabled="store.inspectInFlight" @click="store.refreshRuntime(true)">
          {{ store.userRefreshInFlight ? t("sidebar.refreshing") : t("sidebar.refresh") }}
        </button>
        <!-- IDEA-3 (3c): stopping now closes THIS workspace only (真并行:
             other workspaces' runtimes keep running). Never disabled by
             inspectInFlight: the 5s poll holds that flag for 1-3s per cycle
             and a gated stop reads as a dead button (2026-08-25 report). -->
        <button class="danger" @click="workspaces.closeWorkspace(store.id)">{{ t("sidebar.stopRuntime") }}</button>
      </div>
    </section>

    <!-- runtime-lifecycle-ux 3a (task 11): advisory dependency policy +
         toolchain health — never a startup option, read-only display. -->
    <section v-if="store.runtimeSnapshot?.dependency_policy" class="block">
      <div class="label">{{ t("sidebar.toolchain") }}</div>
      <div class="value">{{ dependencyPolicyLabel }}</div>
      <div class="muted" :data-compat="store.runtimeSnapshot?.toolchain?.compatibility">
        {{ t("sidebar.toolchainHealth." + (store.runtimeSnapshot?.toolchain?.compatibility ?? "unknown")) }}
      </div>
    </section>

    <section class="block" :key="providerKey">
      <div class="label">{{ t("sidebar.provider") }}</div>
      <div v-if="!providerSupported" class="muted">{{ t("sidebar.providerUnsupported") }}</div>
      <div v-else-if="activeAgent !== 'claude' && activeAgent !== 'codex'" class="muted">{{ t("sidebar.providerN/a") }}</div>
      <template v-else>
        <div class="value">{{ providerStatus?.provider_name || providerInFlightLabel }}</div>
        <div v-if="authLabel" class="auth-row">
          <span class="auth" :data-auth="providerStatus?.auth_status">{{ authLabel }}</span>
          <button v-if="authAction" class="link" @click="store.openCcSwitch()">{{ t("guide.openCcSwitch") }}</button>
        </div>
        <div v-if="store.providerError" class="err">{{ store.providerError.message }}</div>
      </template>
    </section>

    <section class="block" :key="sessionsKey">
      <div class="label">{{ t("sidebar.sessions") }}</div>
      <button class="value sessions-btn" @click="store.activeTabId && store.activateTab(store.activeTabId)">
        {{ sessionsText }}
      </button>
      <ul class="mini">
        <li
          v-for="x in store.tabs"
          :key="x.tabId"
          :class="{ active: x.tabId === store.activeTabId }"
          @click="store.activateTab(x.tabId)"
        >
          <span class="t-title">{{ x.title }}</span>
          <span class="t-state" :data-state="x.sessionState">{{ t(SESSION_LABEL_KEY[x.sessionState] ?? "session.state.idle") }}</span>
        </li>
      </ul>
    </section>

    <!-- Developer details: collapsed by default, native <details> (A-G05-3/4) -->
    <details class="details" :open="detailsOpen" @toggle="detailsOpen = ($event.target as HTMLDetailsElement).open">
      <summary class="label">{{ t("sidebar.details") }}</summary>
      <div class="dev">
        <div class="kv">runtime_id <span class="mono copyable" :title="t('sidebar.copyRuntime', { id: snap?.runtime_id ?? '' })" @click="copy('rt', snap?.runtime_id ?? '')">{{ snap?.runtime_id ? short(snap.runtime_id) : "-" }}<span v-if="copyDone('rt')" class="copied">{{ t("sidebar.copied") }}</span></span></div>
        <div class="kv">container_name <span class="mono copyable" :title="t('sidebar.copyContainer', { name: snap?.container_name ?? '' })" @click="copy('ctr', snap?.container_name ?? '')">{{ snap?.container_name ?? "-" }}<span v-if="copyDone('ctr')" class="copied">{{ t("sidebar.copied") }}</span></span></div>
        <div class="kv">container_id <span class="mono copyable" :title="t('sidebar.copyContainer', { name: snap?.container_id ?? '' })" @click="copy('cid', snap?.container_id ?? '')">{{ snap?.container_id ? short(snap.container_id) : "-" }}</span></div>
        <div class="kv">owner <span class="mono">{{ snap?.owner ?? "-" }}</span></div>
        <div class="kv">config_fingerprint <span class="mono copyable" :title="t('sidebar.copyFingerprint', { fp: snap?.config_fingerprint ?? '' })" @click="copy('fp', snap?.config_fingerprint ?? '')">{{ snap?.config_fingerprint ? short(snap.config_fingerprint) : "-" }}</span></div>
        <div class="kv">registry_state <span class="mono">{{ snap?.registry_state ?? "-" }}</span></div>
        <div class="kv">freshness <span class="mono">{{ store.freshness }}</span></div>
        <div class="kv">stale <span class="mono">{{ String(snap?.stale ?? "-") }}</span></div>
        <div class="kv">observed <span class="mono">{{ observedAgoText }}</span></div>
        <div class="kv">{{ t("sidebar.observedAbs") }} <span class="mono">{{ observedAbsText }}</span></div>
        <div class="kv">image <span class="mono">{{ snap?.config.image || "-" }}</span></div>
        <div class="kv">network <span class="mono">{{ snap?.config.network || "-" }}</span></div>
        <div class="kv">scope <span class="mono">{{ snap?.config.scope || "-" }}</span></div>
        <div class="kv">workspace <span class="mono copyable" :title="t('sidebar.copyWorkspace', { path: store.workspace })" @click="copy('ws', store.workspace)">{{ store.workspace || "-" }}</span></div>
        <template v-if="providerStatus">
          <div class="kv">provider_id <span class="mono copyable" :title="t('sidebar.copyProvider', { id: providerStatus.provider_id })" @click="copy('pid', providerStatus.provider_id)">{{ providerStatus.provider_id || "-" }}</span></div>
          <div class="kv">provider_name <span class="mono">{{ providerStatus.provider_name || "-" }}</span></div>
          <div class="kv">route <span class="mono">{{ providerStatus.route_mode || "-" }}</span></div>
          <div class="kv">auth <span class="mono" :data-auth="providerStatus.auth_status">{{ providerStatus.auth_status || "-" }}</span></div>
        </template>
        <!-- G-13 (Step 12): one-click diagnosis from ready details -->
        <button class="diagnose" @click="doctorStore.openDialog()">{{ t("doctor.run") }}</button>
      </div>
    </details>
  </aside>
</template>

<style scoped>
/* 2026-08-18 样式对调：本组件从左侧固定列变右侧悬浮抽屉的内容——填充
 * WorkspaceView 的 .status-drawer（容器画边框/阴影），不再自带固定宽度。 */
.sidebar {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--font-sm);
  overflow-y: auto;
}
.block { display: flex; flex-direction: column; gap: 3px; }
.label { color: var(--text-faint); text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; }
.value { color: var(--text-2); font-size: var(--font-md); word-break: break-all; }
.muted { color: var(--text-muted); }
.copyable { cursor: pointer; transition: color var(--duration-normal) var(--ease); }
.copyable:hover { color: var(--text); }
.copied { color: var(--success); margin-left: 4px; }
.mono { font-family: var(--font-mono); color: var(--info); font-size: var(--font-xs); }
.kv { color: var(--text-muted); display: flex; gap: 6px; flex-wrap: wrap; }
.kv span { color: var(--text-2); word-break: break-all; }
.runtime-row { display: flex; align-items: center; gap: 6px; }
.state { color: var(--text-muted); }
.state[data-state="running"] { color: var(--success); }
.state[data-state="stopped"] { color: var(--warn); }
.state[data-state="starting"], .state[data-state="stopping"] { color: var(--warn); }
.state[data-state="not_found"], .state[data-state="removing"] { color: var(--text-muted); }
/* stale: last-known styling, never deterministic green (04 §2.1) */
.state[data-fresh="stale"] { color: var(--warn); }
.last-known { font-size: 10px; color: var(--warn); }
.actions-row { display: flex; gap: 6px; margin-top: 2px; }
.auth-row { display: flex; align-items: center; gap: 8px; }
.auth { font-size: var(--font-sm); }
.auth[data-auth="configured"] { color: var(--success); }
.auth[data-auth="login_required"], .auth[data-auth="not_configured"] { color: var(--warn-fg); }
.auth[data-auth="unknown"] { color: var(--text-muted); }
.link { background: none; border: none; color: var(--info); padding: 0; font-size: var(--font-xs); cursor: pointer; text-decoration: underline; }
.sessions-btn {
  background: none; border: none; color: var(--text-2); padding: 0; text-align: left;
  font-size: var(--font-md); cursor: pointer;
}
.sessions-btn:hover { color: var(--text); }
.mini { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.mini li { display: flex; align-items: center; gap: 6px; min-height: 24px; padding: 0 6px; cursor: pointer; border-radius: var(--radius-sm); transition: background-color var(--duration-normal) var(--ease); }
.mini li:hover { background: var(--surface-hover); }
.mini li.active { background: var(--accent-soft); }
.t-title { color: var(--text-2); }
.t-state { font-size: 10px; color: var(--text-muted); margin-left: auto; }
.t-state[data-state="running"] { color: var(--success); }
.t-state[data-state="starting"], .t-state[data-state="closing"] { color: var(--warn); }
.t-state[data-state="failed"] { color: var(--error); }
.details { margin-top: auto; }
.details summary { cursor: pointer; user-select: none; }
.diagnose { background: var(--info-bg); border-color: var(--info-border); color: var(--text); margin-top: 8px; }
.dev { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--control-h-sm);
  padding: 0 var(--space-3);
  background: var(--surface-3); color: var(--text-2);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}
button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
button:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
button:disabled { opacity: 0.45; cursor: default; }
button.danger { background: var(--error-bg); border-color: var(--error-border); color: var(--error-fg); }
.err { font-size: var(--font-xs); color: var(--error); }
</style>
