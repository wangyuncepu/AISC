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
import { computed, onMounted, onUnmounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useOnboardingStore } from "../../stores/onboarding";
import { useEnvironmentStore } from "../../stores/environment";
import { useRuntimeStore } from "../../stores/runtime";
import { useNetworkStore } from "../../stores/network";

const { t } = useI18n();
const onboarding = useOnboardingStore();
const environment = useEnvironmentStore();
const runtime = useRuntimeStore();
const network = useNetworkStore();

onMounted(() => {
  if (!onboarding.loaded) void onboarding.load();
});

onUnmounted(() => environment.stopAutoPoll());

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

      <p v-if="environment.installing" class="ob-note" role="status">
        {{ t("onboarding.env.installingHint") }}
      </p>
      <p v-else-if="environment.readiness.engine === 'starting'" class="ob-note" role="status">
        {{ t("onboarding.env.startingHint") }}
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
          :disabled="environment.polling || environment.installing"
          @click="startDocker"
        >
          {{ environment.installing
            ? t("onboarding.env.installingDocker")
            : environment.polling
              ? t("onboarding.env.starting")
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
.ob-engine-detail { font-family: monospace; font-size: var(--font-xs); color: var(--warn); }
.ob-probe[data-result="ok"] { color: var(--status-ok); font-size: var(--font-sm); }
.ob-probe[data-result="failed"] { color: var(--status-err); font-size: var(--font-sm); }
.ob-btn.confirm { border-color: var(--status-pending); color: var(--status-pending); }
.ob-conflicts { max-width: 420px; }
.ob-conflict-row { color: var(--muted, #888); font-size: var(--font-sm); margin: 2px 0; }
.ob-check-dot { display: inline-block; width: 8px; height: 8px; border-radius: var(--radius-full); margin-right: 8px; background: var(--muted, #888); }
.ob-check-dot[data-state="ready"] { background: var(--status-ok); }
.ob-check-dot[data-state="starting"], .ob-check-dot[data-state="installing"] { background: var(--status-pending); }
.ob-check-dot[data-state="unavailable"], .ob-check-dot[data-state="not_installed"], .ob-check-dot[data-state="missing"], .ob-check-dot[data-state="blocked"] { background: var(--status-err); }
</style>
