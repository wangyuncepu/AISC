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

/** Auto-poll cadence while Docker is installing/starting (ms). Keeps the env
 *  step live so the wizard notices readiness without manual re-checks. */
const AUTO_POLL_MS = 5000;

const EMPTY: EnvReadiness = {
  cli: "unknown",
  docker: "unknown",
  engine: "unknown",
  webview2: "unknown",
  dockerDesktopPath: "",
  cliPath: "",
  engineDetail: "",
};

export const useEnvironmentStore = defineStore("environment", () => {
  const readiness = ref<EnvReadiness>(EMPTY);
  const loading = ref(false);
  const polling = ref(false);
  /** True while start_docker is actually installing Docker Desktop (winget
   *  download) — distinct from `polling` (which waits for the engine). */
  const installing = ref(false);
  const error = ref<string | null>(null);

  const engineReady = computed(() => readiness.value.engine === "ready");
  const cliReady = computed(() => readiness.value.cli === "ready");
  /** Everything the onboarding needs is ready. */
  const allReady = computed(() => cliReady.value && engineReady.value);
  /** KI-1 UX (wizard, user feedback 2026-08-17): a wake-up is in flight —
   * Docker Desktop was launched from here and the engine has not answered
   * yet. Drives the progress banner (spinner + elapsed) so the click has a
   * visible outcome instead of one flicker. Cleared by refresh() when the
   * engine turns ready, or after a deadline if it never does. */
  const dockerStarting = ref(false);
  const dockerStartedAt = ref<number | null>(null);
  /** How long the progress state may persist before giving up on it (ms). */
  const DOCKER_START_DEADLINE_MS = 180_000;

  /** Clear the wake-up progress state (engine answered, deadline, or stop). */
  function clearDockerStarting(): void {
    dockerStarting.value = false;
    dockerStartedAt.value = null;
  }
  /** Docker Desktop missing or installed but Engine not answering yet — the
   *  "Start Docker" action should offer to install (winget) and/or launch. */
  const dockerInstalling = computed(
    () =>
      (readiness.value.docker === "installed" ||
        readiness.value.docker === "not_installed") &&
      readiness.value.engine !== "ready",
  );

  // --- auto-poll: live detection while Docker installs/starts --------------
  // Manual test 2026-08-16 (round 2): after "Install and start Docker" the
  // wizard stayed static — no real-time detection and "Re-check" appeared dead.
  // Two root causes fixed: the old 180s blocking poll (disabled buttons, then
  // nothing) and the re-check button being disabled while `loading` was true
  // (~4s of every 5s auto-poll tick, so clicks landed on a disabled button).
  // Auto-poll now runs continuously while the env step is active and Docker is
  // not ready — it does NOT pause during a manual poll (both are idempotent
  // reads), only while an install (winget/bundled) is actually in flight.
  let autoTimer: number | null = null;

  function stopAutoPoll(): void {
    if (autoTimer !== null) {
      window.clearInterval(autoTimer);
      autoTimer = null;
    }
  }

  /** Begin live auto-polling (idempotent). Self-stops on the next tick when
   *  readiness no longer warrants it, or via stopAutoPoll(). */
  function startAutoPoll(): void {
    if (autoTimer !== null) return;
    autoTimer = window.setInterval(async () => {
      if (!dockerInstalling.value || installing.value) {
        stopAutoPoll();
        return;
      }
      await refresh();
    }, AUTO_POLL_MS);
  }

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
      // KI-1 UX: resolve the wake-up progress state on the same observation
      // the auto-poll uses — engine answered, or the deadline passed.
      if (dockerStarting.value) {
        const started = dockerStartedAt.value ?? Date.now();
        if (readiness.value.engine === "ready" || Date.now() - started >= DOCKER_START_DEADLINE_MS) {
          clearDockerStarting();
        }
      }
      loading.value = false;
    }
  }

  async function startDocker() {
    if (dockerStarting.value) return; // one wake-up at a time (no re-spawn)
    installing.value = true;
    error.value = null;
    try {
      // start_docker awaits the winget install (bounded ~10 min) and returns
      // a real error on failure; success means Docker Desktop.exe exists.
      await ipc.startDocker();
      // Spawn dispatched (installed case returns in ~1-2s): enter the
      // progress state — the auto-poll's refresh() clears it when the engine
      // answers (or the deadline passes).
      dockerStarting.value = true;
      dockerStartedAt.value = Date.now();
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
    } finally {
      installing.value = false;
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
    installing,
    error,
    engineReady,
    cliReady,
    allReady,
    dockerInstalling,
    dockerStarting,
    dockerStartedAt,
    refresh,
    startDocker,
    pollEngineReady,
    startAutoPoll,
    stopAutoPoll,
  };
});
