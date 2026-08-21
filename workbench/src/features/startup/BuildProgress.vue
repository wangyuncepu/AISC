<script setup lang="ts">
/** Build progress (02 §四, 05 §4.1): opaque build.output log + Cancel.
 *  In-memory only, not parsed for percentage (05 §4.1.3/§4.1.5). */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();
const logEl = ref<HTMLPreElement | null>(null);
const elapsedMs = ref(0);
let timer: number | null = null;

const STATUS_KEY: Record<string, string> = {
  building: "build.building",
  complete: "build.complete",
  failed: "build.failed",
  cancelled: "build.cancelled",
  idle: "",
};
const statusText = computed(() => (STATUS_KEY[store.buildStatus] ? t(STATUS_KEY[store.buildStatus]) : ""));
// G-14 (Step 13): live tick while building; frozen store duration after the
// first settle - never grows again (A-G14-1/4). Timing is store-owned; the
// component only renders it.
const elapsedSec = computed(() => {
  if (store.buildStatus === "building") return (elapsedMs.value / 1000).toFixed(1);
  return ((store.buildDurationMs ?? 0) / 1000).toFixed(1);
});
const dockerError = computed(
  () => store.buildError?.code === "AISC_ERR_DOCKER_UNAVAILABLE"
);

function stopTimer(): void {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}
function startTimer(): void {
  if (timer !== null) return;
  timer = window.setInterval(() => {
    elapsedMs.value = Date.now() - (store.buildStartedAt ?? Date.now());
  }, 200);
}
onMounted(() => {
  if (store.buildStatus === "building") startTimer();
});
onBeforeUnmount(stopTimer);
// A-G14-4: the elapsed timer stops at the first settle (complete/failed/
// cancelled); leaving and returning shows the frozen value.
watch(
  () => store.buildStatus,
  (s) => {
    if (s === "building") startTimer();
    else stopTimer();
  }
);

// Auto-scroll the log to the bottom on new output.
watch(
  () => store.buildLog,
  () => {
    nextTick(() => {
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight;
    });
  }
);
</script>

<template>
  <div class="build">
    <div class="head">
      <span class="title">{{ t("build.title", { tag: store.buildTag }) }}</span>
      <span class="state" :data-state="store.buildStatus">{{ statusText }}</span>
      <span v-if="store.buildStatus !== 'idle'" class="elapsed">{{ elapsedSec }}s</span>
    </div>
    <pre ref="logEl" class="log">{{ store.buildLog || t("build.logEmpty") }}</pre>
    <p v-if="store.buildError" class="err">{{ store.buildError.message }}</p>
    <p v-if="dockerError" class="err">{{ t("build.dockerError") }}</p>
    <div class="actions">
      <button v-if="store.buildStatus === 'building'" class="danger" @click="store.cancelBuild()">Cancel</button>
      <template v-else>
        <button v-if="dockerError" class="primary" :disabled="store.dockerStarting" @click="store.startDockerAndRepreflight()">
          {{ store.dockerStarting ? t("summary.startingDocker") : t("summary.startDocker") }}
        </button>
        <button class="primary" @click="store.backToSummaryFromBuild()">{{ t("build.backToSummary") }}</button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.build {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px;
  gap: 8px;
  color: var(--text-2);
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: var(--font-md);
}
.title { font-weight: 600; }
.state { font-size: var(--font-sm); color: var(--text-muted); }
.elapsed { font-size: var(--font-sm); color: var(--text-muted); margin-left: auto; }
.state[data-state="complete"] { color: var(--success); }
.state[data-state="failed"], .state[data-state="cancelled"] { color: var(--error); }
.log {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  padding: 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-family: monospace;
  font-size: var(--font-sm);
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-2);
}
.err { font-size: var(--font-sm); color: var(--error); margin: 0; }
.actions { display: flex; gap: 8px; }
button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); color: var(--text-2); border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  padding: 0 var(--space-3); font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
button.primary { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
button.danger { background: var(--error-bg); border-color: var(--error-border); color: var(--error-fg); }
button.danger:hover:not(:disabled) { background: var(--error-hover); }
button:disabled { opacity: 0.45; cursor: default; }
</style>
