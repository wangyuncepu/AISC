/**
 * Onboarding store (Stage 5, ONB-01).
 *
 * The Rust backend is the authoritative source: it persists a schema-versioned
 * `onboarding.json` (status/current/completed/skipped steps, last error code,
 * handoff source) and never stores secrets (D5-05). This store loads it, holds
 * a working copy, and sends validated patches. `onboardingLoad`/`onboardingUpdate`
 * keep the backend and UI in sync; corrupt/high-version files fail closed.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as ipc from "../lib/ipc";
import type { OnboardingPatch, OnboardingState } from "../types";

export const useOnboardingStore = defineStore("onboarding", () => {
  const state = ref<OnboardingState | null>(null);
  const loaded = ref(false);
  const error = ref<string | null>(null);

  const status = computed(() => state.value?.status ?? "not_started");
  /** True when the wizard is finished (completed/skipped/abandoned). */
  const isFinished = computed(
    () =>
      state.value?.status === "completed" ||
      state.value?.status === "skipped" ||
      state.value?.status === "abandoned",
  );
  const isInProgress = computed(() => state.value?.status === "in_progress");

  async function load(): Promise<void> {
    try {
      state.value = await ipc.onboardingLoad();
      loaded.value = true;
      error.value = null;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      loaded.value = true; // fail-closed: UI can still show a fresh-wizard path
    }
  }

  /** Apply a validated patch; the backend returns the authoritative state. */
  async function patch(p: OnboardingPatch): Promise<boolean> {
    if (!state.value) await load();
    try {
      state.value = await ipc.onboardingUpdate(p);
      error.value = null;
      return true;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      return false;
    }
  }

  // --- step helpers -------------------------------------------------------

  function isStepComplete(step: string): boolean {
    return state.value?.completed_steps.includes(step) ?? false;
  }

  function isSkipped(step: string): boolean {
    return state.value?.skipped_steps.includes(step) ?? false;
  }

  return {
    state,
    loaded,
    error,
    status,
    isFinished,
    isInProgress,
    load,
    patch,
    isStepComplete,
    isSkipped,
  };
});
