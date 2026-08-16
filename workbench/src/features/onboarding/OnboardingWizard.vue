<script setup lang="ts">
/**
 * Stage 5 (ONB-01): first-run wizard route shell.
 *
 * Minimal state-routing shell for 5a: mounts when onboarding isn't finished,
 * renders the current step from the store, and provides Begin / Skip actions
 * that checkpoint through the backend. Concrete steps (environment, workspace,
 * agent, network, runtime, complete) are filled in by 5c-5g.
 */
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useOnboardingStore } from "../../stores/onboarding";

const { t } = useI18n();
const onboarding = useOnboardingStore();

onMounted(() => {
  if (!onboarding.loaded) void onboarding.load();
});

async function begin() {
  await onboarding.patch({ status: "in_progress", currentStep: "environment" });
}

async function skip() {
  await onboarding.patch({ status: "skipped" });
}
</script>

<template>
  <div class="onboarding" data-testid="onboarding-wizard">
    <h1 class="ob-title">{{ t("onboarding.title") }}</h1>
    <p v-if="onboarding.error" class="ob-error" role="alert">{{ onboarding.error }}</p>
    <p v-else-if="onboarding.isFinished" class="ob-finished" role="status">
      {{ t("onboarding.finished") }}
    </p>
    <template v-else>
      <p class="ob-subtitle">{{ t("onboarding.subtitle") }}</p>
      <p class="ob-step" role="status">{{ t("onboarding.currentStep", { step: onboarding.state?.current_step || "welcome" }) }}</p>
      <div class="ob-actions">
        <button v-if="onboarding.status === 'not_started'" class="ob-btn primary" @click="begin">
          {{ t("onboarding.begin") }}
        </button>
        <button v-else class="ob-btn primary" disabled>{{ t("onboarding.continue") }}</button>
        <button class="ob-btn ghost" @click="skip">{{ t("onboarding.skip") }}</button>
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
.ob-title { font-size: 20px; margin: 0; }
.ob-subtitle { color: var(--muted, #888); margin: 0; }
.ob-step { color: var(--text-2); font-size: 13px; margin: 0; }
.ob-error { color: var(--error, #e5534b); font-size: 13px; }
.ob-finished { color: var(--muted, #888); }
.ob-actions { display: flex; gap: 8px; margin-top: 8px; }
.ob-btn { padding: 6px 16px; border-radius: 4px; border: 1px solid var(--border-strong, #444); background: var(--surface-3, #262626); color: inherit; cursor: pointer; }
.ob-btn.primary { background: var(--accent, #4a9eff); border-color: var(--accent, #4a9eff); color: #fff; }
.ob-btn.ghost { background: none; }
</style>
