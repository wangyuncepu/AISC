/**
 * useRuntimePolling (S2.3.a; IDEA-3 3c: multi-workspace). Visibility-aware
 * runtime inspect loop over ALL open workspaces:
 *
 * - the ACTIVE workspace keeps the S2.3 cadence — 5s focused, 30s blurred
 *   (P7: was 15s — a blurred window still spawns full aisc.exe per tick),
 *   paused while hidden; ±10% jitter; deduped per-instance via
 *   `inspectInFlight`; resume marks stale and inspects immediately;
 * - BACKGROUND workspaces (真并行) downshift to ~60s (P7: was 25s) — their
 *   status dots / external-stop detection only need eventual consistency;
 *   switching back to a workspace refreshes it immediately.
 *
 * Started/stopped by App.vue watching "any workspace open".
 *
 * O6 (opt-batch, D-11): ADAPTIVE BACKOFF ladder on the focused interval.
 * A slow engine's inspect chain (aisc.exe + docker info/ps/inspect + gateway
 * probe) runs 1.5-2.8s per call — 40-60% duty cycle at 5s, which is the
 * user-perceived "docker 负载" on low-end machines. One slow refresh steps
 * the ladder 5s → 10s → 20s; three consecutive fast (<1s) refreshes step it
 * back down. A fast machine never leaves 5s (zero behavior change).
 */
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspacesStore } from "../stores/workspaces";
import {
  focusIntervalMs,
  initialBackoffState,
  nextBackoffState,
} from "./pollBackoff";

const BLUR_INTERVAL_MS = 30000;
const BACKGROUND_INTERVAL_MS = 60000;
const JITTER = 0.1; // ±10%

function jittered(base: number): number {
  const delta = base * JITTER * (Math.random() - 0.5) * 2;
  return Math.round(base + delta);
}

export function useRuntimePolling() {
  const store = useRuntimeStore();
  const ws = useWorkspacesStore();
  let timer: number | null = null;
  let running = false;
  /** Last background poll per workspace id (non-reactive bookkeeping). */
  const lastBackgroundPoll = new Map<string, number>();
  /** O6: adaptive ladder state (see pollBackoff.ts). */
  let backoff = initialBackoffState();

  /** Test/diagnostic view of the adaptive state. */
  function adaptiveRung(): number {
    return backoff.rung;
  }

  function intervalMs(): number {
    if (document.hidden) return 0; // paused while minimized/hidden
    const focused = document.hasFocus();
    const base = focused ? focusIntervalMs(backoff) : BLUR_INTERVAL_MS;
    return jittered(base);
  }

  async function tick(): Promise<void> {
    const t0 = performance.now();
    try {
      await store.refreshRuntime(); // the ACTIVE instance (facade forward)
    } finally {
      // Measure even on failure: a TIMEOUT is the strongest slow signal.
      backoff = nextBackoffState(backoff, performance.now() - t0);
    }
    // Background workspaces: only READY ones (launch flows own their state
    // until then), at the downshifted cadence, fire-and-forget (each instance
    // dedupes itself via its own inspectInFlight).
    const now = Date.now();
    for (const r of ws.runtimes) {
      if (r === ws.activeRuntime) continue;
      if (r.status.value !== "ready") continue;
      const last = lastBackgroundPoll.get(r.id) ?? 0;
      if (now - last >= BACKGROUND_INTERVAL_MS) {
        lastBackgroundPoll.set(r.id, now);
        void r.refreshRuntime();
      }
    }
    if (running) scheduleNext();
  }

  function scheduleNext(): void {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    const ms = intervalMs();
    if (ms === 0) return; // paused; resumed via the visibility handler
    timer = window.setTimeout(() => {
      void tick();
    }, ms);
  }

  /** Resume: mark every workspace stale, inspect, then resume the schedule. */
  function onResume(): void {
    store.markStale();
    for (const r of ws.runtimes) r.markStale();
    void tick();
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
    void tick(); // immediate first poll
  }

  function stop(): void {
    running = false;
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    lastBackgroundPoll.clear();
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("focus", onResume);
    window.removeEventListener("blur", scheduleNext);
  }

  return { start, stop, adaptiveRung };
}
