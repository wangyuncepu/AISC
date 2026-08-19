<script setup lang="ts">
/**
 * Stage 5 (ONB-01/02/03/04): first-run wizard route shell + environment +
 * workspace + agent steps.
 *
 * 5a shell (begin/skip/finished); 5c environment readiness; 5d workspace
 * selection/recents (reusing the runtime store) and Agent readiness mapping
 * (ready / needs_login / needs_configuration / unsupported, never secrets).
 * Network / runtime / complete steps are added by 5e-5g.
 */
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useOnboardingStore } from "../../stores/onboarding";
import { useEnvironmentStore } from "../../stores/environment";
import { useRuntimeStore } from "../../stores/runtime";
import { useNetworkStore } from "../../stores/network";
import { useUsageStore } from "../../stores/usage";
import SubscriptionForm from "../usage/SubscriptionForm.vue";

const { t } = useI18n();
const onboarding = useOnboardingStore();
const environment = useEnvironmentStore();
const runtime = useRuntimeStore();
const network = useNetworkStore();

onMounted(() => {
  if (!onboarding.loaded) void onboarding.load();
});

onUnmounted(() => environment.stopAutoPoll());

// IDEA-2 (D3): inline subscription import for the container_tun choice.
// The wizard never blocks on it — the form is skippable and the「网络与
// 用量」panel manages the subscription later.
const usageStore = useUsageStore();
const subConfigured = ref<boolean | null>(null);
watch(
  () => (onboarding.state?.current_step === "network" ? network.choice : null),
  (choice) => {
    if (choice === "container_tun" && subConfigured.value === null) {
      void usageStore.refreshSubscriptionStatus().then((configured) => {
        subConfigured.value = configured;
      });
    }
  },
  { immediate: true },
);

// Load readiness once when the wizard reaches the environment step, and keep
// live auto-polling while it is visible (real-time detection — manual test
// 2026-08-16: after Docker starts the step was static).
watch(
  () => onboarding.state?.current_step,
  (step) => {
    if (step === "environment") {
      if (environment.readiness.cli === "unknown") void environment.refresh();
      environment.startAutoPoll();
    } else {
      environment.stopAutoPoll();
    }
  },
  { immediate: true },
);

const step = computed(() => onboarding.state?.current_step || "welcome");
const chosenWorkspace = computed(() => runtime.workspace || "");

async function begin() {
  await onboarding.patch({ status: "in_progress", currentStep: "environment" });
  await environment.refresh();
}

async function skip() {
  await onboarding.patch({ status: "skipped" });
}

// --- environment step (5c) ---

async function startDocker() {
  // Launch (or install, if missing) — awaited so failures surface. Then hand
  // detection to the live auto-poll (5s): first launch of Docker Desktop needs
  // time (WSL 2 init + first-run dialog), and the env step updates the moment
  // the engine answers. No long blocking poll that disables the buttons.
  await environment.startDocker();
  environment.startAutoPoll();
}

async function retryEnv() {
  await environment.refresh();
}

// KI-1 UX (user feedback 2026-08-17): clicking 启动 Docker gave no visible
// outcome — one flicker, then silence until the engine suddenly readied.
// The wake-up now shows a continuous progress banner (spinner + elapsed) and
// a terminal success note when the engine answers.
const dockerBusy = computed(
  () => environment.installing || environment.dockerStarting || environment.polling
);
/** The winget/bundled INSTALL only applies to a missing Docker Desktop; on an
 * installed-not-running machine the same `installing` window is just the
 * spawn (~1-2s) and must read 启动中, not 安装中. */
const dockerInstallingMissing = computed(
  () => environment.installing && environment.readiness.docker === "not_installed"
);
/** Sticky: this wizard session woke Docker up (drives the success note). */
const dockerStartedHere = ref(false);
watch(
  () => environment.dockerStarting,
  (on) => {
    if (on) dockerStartedHere.value = true;
  }
);

// Elapsed-seconds ticker while the wake-up runs (same pattern as the summary
// page's banner).
const nowMs = ref(Date.now());
let dockerTicker: number | null = null;
watch(
  dockerBusy,
  (busy) => {
    if (busy && dockerTicker === null) {
      dockerTicker = window.setInterval(() => (nowMs.value = Date.now()), 1_000);
    } else if (!busy && dockerTicker !== null) {
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
  environment.dockerStartedAt
    ? Math.max(0, Math.floor((nowMs.value - environment.dockerStartedAt) / 1000))
    : 0
);
/** Terminal success signal — the engine answered after OUR wake-up. */
const dockerReadyHere = computed(
  () => dockerStartedHere.value && environment.readiness.engine === "ready"
);

async function continueFromEnv() {
  await onboarding.patch({ completeStep: "environment", currentStep: "workspace" });
}

// --- workspace step (5d, ONB-03) ---

async function pickWorkspace() {
  await runtime.pickWorkspace();
  if (runtime.workspace) await continueFromWorkspace();
}

async function selectRecent(path: string) {
  runtime.selectRecentWorkspace(path);
  await continueFromWorkspace();
}

async function continueFromWorkspace() {
  await onboarding.patch({ completeStep: "workspace", currentStep: "agent" });
}

// --- agent step (5d, ONB-04) ---

/** Map an agent's provider status to a user-facing readiness state. When no
 *  runtime is running (fresh onboarding) the agent is needs_configuration. */
function agentReadiness(agent: "claude" | "codex"): string {
  const st = runtime.providerStatuses?.[agent];
  if (!st) return "needs_configuration";
  switch (st.auth_status) {
    case "configured":
      return "ready";
    case "login_required":
      return "needs_login";
    case "not_configured":
      return "needs_configuration";
    default:
      return "unsupported";
  }
}

async function continueFromAgent() {
  await onboarding.patch({ completeStep: "agent", currentStep: "network" });
}

// --- network step (5e, A-ONB05) ---

function pickNetwork(choice: "direct" | "host_proxy" | "container_tun") {
  network.setChoice(choice);
}

async function probeNetwork() {
  await network.probe();
}

/** Save the confirmed choice to the runtime launch config (container-TUN maps
 *  to the existing `network: "proxy"` setting; host-proxy keeps "direct" and
 *  only affects how the agent reaches the host proxy — no TUN). */
async function confirmNetwork() {
  network.confirm();
  // The runtime's launch.network is "direct" | "proxy"; container-TUN = proxy.
  if (network.choice === "container_tun") {
    runtime.launch.network = "proxy";
  } else {
    runtime.launch.network = "direct";
  }
  await continueFromNetwork();
}

async function continueFromNetwork() {
  await onboarding.patch({ completeStep: "network", currentStep: "runtime" });
}

// --- runtime step (5f, A-ONB06) ---

watch(
  () => onboarding.state?.current_step,
  async (step) => {
    if (step === "runtime" && runtime.preflight === null) {
      await runtime.runPreflight();
    }
  },
  { immediate: true },
);

/** Continue past the runtime step. The actual runtime start happens in the
 *  completion flow (5g) via the runtime store; here we only checkpoint that the
 *  user reviewed preflight/reuse/restart/conflict state. A resolve_conflict is
 *  not completeable until the user re-runs preflight (button disabled). */
async function continueFromRuntime() {
  await onboarding.patch({ completeStep: "runtime", currentStep: "complete" });
}

// --- complete step (5g, A-ONB07) ---

/** Finish onboarding: start the runtime (opens the workspace) and mark
 *  completed. The App.vue gate watches `isFinished` and removes the overlay. */
async function finish() {
  await onboarding.patch({ status: "completed", completeStep: "complete" });
  // Start the runtime into the workspace (opens the first tab). Best-effort:
  // if it fails, onboarding is still complete — the user can use Settings.
  await runtime.startFromSummary();
}
</script>

<template>
  <div class="onboarding" data-testid="onboarding-wizard">
    <h1 class="ob-title">{{ t("onboarding.title") }}</h1>
    <!-- The error is a banner, NOT a dead end: a transient backend failure
         must not brick the wizard by hiding the begin/skip buttons (manual
         test 2026-08-16: "Workbench 配置读取失败" trapped the welcome step). -->
    <p v-if="onboarding.error" class="ob-error" role="alert">{{ onboarding.error }}</p>
    <p v-if="onboarding.isFinished" class="ob-finished" role="status">
      {{ t("onboarding.finished") }}
    </p>

    <!-- Welcome / begin -->
    <template v-else-if="step === 'welcome' || onboarding.status === 'not_started'">
      <p class="ob-subtitle">{{ t("onboarding.subtitle") }}</p>
      <div class="ob-actions">
        <button class="ob-btn primary" @click="begin">{{ t("onboarding.begin") }}</button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
      </div>
    </template>

    <!-- Environment readiness (5c) -->
    <template v-else-if="step === 'environment'">
      <p class="ob-subtitle">{{ t("onboarding.env.title") }}</p>
      <p v-if="environment.error" class="ob-error" role="alert">{{ environment.error }}</p>

      <ul class="ob-check-list">
        <li>
          <span class="ob-check-dot" :data-state="environment.readiness.cli" />
          {{ t("onboarding.env.cli") }}: {{ environment.readiness.cli }}
        </li>
        <li>
          <span class="ob-check-dot" :data-state="environment.readiness.docker" />
          {{ t("onboarding.env.docker") }}: {{ environment.readiness.docker }}
        </li>
        <li>
          <span class="ob-check-dot" :data-state="environment.readiness.engine" />
          {{ t("onboarding.env.engine") }}: {{ environment.readiness.engine }}
        </li>
        <li>
          <span class="ob-check-dot" :data-state="environment.readiness.webview2" />
          {{ t("onboarding.env.webview2") }}: {{ environment.readiness.webview2 }}
        </li>
      </ul>

      <p v-if="dockerInstallingMissing" class="ob-note" role="status">
        {{ t("onboarding.env.installingHint") }}
      </p>
      <!-- KI-1 UX: visible wake-up progress — spinner + elapsed + first-boot
           hint, continuous until the engine answers (no flicker-then-silence). -->
      <p v-else-if="dockerBusy" class="ob-note ob-progress" role="status">
        <span class="spinner" aria-hidden="true" />
        {{ t("onboarding.env.dockerProgress", { sec: dockerElapsedSec }) }}
      </p>
      <p v-else-if="environment.readiness.engine === 'starting'" class="ob-note" role="status">
        {{ t("onboarding.env.startingHint") }}
      </p>
      <!-- Terminal signal for OUR wake-up: green note the moment it readies
           (previously the step just silently unlocked 继续). -->
      <p v-if="dockerReadyHere" class="ob-ready" role="status">
        {{ t("onboarding.env.dockerReadyNote") }}
      </p>
      <!-- KI-1 diagnostic: redacted probe detail so a still-not-ready engine is
           explainable in-place (docker CLI missing / spawn err / exit / timeout). -->
      <p
        v-if="environment.readiness.engine !== 'ready' && environment.readiness.engineDetail"
        class="ob-note ob-engine-detail"
        role="status"
      >{{ t("onboarding.env.engineDetail") }}: {{ environment.readiness.engineDetail }}</p>

      <div class="ob-actions">
        <button
          v-if="environment.dockerInstalling"
          class="ob-btn primary"
          :disabled="dockerBusy"
          @click="startDocker"
        >
          {{ dockerInstallingMissing
            ? t("onboarding.env.installingDocker")
            : dockerBusy
              ? t("onboarding.env.startingDocker")
              : environment.readiness.docker === "not_installed"
                ? t("onboarding.env.installDocker")
                : t("onboarding.env.startDocker") }}
        </button>
        <!-- Never disabled: envReadiness is a cheap idempotent read, and the
             auto-poll already keeps this live. Disabling on `loading` made
             "Re-check" dead ~4s of every 5s (manual test 2026-08-16). -->
        <button class="ob-btn ghost" @click="retryEnv">
          {{ t("onboarding.env.retry") }}
        </button>
        <button
          class="ob-btn primary"
          :disabled="!environment.allReady"
          @click="continueFromEnv"
        >
          {{ t("onboarding.continue") }}
        </button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
      </div>
    </template>

    <!-- Workspace selection (5d, ONB-03) -->
    <template v-else-if="step === 'workspace'">
      <p class="ob-subtitle">{{ t("onboarding.ws.title") }}</p>

      <div v-if="runtime.recentWorkspaces.length" class="ob-recents">
        <button
          v-for="rec in runtime.recentWorkspaces.slice(0, 5)"
          :key="rec.path"
          class="ob-btn ws-recent"
          @click="selectRecent(rec.path)"
        >
          {{ rec.path }}
        </button>
      </div>

      <div class="ob-actions">
        <button class="ob-btn primary" @click="pickWorkspace">{{ t("onboarding.ws.pick") }}</button>
        <button
          v-if="chosenWorkspace"
          class="ob-btn primary"
          :disabled="!chosenWorkspace"
          @click="continueFromWorkspace"
        >
          {{ t("onboarding.continue") }}
        </button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
      </div>
    </template>

    <!-- Agent readiness (5d, ONB-04) -->
    <template v-else-if="step === 'agent'">
      <p class="ob-subtitle">{{ t("onboarding.agent.title") }}</p>

      <ul class="ob-check-list">
        <li>
          <span class="ob-check-dot" :data-state="agentReadiness('claude')" />
          {{ t("onboarding.agent.claude") }}: {{ t(`onboarding.agent.state.${agentReadiness('claude')}`) }}
        </li>
        <li>
          <span class="ob-check-dot" :data-state="agentReadiness('codex')" />
          {{ t("onboarding.agent.codex") }}: {{ t(`onboarding.agent.state.${agentReadiness('codex')}`) }}
        </li>
      </ul>

      <div class="ob-actions">
        <button class="ob-btn primary" @click="continueFromAgent">{{ t("onboarding.continue") }}</button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
      </div>
    </template>

    <!-- Network (5e, A-ONB05) -->
    <template v-else-if="step === 'network'">
      <p class="ob-subtitle">{{ t("onboarding.net.title") }}</p>

      <div class="ob-net-options">
        <button
          class="ob-btn"
          :class="{ active: network.choice === 'direct' }"
          @click="pickNetwork('direct')"
        >{{ t("onboarding.net.direct") }}</button>
        <button
          class="ob-btn"
          :class="{ active: network.choice === 'host_proxy' }"
          @click="pickNetwork('host_proxy')"
        >{{ t("onboarding.net.hostProxy") }}</button>
        <button
          class="ob-btn"
          :class="{ active: network.choice === 'container_tun' }"
          @click="pickNetwork('container_tun')"
        >{{ t("onboarding.net.containerTun") }}</button>
      </div>

      <p class="ob-note">{{ t("onboarding.net.impact") }}</p>
      <p v-if="network.error" class="ob-error" role="alert">{{ network.error }}</p>

      <!-- IDEA-2 (D3): the container TUN choice needs a proxy subscription —
           import inline (URL or pasted content) or skip and configure later
           from the「网络与用量」panel. Never blocks the wizard. -->
      <div v-if="network.choice === 'container_tun'" class="ob-sub-import">
        <p class="ob-note">{{ t("onboarding.net.subNeed") }}</p>
        <p v-if="subConfigured" class="ob-sub-ok">✓ {{ t("onboarding.net.subReady") }}</p>
        <SubscriptionForm v-else @imported="subConfigured = true" />
        <p class="ob-note">{{ t("onboarding.net.subLater") }}</p>
      </div>

      <div class="ob-actions">
        <button class="ob-btn ghost" :disabled="network.probing" @click="probeNetwork">
          {{ network.probing ? t("onboarding.net.probing") : t("onboarding.net.probe") }}
        </button>
        <span v-if="network.probeResult" class="ob-probe" :data-result="network.probeResult">
          {{ network.probeResult === "ok" ? t("onboarding.net.probeOk") : t("onboarding.net.probeFail") }}
        </span>
        <button
          class="ob-btn primary"
          :disabled="network.choice === 'direct' ? false : !network.confirmed"
          @click="confirmNetwork"
        >{{ t("onboarding.continue") }}</button>
        <button class="ob-btn ghost" @click="network.revoke(); continueFromNetwork()">
          {{ t("onboarding.net.skip") }}
        </button>
      </div>

      <!-- Explicit confirm before applying a non-direct choice -->
      <button
        v-if="network.choice !== 'direct' && !network.confirmed"
        class="ob-btn confirm"
        @click="network.confirm()"
      >{{ t("onboarding.net.confirm") }}</button>
    </template>

    <!-- Runtime (5f, A-ONB06) -->
    <template v-else-if="step === 'runtime'">
      <p class="ob-subtitle">{{ t("onboarding.runtime.title") }}</p>
      <p v-if="runtime.error" class="ob-error" role="alert">{{ runtime.error }}</p>

      <template v-if="runtime.preflight">
        <p class="ob-step" role="status">
          {{ t(`onboarding.runtime.action.${runtime.preflight.recommended_action}`) }}
        </p>
        <div v-if="runtime.conflicts.length" class="ob-conflicts">
          <p class="ob-note">{{ t("onboarding.runtime.conflicts") }}</p>
          <p
            v-for="c in runtime.conflicts.slice(0, 3)"
            :key="c.runtime_id"
            class="ob-conflict-row"
          >{{ c.container_name || c.runtime_id }}</p>
        </div>
      </template>

      <div class="ob-actions">
        <button
          class="ob-btn primary"
          :disabled="runtime.status === 'preflight' || runtime.status === 'starting' || runtime.preflight?.recommended_action === 'resolve_conflict'"
          @click="continueFromRuntime"
        >{{ t("onboarding.continue") }}</button>
        <button class="ob-btn ghost" @click="runtime.runPreflight()">{{ t("onboarding.runtime.retry") }}</button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
      </div>
    </template>

    <!-- Complete (5g, A-ONB07) -->
    <template v-else-if="step === 'complete'">
      <p class="ob-subtitle">{{ t("onboarding.complete.title") }}</p>
      <p class="ob-note">{{ t("onboarding.complete.note") }}</p>
      <div class="ob-actions">
        <button class="ob-btn primary" @click="finish">{{ t("onboarding.complete.enter") }}</button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.complete.later") }}</button>
      </div>
    </template>

    <!-- Unknown step fallback -->
    <template v-else>
      <p class="ob-step" role="status">{{ t("onboarding.currentStep", { step }) }}</p>
      <div class="ob-actions">
        <button class="ob-btn primary" @click="skip">{{ t("onboarding.complete.later") }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.onboarding {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  padding: 24px;
  text-align: center;
}
.ob-title { font-size: var(--font-xl); margin: 0; }
.ob-subtitle { color: var(--muted, #888); margin: 0; }
.ob-step { color: var(--text-2); font-size: var(--font-md); margin: 0; }
.ob-error { color: var(--error, var(--status-err)); font-size: var(--font-md); }
.ob-finished { color: var(--muted, #888); }
.ob-actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; justify-content: center; }
.ob-btn { padding: 6px 16px; border-radius: var(--radius-md); border: 1px solid var(--border-strong, #444); background: var(--surface-3, #262626); color: inherit; cursor: pointer; }
.ob-btn.primary { background: var(--accent, #4a9eff); border-color: var(--accent, #4a9eff); color: var(--accent-fg); }
.ob-btn.ghost { background: none; }
.ob-btn:disabled { opacity: 0.5; cursor: default; }
.ob-check-list { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-direction: column; gap: 6px; text-align: left; font-size: var(--font-md); }
.ob-recents { display: flex; flex-direction: column; gap: 4px; max-width: 420px; width: 100%; }
.ws-recent { text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ob-net-options { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.ob-btn.active { border-color: var(--accent, #4a9eff); color: var(--accent, #4a9eff); }
.ob-note { color: var(--muted, #888); font-size: var(--font-sm); max-width: 420px; }
/* KI-1 UX: wake-up progress + terminal success (wizard parity with the
   summary page's banner). */
.ob-progress {
  display: inline-flex; align-items: center; gap: 8px;
  color: var(--info, #4a9eff);
}
.spinner {
  width: 12px; height: 12px; flex-shrink: 0;
  border: 2px solid var(--border-strong, #444);
  border-top-color: var(--info, #4a9eff);
  border-radius: 50%;
  animation: ob-spin 0.9s linear infinite;
}
@keyframes ob-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .spinner { animation-duration: 2.4s; }
}
.ob-ready { color: var(--status-ok); font-size: var(--font-md); }
.ob-engine-detail { font-family: monospace; font-size: var(--font-xs); color: var(--warn); }
.ob-probe[data-result="ok"] { color: var(--status-ok); font-size: var(--font-sm); }
.ob-probe[data-result="failed"] { color: var(--status-err); font-size: var(--font-sm); }

/* IDEA-2 (D3): inline subscription import block (container_tun choice). */
.ob-sub-import {
  display: flex; flex-direction: column; gap: 8px; align-items: flex-start;
  padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
  max-width: 640px; text-align: left;
}
.ob-sub-ok { color: var(--status-ok); font-size: var(--font-sm); }
.ob-btn.confirm { border-color: var(--status-pending); color: var(--status-pending); }
.ob-conflicts { max-width: 420px; }
.ob-conflict-row { color: var(--muted, #888); font-size: var(--font-sm); margin: 2px 0; }
.ob-check-dot { display: inline-block; width: 8px; height: 8px; border-radius: var(--radius-full); margin-right: 8px; background: var(--muted, #888); }
.ob-check-dot[data-state="ready"] { background: var(--status-ok); }
.ob-check-dot[data-state="starting"], .ob-check-dot[data-state="installing"] { background: var(--status-pending); }
.ob-check-dot[data-state="unavailable"], .ob-check-dot[data-state="not_installed"], .ob-check-dot[data-state="missing"], .ob-check-dot[data-state="blocked"] { background: var(--status-err); }
</style>
