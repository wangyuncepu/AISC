<script setup lang="ts">
/** v2.1.7 S4: progress-first build view (Gate-S4 §1).
 *  The structured build.progress facts drive a determinate/indeterminate
 *  bar; the raw docker output lives in a collapsed tail-log drawer (bounded
 *  ring in the store; the complete log opens from buildLogPath). The view
 *  never parses build.output itself. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();
const logEl = ref<HTMLPreElement | null>(null);
const elapsedMs = ref(0);
let timer: number | null = null;
const logOpen = ref(false);

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

const progress = computed(() => store.buildProgress);
const phaseText = computed(() =>
  progress.value ? t(`build.phase.${progress.value.phase}`) : t("build.phase.prepare"),
);
const summary = computed(() => progress.value?.summary ?? "");
const stepsText = computed(() => {
  const p = progress.value;
  if (!p || p.step_current == null || p.step_total == null) return "";
  return t("build.steps", { c: p.step_current, t: p.step_total });
});
/** Determinate bar percent; the terminal complete state owns 100. */
const barPercent = computed(() => {
  if (store.buildStatus === "complete") return 100;
  const p = progress.value;
  if (!p || p.progress_kind !== "determinate" || p.percent == null) return null;
  return p.percent;
});
const determinate = computed(() => barPercent.value !== null);
const percentLabel = computed(() =>
  barPercent.value == null ? "" : `${Math.floor(barPercent.value)}%`,
);
const building = computed(() => store.buildStatus === "building");

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

// Auto-scroll the tail log to the bottom on new output while the drawer is
// open (closed = zero DOM cost for huge logs, A-21748).
watch(
  () => store.buildLog,
  () => {
    if (!logOpen.value) return;
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

    <!-- progress-first card (S4) -->
    <div class="card" :data-terminal="!building">
      <div class="p-row">
        <span v-if="determinate" class="pct">{{ percentLabel }}</span>
        <span v-else class="pct pulsing">…</span>
        <span class="phase">{{ building ? phaseText : statusText }}</span>
        <span v-if="stepsText" class="steps">{{ stepsText }}</span>
      </div>
      <div class="bar" :class="{ indeterminate: !determinate, running: building }">
        <div v-if="determinate" class="fill" :style="{ width: `${barPercent}%` }" />
      </div>
      <p v-if="summary && building" class="summary" :title="summary">{{ summary }}</p>
      <!-- S8c (VM retest feedback #3): set the wait expectation — a cold
           first build downloads base images and installs dependencies. -->
      <p v-if="building" class="hint">{{ t("build.durationHint") }}</p>
    </div>

    <!-- S8b: degraded-but-continuing notices (e.g. offline unpinned build). -->
    <p v-for="(w, i) in store.buildWarnings" :key="i" class="warn" role="status">{{ w }}</p>

    <p v-if="store.buildError" class="err">{{ store.buildError.message }}</p>
    <!-- S8b: the failure's real diagnosis (backend detail, e.g. the cc-switch
         network guidance) — never only the generic headline. -->
    <p v-if="store.buildError?.technical_detail" class="err detail">{{ store.buildError.technical_detail }}</p>
    <p v-if="dockerError" class="err">{{ t("build.dockerError") }}</p>

    <div class="actions">
      <button v-if="building" class="danger" @click="store.cancelBuild()">{{ t("build.cancel") }}</button>
      <template v-else>
        <button v-if="dockerError" class="primary" :disabled="store.dockerStarting" @click="store.startDockerAndRepreflight()">
          {{ store.dockerStarting ? t("summary.startingDocker") : t("summary.startDocker") }}
        </button>
        <button class="primary" @click="store.backToSummaryFromBuild()">{{ t("build.backToSummary") }}</button>
      </template>
    </div>

    <!-- raw output as a collapsed drawer (A-21748: bounded tail here; the
         complete log opens from the file the backend named). -->
    <div class="drawer">
      <div class="drawer-bar">
        <button class="quiet" @click="logOpen = !logOpen">
          {{ logOpen ? t("build.hideLog") : t("build.showLog") }}
        </button>
        <button v-if="store.buildLogPath" class="quiet" @click="store.revealBuildLog()">
          {{ t("build.openFullLog") }}
        </button>
      </div>
      <pre v-show="logOpen" ref="logEl" class="log">{{ store.buildLog || t("build.logEmpty") }}</pre>
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

/* --- progress card (S4) --- */
.card {
  display: flex; flex-direction: column; gap: var(--space-2);
  padding: var(--space-4);
  background: var(--surface-2);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-md);
}
.card[data-terminal="true"] { opacity: 0.85; }
.p-row { display: flex; align-items: baseline; gap: var(--space-3); }
.pct {
  font-size: calc(var(--font-xl) * 1.8); /* hero percent; stays on the token ramp */
  font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums;
}
.pct.pulsing { animation: pulse 1.2s ease-in-out infinite; color: var(--text-muted); }
@keyframes pulse { 50% { opacity: 0.4; } }
.phase { font-size: var(--font-md); color: var(--text-2); font-weight: 600; }
.steps { margin-left: auto; font-size: var(--font-sm); color: var(--text-muted); font-variant-numeric: tabular-nums; }
.bar {
  height: 8px; border-radius: var(--radius-sm);
  background: var(--surface-3); overflow: hidden; position: relative;
}
.bar .fill {
  height: 100%; border-radius: var(--radius-sm);
  background: var(--accent); transition: width var(--duration-normal) var(--ease);
}
.bar.indeterminate.running::after {
  content: ""; position: absolute; inset: 0; width: 30%;
  border-radius: var(--radius-sm); background: var(--accent);
  animation: slide 1.4s ease-in-out infinite;
}
@keyframes slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(433%); }
}
.summary {
  margin: 0; font-family: var(--font-mono); font-size: var(--font-xs);
  color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hint {
  margin: 0; font-size: var(--font-xs); color: var(--text-muted);
}
@media (prefers-reduced-motion: reduce) {
  .pct.pulsing, .bar.indeterminate.running::after { animation: none; }
  .bar.indeterminate.running::after { width: 100%; opacity: 0.35; }
}

.err { font-size: var(--font-sm); color: var(--error); margin: 0; }
.err.detail {
  font-size: var(--font-xs);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  opacity: 0.85;
}
.warn { font-size: var(--font-sm); color: var(--warn); margin: 0; overflow-wrap: anywhere; }
.actions { display: flex; gap: 8px; }

.drawer { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 4px; }
.drawer-bar { display: flex; gap: 8px; }
.log {
  flex: 1; min-height: 0;
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
button.quiet { background: transparent; color: var(--text-muted); }
button.quiet:hover:not(:disabled) { color: var(--text); background: var(--surface-hover); }
button:disabled { opacity: 0.45; cursor: default; }
</style>
