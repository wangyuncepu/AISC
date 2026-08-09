<script setup lang="ts">
/**
 * RuntimeSidebar (S2.3.a): always-visible P0 observability for the ready view
 * (04 §二 P0, §四.1). Shows workspace, runtime state + freshness + observed-ago,
 * config (image/network/scope), active agent, exact IDs and the session list.
 * Network/scope come from the runtime snapshot's config (free); provider/route
 * (P1) land in S2.3.b.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import type { RuntimeState } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();

// 1s ticker so "observed Xs ago" stays current without re-polling.
const nowMs = ref(Date.now());
let timer: number | null = null;
onMounted(() => {
  timer = window.setInterval(() => {
    nowMs.value = Date.now();
  }, 1000);
});

// Click-to-copy for exact IDs (hover tooltips can't be selected).
const copiedKey = ref("");
let copiedTimer: number | null = null;
function copy(key: string, text: string): void {
  if (!text) return;
  void navigator.clipboard
    .writeText(text)
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

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
  if (copiedTimer !== null) window.clearTimeout(copiedTimer);
});

const snap = computed(() => store.runtimeSnapshot);

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

const observedAgoText = computed(() => {
  const s = snap.value;
  if (!s || !s.observed_at) return "-";
  const t = Date.parse(s.observed_at);
  if (Number.isNaN(t)) return "-";
  const sec = Math.max(0, Math.floor((nowMs.value - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
});

const activeTab = computed(
  () => store.tabs.find((t) => t.tabId === store.activeTabId) ?? null
);

// S2.3.b: P1 provider (claude/codex only; bash/cc-switch n/a).
const providerSupported = computed(() => store.capability?.provider_status ?? false);
const activeAgent = computed(() => activeTab.value?.agent ?? null);
const providerStatus = computed(() => {
  const a = activeAgent.value;
  if (a === "claude" || a === "codex") return store.providerStatuses[a];
  return null;
});
const providerInFlightLabel = computed(() => {
  const a = activeAgent.value;
  if (a && store.providerInFlight === a) return t("sidebar.loading");
  return t("sidebar.unknown");
});

function short(id: string): string {
  return id.slice(0, 8);
}
</script>

<template>
  <aside class="sidebar" aria-label="Runtime status">
    <section class="block">
      <div class="label">Workspace</div>
      <div class="value" :title="store.workspace">{{ workspaceName }}</div>
    </section>

    <section class="block">
      <div class="label">Runtime</div>
      <div class="runtime-row">
        <span
          class="state"
          :data-state="store.runtimeState"
          :aria-label="`Runtime ${t(STATE_LABEL_KEY[store.runtimeState])}`"
        >{{ t(STATE_LABEL_KEY[store.runtimeState]) }}</span>
        <span class="fresh" :data-fresh="store.freshness">{{ store.freshness }}</span>
      </div>
      <div class="muted">observed {{ observedAgoText }}</div>
      <div
        class="id copyable"
        :title="store.runtimeId ? t('sidebar.copyRuntime', { id: store.runtimeId }) : ''"
        @click="copy('rt', store.runtimeId)"
      >
        id {{ store.runtimeId ? short(store.runtimeId) : "-" }}
        <span v-if="copiedKey === 'rt'" class="copied">{{ t("sidebar.copied") }}</span>
      </div>
      <div
        v-if="snap?.container_name"
        class="id copyable"
        :title="t('sidebar.copyContainer', { name: snap.container_name })"
        @click="copy('ctr', snap!.container_name)"
      >
        ctr {{ snap.container_name }}
        <span v-if="copiedKey === 'ctr'" class="copied">{{ t("sidebar.copied") }}</span>
      </div>
    </section>

    <section class="block">
      <div class="label">Config</div>
      <div class="kv">image <span>{{ snap?.config.image || "-" }}</span></div>
      <div class="kv">network <span>{{ snap?.config.network || "-" }}</span></div>
      <div class="kv">scope <span>{{ snap?.config.scope || "-" }}</span></div>
    </section>

    <section class="block">
      <div class="label">Active agent</div>
      <div class="value">{{ activeTab?.title ?? "No session" }}</div>
    </section>

    <section class="block">
      <div class="label">Provider</div>
      <div v-if="!providerSupported" class="muted">{{ t("sidebar.providerUnsupported") }}</div>
      <div v-else-if="activeAgent !== 'claude' && activeAgent !== 'codex'" class="muted">{{ t("sidebar.providerN/a") }}</div>
      <template v-else>
        <div v-if="providerStatus" class="p-name">{{ providerStatus.provider_name || t("sidebar.unknown") }}</div>
        <div v-else class="muted">{{ providerInFlightLabel }}</div>
        <div v-if="providerStatus" class="kv">route <span>{{ providerStatus.route_mode || "-" }}</span></div>
        <div v-if="providerStatus" class="kv">
          auth <span :data-auth="providerStatus.auth_status">{{ providerStatus.auth_status || "-" }}</span>
        </div>
        <div v-if="store.providerError" class="err">{{ store.providerError.message }}</div>
      </template>
    </section>

    <section class="block sessions">
      <div class="label">Sessions</div>
      <ul>
        <li
          v-for="t in store.tabs"
          :key="t.tabId"
          :class="{ active: t.tabId === store.activeTabId }"
        >
          <span class="t-title">{{ t.title }}</span>
          <span class="t-state" :data-state="t.sessionState">{{ t.sessionState }}</span>
        </li>
      </ul>
    </section>

    <section class="actions">
      <button :disabled="store.inspectInFlight" @click="store.refreshRuntime()">
        {{ store.inspectInFlight ? t("sidebar.refreshing") : t("sidebar.refresh") }}
      </button>
      <button class="danger" @click="store.stopRuntime()">{{ t("sidebar.stopRuntime") }}</button>
    </section>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.id { font-family: monospace; color: #9cdcfe; font-size: 11px; }
.copyable { cursor: pointer; transition: color 0.1s; }
.copyable:hover { color: #fff; }
.copied { color: #4caf50; margin-left: 4px; }
.kv { color: #888; }
.kv span { color: #ccc; }
.p-name { color: #ddd; font-size: 13px; word-break: break-all; }
.err { color: #e57373; font-size: 11px; }
.kv span[data-auth="configured"] { color: #4caf50; }
.kv span[data-auth="login_required"], .kv span[data-auth="not_configured"] { color: #cca84a; }
.kv span[data-auth="unknown"] { color: #888; }
.runtime-row { display: flex; align-items: center; gap: 8px; }
.state {
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}
.state[data-state="running"] { color: #4caf50; background: #1e3a1e; }
.state[data-state="stopped"] { color: #cca84a; background: #3a331e; }
.state[data-state="not_found"] { color: #e57373; background: #3a1e1e; }
.state[data-state="unknown"] { color: #888; background: #333; }
.state[data-state="starting"], .state[data-state="stopping"], .state[data-state="removing"] {
  color: #6db4e0; background: #1e2e3a;
}
.fresh { font-size: 11px; }
.fresh[data-fresh="fresh"] { color: #4caf50; }
.fresh[data-fresh="stale"] { color: #cca84a; }
.fresh[data-fresh="unknown"] { color: #888; }
.sessions ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }
.sessions li {
  display: flex; justify-content: space-between; align-items: center;
  padding: 2px 4px; border-radius: 3px;
}
.sessions li.active { background: #2d2d2d; }
.t-title { color: #ccc; }
.t-state { font-size: 10px; color: #777; }
.t-state[data-state="running"] { color: #4caf50; }
.t-state[data-state="exited"], .t-state[data-state="disconnected"] { color: #888; }
.t-state[data-state="failed"] { color: #e57373; }
.t-state[data-state="starting"], .t-state[data-state="closing"] { color: #cca84a; }
.actions { margin-top: auto; display: flex; flex-direction: column; gap: 6px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 10px; font-size: 12px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.5; cursor: default; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
button.danger:hover:not(:disabled) { background: #6e3a3a; }
</style>
