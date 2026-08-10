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
import { useDoctorStore } from "../../stores/doctor";
import { i18n as i18nLocale } from "../../i18n";
import type { RuntimeState } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();
const doctorStore = useDoctorStore();

const snap = computed(() => store.runtimeSnapshot);

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

/** Semantic keys (04 §4.2): stable key -> untouched DOM subtree. */
const runtimeKey = computed(
  () => `${snap.value?.state ?? "none"}|${store.freshness}|${store.runtimeState}`
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
    `${snap.value?.runtime_id}|${activeAgent.value ?? "none"}|${providerStatus.value?.provider_name ?? ""}|${providerStatus.value?.route_mode ?? ""}|${providerStatus.value?.auth_status ?? ""}|${store.freshness}`
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
        <button class="danger" @click="store.stopRuntime()">{{ t("sidebar.stopRuntime") }}</button>
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
          <span class="t-state" :data-state="x.sessionState">{{ x.sessionState }}</span>
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
.sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: #252526;
  border-right: 1px solid #333;
  color: #ccc;
  font-size: 12px;
  overflow-y: auto;
}
.block { display: flex; flex-direction: column; gap: 3px; }
.label { color: #6a6a6a; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; }
.value { color: #ddd; font-size: 13px; word-break: break-all; }
.muted { color: #777; }
.copyable { cursor: pointer; transition: color 0.1s; }
.copyable:hover { color: #fff; }
.copied { color: #4caf50; margin-left: 4px; }
.mono { font-family: monospace; color: #9cdcfe; font-size: 11px; }
.kv { color: #888; display: flex; gap: 6px; flex-wrap: wrap; }
.kv span { color: #ccc; word-break: break-all; }
.runtime-row { display: flex; align-items: center; gap: 6px; }
.state { color: #888; }
.state[data-state="running"] { color: #4caf50; }
.state[data-state="stopped"] { color: #e0a868; }
.state[data-state="starting"], .state[data-state="stopping"] { color: #cca84a; }
.state[data-state="not_found"], .state[data-state="removing"] { color: #888; }
/* stale: last-known styling, never deterministic green (04 §2.1) */
.state[data-fresh="stale"] { color: #e0a868; }
.last-known { font-size: 10px; color: #e0a868; }
.actions-row { display: flex; gap: 6px; margin-top: 2px; }
.auth-row { display: flex; align-items: center; gap: 8px; }
.auth { font-size: 12px; }
.auth[data-auth="configured"] { color: #4caf50; }
.auth[data-auth="login_required"], .auth[data-auth="not_configured"] { color: #e0c97a; }
.auth[data-auth="unknown"] { color: #888; }
.link { background: none; border: none; color: #9cdcfe; padding: 0; font-size: 11px; cursor: pointer; text-decoration: underline; }
.sessions-btn {
  background: none; border: none; color: #ddd; padding: 0; text-align: left;
  font-size: 13px; cursor: pointer;
}
.sessions-btn:hover { color: #fff; }
.mini { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.mini li { display: flex; gap: 6px; padding: 2px 4px; cursor: pointer; border-radius: 3px; }
.mini li:hover { background: #2d2d2d; }
.mini li.active { background: #1e1e1e; }
.t-title { color: #ddd; }
.t-state { font-size: 10px; color: #777; margin-left: auto; }
.t-state[data-state="running"] { color: #4caf50; }
.t-state[data-state="starting"], .t-state[data-state="closing"] { color: #cca84a; }
.t-state[data-state="failed"] { color: #e57373; }
.details { margin-top: auto; }
.details summary { cursor: pointer; user-select: none; }
.diagnose { background: #2d3a4a; border-color: #3a4a5a; margin-top: 8px; }
.dev { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 4px 10px; font-size: 12px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
.err { font-size: 11px; color: #e57373; }
</style>
