/**
 * useRuntimePolling (S2.3.a; IDEA-3 3c: multi-workspace). Visibility-aware
 * runtime inspect loop over ALL open workspaces:
 *
 * - the ACTIVE workspace keeps the S2.3 cadence — 5s focused, 15s blurred,
 *   paused while hidden; ±10% jitter; deduped per-instance via
 *   `inspectInFlight`; resume marks stale and inspects immediately;
 * - BACKGROUND workspaces (真并行) downshift to ~25s so their status dots /
 *   external-stop detection stay fresh at a fraction of the cost.
 *
 * Started/stopped by App.vue watching "any workspace open".
 */
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspacesStore } from "../stores/workspaces";

const FOCUS_INTERVAL_MS = 5000;
const BLUR_INTERVAL_MS = 15000;
const BACKGROUND_INTERVAL_MS = 25000;
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

  function intervalMs(): number {
    if (document.hidden) return 0; // paused while minimized/hidden
    const focused = document.hasFocus();
    return jittered(focused ? FOCUS_INTERVAL_MS : BLUR_INTERVAL_MS);
  }

  async function tick(): Promise<void> {
    await store.refreshRuntime(); // the ACTIVE instance (facade forward)
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

  return { start, stop };
}
