/**
 * useProviderPolling (S2.3.b): per-agent provider status refresh for the active
 * claude/codex tab (04 §五). Cadence: 15s focused, 60s blurred, paused while
 * hidden; only when the runtime is running. Switching to a claude/codex tab
 * refreshes immediately; bash/cc-switch or a non-running runtime pauses.
 *
 * PERF P7 (D-13): the focused cadence now rides the O6 adaptive ladder
 * (PROVIDER_LADDER_MS 15→30→60s, provider-op duration as the slow signal) —
 * each poll spawns a full aisc.exe, so slow engines degrade instead of
 * churning. Blurred stays 60s; fast machines never leave rung 0.
 *
 * Started/stopped by App.vue alongside useRuntimePolling (ready only).
 */
import { watch } from "vue";
import { useRuntimeStore } from "../stores/runtime";
import type { LaunchAgent } from "../types";
import {
  focusIntervalMs,
  initialBackoffState,
  nextBackoffState,
  PROVIDER_LADDER_MS,
} from "./pollBackoff";

const BLUR_INTERVAL_MS = 60000;
const JITTER = 0.1; // ±10%

function jittered(base: number): number {
  const delta = base * JITTER * (Math.random() - 0.5) * 2;
  return Math.round(base + delta);
}

function isProviderAgent(a: LaunchAgent | null | undefined): a is "claude" | "codex" {
  return a === "claude" || a === "codex";
}

export function useProviderPolling() {
  const store = useRuntimeStore();
  let timer: number | null = null;
  let running = false;
  /** P7: adaptive ladder state (provider cadence table). */
  let backoff = initialBackoffState();

  function activeAgent(): LaunchAgent | null {
    const tab = store.tabs.find((t) => t.tabId === store.activeTabId);
    return tab?.agent ?? null;
  }

  function shouldQuery(): boolean {
    return store.runtimeState === "running" && isProviderAgent(activeAgent());
  }

  function intervalMs(): number {
    if (document.hidden) return 0;
    const base = document.hasFocus()
      ? focusIntervalMs(backoff, PROVIDER_LADDER_MS)
      : BLUR_INTERVAL_MS;
    return jittered(base);
  }

  async function tick(): Promise<void> {
    const t0 = performance.now();
    let ran = false;
    let outcome: "ok" | "unsettled" | "error" | "skipped" = "skipped";
    if (shouldQuery()) {
      ran = true;
      // Manual-test fix v2 (2026-09-06): the store reports a tri-state —
      // "unsettled" (probe ANSWERED but auth is not_configured/unknown,
      // e.g. cold-boot cc-switch mid-rewrite) counts as not-settled too.
      outcome = await store.loadProviderStatus(activeAgent() as "claude" | "codex");
    }
    if (ran) {
      if (outcome === "ok") {
        // Configured: the duration feeds the churn ladder (slow-but-
        // successful ops escalate — the P7 steady-state protection).
        backoff = nextBackoffState(backoff, performance.now() - t0, PROVIDER_LADDER_MS);
      } else {
        // Error or not-yet-settled: retry at the BASE cadence. Escalating
        // here is what stretched "检测不到 → 已配置" to 30-60s+.
        backoff = initialBackoffState();
      }
    }
    if (running) scheduleNext();
  }

  function scheduleNext(): void {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    if (!shouldQuery()) return; // active agent not claude/codex, or runtime not running
    const ms = intervalMs();
    if (ms === 0) return; // paused; resumed via the visibility handler
    timer = window.setTimeout(() => {
      void tick();
    }, ms);
  }

  function onResume(): void {
    if (shouldQuery()) void tick();
  }

  function onVisibilityChange(): void {
    if (document.hidden) {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    } else {
      onResume();
    }
  }

  function start(): void {
    if (running) return;
    running = true;
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("focus", onResume);
    window.addEventListener("blur", scheduleNext);
    void tick(); // immediate first query if applicable
  }

  function stop(): void {
    running = false;
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("focus", onResume);
    window.removeEventListener("blur", scheduleNext);
  }

  // Re-evaluate on active-tab / runtime-state change: refresh immediately when
  // switching to a claude/codex tab, pause otherwise. A fresh runtime means a
  // fresh container — the ladder (built from the previous world's op timings)
  // resets so the first probes run at the base cadence.
  watch([() => store.activeTabId, () => store.runtimeState], () => {
    if (!running) return;
    if (shouldQuery()) {
      backoff = initialBackoffState();
      void tick();
    } else if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  });

  return { start, stop };
}
