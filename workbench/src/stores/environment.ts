/**
 * Environment readiness store (Stage 5, A-ONB02).
 *
 * Surfaces CLI / Docker Desktop / Docker Engine / WebView2 readiness and the
 * "installed ≠ engine ready" poll. `startDocker` launches Docker Desktop; the
 * caller then polls `envPollEngine` with a deadline so a stale snapshot is
 * never treated as ready (02-domain-contract.md).
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as ipc from "../lib/ipc";
import type { EnvReadiness } from "../types";

const EMPTY: EnvReadiness = {
  cli: "unknown",
  docker: "unknown",
  engine: "unknown",
  webview2: "unknown",
  dockerDesktopPath: "",
  cliPath: "",
};

export const useEnvironmentStore = defineStore("environment", () => {
  const readiness = ref<EnvReadiness>(EMPTY);
  const loading = ref(false);
  const polling = ref(false);
  const error = ref<string | null>(null);

  const engineReady = computed(() => readiness.value.engine === "ready");
  const cliReady = computed(() => readiness.value.cli === "ready");
  /** Everything the onboarding needs is ready. */
  const allReady = computed(() => cliReady.value && engineReady.value);
  /** Docker Desktop present but Engine not answering yet. */
  const dockerInstalling = computed(
    () =>
      readiness.value.docker === "installed" && readiness.value.engine !== "ready",
  );

  async function refresh(): Promise<EnvReadiness> {
    loading.value = true;
    error.value = null;
    try {
      readiness.value = await ipc.envReadiness();
      return readiness.value;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      return readiness.value;
    } finally {
      loading.value = false;
    }
  }

  async function startDocker() {
    try {
      await ipc.startDocker();
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
    }
  }

  /** Poll Engine readiness up to a deadline (ms); used after startDocker. */
  async function pollEngineReady(deadlineMs: number): Promise<EnvReadiness> {
    polling.value = true;
    error.value = null;
    try {
      readiness.value = await ipc.envPollEngine(deadlineMs);
      return readiness.value;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      return readiness.value;
    } finally {
      polling.value = false;
    }
  }

  return {
    readiness,
    loading,
    polling,
    error,
    engineReady,
    cliReady,
    allReady,
    dockerInstalling,
    refresh,
    startDocker,
    pollEngineReady,
  };
});
