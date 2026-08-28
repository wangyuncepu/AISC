<script setup lang="ts">
/** Launch summary (02 §七): preflight gate + inferred config + Start/Change/Cancel. */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkspacesStore } from "../../stores/workspaces";
import { useUsageStore } from "../../stores/usage";
import PreflightGate from "./PreflightGate.vue";

const { t } = useI18n();
const store = useRuntimeStore();
const ws = useWorkspacesStore();
const usageStore = useUsageStore();

// IDEA-2 (2d): proxy mode with no imported subscription mounts nothing (the
// entrypoint silently skips mihomo). Hint + jump to the「网络与用量」panel.
const subConfigured = ref<boolean | null>(null);
watch(
  () => store.launch.network,
  (network) => {
    if (network === "proxy" && subConfigured.value === null) {
      void usageStore.refreshSubscriptionStatus().then((configured) => {
        subConfigured.value = configured;
      });
    }
  },
  { immediate: true },
);
const proxyNoSub = computed(
  () => store.launch.network === "proxy" && store.showAdvanced && subConfigured.value === false,
);

const ACTION_KEY: Record<string, string> = {
  start: "summary.action.start",
  reuse: "summary.action.reuse",
  restart: "summary.action.restart",
  resolve_conflict: "summary.action.conflict",
};
const action = computed(() => store.preflight?.recommended_action ?? "start");
const actionText = computed(() => t(ACTION_KEY[action.value] ?? action.value));

function checkStatus(id: string): string {
  return store.preflight?.checks.find((c) => c.id === id)?.status ?? "pass";
}

const hardBlocking = computed(() => checkStatus("docker") === "fail" || checkStatus("workspace") === "fail");
const dockerDown = computed(() => checkStatus("docker") === "fail");
/** Genuinely missing image (error_code IMAGE_NOT_FOUND, not Docker-unreachable).
 * G-14 (2026-08-10 bugfix): unlike imageMissing this ignores recommended_action,
 * so a matching existing runtime (action=reuse) does NOT hide the build button -
 * the gate would show 镜像失败 with no recovery path. */
const imageNotFound = computed(() => {
  const c = store.preflight?.checks.find((c) => c.id === "image");
  return c?.status === "fail" && c?.error_code === "AISC_ERR_IMAGE_NOT_FOUND";
});
/** Missing image on a non-reuse path - disables Start (reuse keeps the existing
 * container, so a missing tag does not block it). */
const imageMissing = computed(() => checkStatus("image") === "fail" && action.value !== "reuse");
const startEnabled = computed(
  () =>
    !!store.preflight &&
    ["start", "reuse", "restart"].includes(action.value) &&
    !hardBlocking.value &&
    !imageMissing.value
);

function changeSettings() {
  store.showAdvanced = !store.showAdvanced;
}

function onConfigChanged() {
  store.recomputePreflightNeeded();
}

// KI-1 UX: elapsed-seconds ticker for the Docker boot banner — a visible
// heartbeat while the engine comes up (user feedback 2026-08-17: silence for
// 30-60s read as "nothing happened").
const nowMs = ref(Date.now());
let dockerTicker: number | null = null;
watch(
  () => store.dockerStarting,
  (on) => {
    if (on && dockerTicker === null) {
      dockerTicker = window.setInterval(() => (nowMs.value = Date.now()), 1_000);
    } else if (!on && dockerTicker !== null) {
      window.clearInterval(dockerTicker);
      dockerTicker = null;
    }
  },
  { immediate: true }
);
onBeforeUnmount(() => {
  if (dockerTicker !== null) window.clearInterval(dockerTicker);
});
const dockerElapsedSec = computed(() =>
  store.dockerStartedAt ? Math.max(0, Math.floor((nowMs.value - store.dockerStartedAt) / 1000)) : 0
);
</script>

<template>
  <div class="summary">
    <h2>{{ t("summary.title") }}</h2>
    <PreflightGate v-if="store.preflight" :report="store.preflight" />

    <div class="row"><span class="k">{{ t("summary.kWorkspace") }}</span><span class="v">{{ store.workspace }}</span></div>
    <!-- G-08 (A-G08-1): no initial-agent picker; a fresh Start opens one Bash
         tab, more tabs are created dynamically via the + menu. -->
    <div class="row"><span class="k">{{ t("summary.kRuntime") }}</span><span class="v">{{ actionText }}</span></div>

    <div v-if="store.showAdvanced" class="advanced">
      <div class="row">
        <span class="k">{{ t("summary.kImage") }}</span>
        <input v-model="store.launch.image" @change="onConfigChanged" />
      </div>
      <div class="row">
        <span class="k">{{ t("summary.kNetwork") }}</span>
        <select v-model="store.launch.network" @change="onConfigChanged">
          <option value="direct">{{ t("summary.network.direct") }}</option>
          <option value="proxy">{{ t("summary.network.proxy") }}</option>
        </select>
      </div>
      <div class="row">
        <span class="k">{{ t("summary.kScope") }}</span>
        <select v-model="store.launch.scope" @change="onConfigChanged">
          <option value="project">{{ t("summary.scope.project") }}</option>
          <option value="temporary">{{ t("summary.scope.temporary") }}</option>
        </select>
      </div>
      <!-- IDEA-2 (2d): proxy without a subscription = TUN caps with nothing
           mounted (mihomo silently skipped). Non-blocking hint + jump. -->
      <p v-if="proxyNoSub" class="gate-msg config sub-hint" role="status">
        {{ t("summary.proxyNoSub") }}
        <button class="linklike" @click="ws.openNetworkUsageTab()">
          {{ t("summary.configureSub") }}
        </button>
      </p>
    </div>

    <p v-if="imageNotFound" class="gate-msg config">{{ t("summary.imageMissing") }}</p>
    <!-- KI-1 UX: boot progress banner (spinner + elapsed) while the wake-up
         loop probes quietly; the red gate message only returns once it ends
         without success (timeout re-shows via the error path). -->
    <p v-if="store.dockerStarting" class="gate-msg docker-progress" role="status">
      <span class="spinner" aria-hidden="true" />
      {{ t("summary.dockerProgress", { sec: dockerElapsedSec }) }}
    </p>
    <p v-else-if="dockerDown" class="gate-msg hard">
      {{ t("summary.dockerDown") }}
    </p>
    <p v-else-if="hardBlocking" class="gate-msg hard">{{ t("summary.hardBlocked") }}</p>
    <p v-else-if="action === 'resolve_conflict'" class="gate-msg hard">{{ t("summary.conflictGate") }}</p>

    <!-- runtime-lifecycle-ux Stage 4 (01 §1.2): reconcile recycled a leftover
         runtime before this summary — state it once, non-blocking. -->
    <p v-if="store.reconcile?.cleanup?.attempted" class="gate-msg recycled" role="status">
      {{ t("summary.reconcileRecycled") }}
    </p>

    <div class="actions">
      <button class="primary" :disabled="!startEnabled" @click="store.startFromSummary()">{{ t("summary.start") }}</button>
      <button v-if="dockerDown" class="primary" :disabled="store.dockerStarting" @click="store.startDockerAndRepreflight()">
        {{ store.dockerStarting ? t("summary.startingDocker") : t("summary.startDocker") }}
      </button>
      <button @click="changeSettings">{{ store.showAdvanced ? t("summary.toggleSettings") : t("summary.changeSettings") }}</button>
      <button v-if="imageNotFound" class="danger" @click="store.startBuild(store.launch.image)">{{ t("summary.buildImage") }}</button>
      <button @click="store.backToPicker()">{{ t("summary.cancel") }}</button>
    </div>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  color: var(--text-2);
  overflow: auto;
}
h2 { margin: 0 0 4px; font-size: 15px; }
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: var(--font-md);
}
.k { width: 90px; color: var(--text-muted); }
.v { color: var(--text-2); word-break: break-all; }
input, select {
  background: var(--surface);
  color: var(--text-2);
  border: 1px solid var(--border-2);
  border-radius: var(--radius-md);
  padding: 4px 6px;
  font-size: var(--font-md);
  flex: 1;
  min-width: 0;
}
.advanced {
  padding: 8px;
  background: var(--surface);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gate-msg { font-size: var(--font-sm); padding: 6px 8px; border-radius: var(--radius-md); margin: 0; }
.gate-msg.config { background: var(--warn-bg); color: var(--warn-fg); }
.gate-msg.hard { background: var(--error-bg); color: var(--error-fg); }
.gate-msg.resume { background: var(--info-bg); color: var(--info); }
/* KI-1 UX: Docker boot progress — visible heartbeat, not a silent wait. */
.gate-msg.docker-progress {
  background: var(--info-bg); color: var(--info);
  display: flex; align-items: center; gap: 8px;
}
.spinner {
  width: 12px; height: 12px; flex-shrink: 0;
  border: 2px solid var(--info-border);
  border-top-color: var(--info);
  border-radius: 50%;
  animation: docker-spin 0.9s linear infinite;
}
@keyframes docker-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .spinner { animation-duration: 2.4s; }
}
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); color: var(--text-2); border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  padding: 0 var(--space-3); font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
button:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
button.danger { background: var(--error-bg); border-color: var(--error-border); color: var(--error-fg); }
button.danger:hover:not(:disabled) { background: var(--error-hover); }
</style>
