/**
 * useRuntimePolling (S2.3.a): visibility-aware runtime inspect loop.
 *
 * Periodically calls `store.refreshRuntime()` (inspect + apply) so external
 * stop/remove is reflected within one poll cycle (04 §五; Phase 2 gate). Cadence
 * per 04 §五: 5s focused, 15s blurred, paused while hidden; ±10% jitter; deduped
 * via `store.inspectInFlight`. On resume (hidden->visible or focus regained)
 * the snapshot is marked stale and inspected immediately (04 §六.1 resume).
 *
 * Started/stopped by App.vue watching `store.status === "ready"`.
 */
import { useRuntimeStore } from "../stores/runtime";

const FOCUS_INTERVAL_MS = 5000;
const BLUR_INTERVAL_MS = 15000;
const JITTER = 0.1; // ±10%

function jittered(base: number): number {
  const delta = base * JITTER * (Math.random() - 0.5) * 2;
  return Math.round(base + delta);
}

export function useRuntimePolling() {
  const store = useRuntimeStore();
  let timer: number | null = null;
  let running = false;

  function intervalMs(): number {
    if (document.hidden) return 0; // paused while minimized/hidden
    const focused = document.hasFocus();
    return jittered(focused ? FOCUS_INTERVAL_MS : BLUR_INTERVAL_MS);
  }

  async function tick(): Promise<void> {
    await store.refreshRuntime();
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

  /** Resume: mark stale, inspect immediately, then resume the schedule. */
  function onResume(): void {
    store.markStale();
    void tick();
  }

  function onVisibilityChange(): void {
    if (document.hidden) {
      // Pause: drop the pending tick. visibility->visible resumes via onResume.
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
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("focus", onResume);
    window.removeEventListener("blur", scheduleNext);
  }

  return { start, stop };
}
