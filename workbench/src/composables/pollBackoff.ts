/**
 * O6 (opt-batch, D-11): adaptive poll-backoff state machine — pure so the
 * ladder semantics stay testable without a DOM/store.
 *
 * A slow engine's inspect chain runs 1.5-2.8s per call (nairong probe);
 * at a 5s cadence that is a 40-60% duty cycle of continuous aisc.exe +
 * docker subprocess churn. One slow refresh escalates 5s → 10s → 20s;
 * three consecutive fast ones recover one rung. Fast machines never leave
 * rung 0 — zero behavior change for them.
 */

export const FOCUS_LADDER_MS = [5000, 10000, 20000] as const;
export const SLOW_OP_MS = 1500;
export const FAST_OP_MS = 1000;
export const FAST_STREAK_TO_RECOVER = 3;

export interface BackoffState {
  rung: number;
  fastStreak: number;
}

export function initialBackoffState(): BackoffState {
  return { rung: 0, fastStreak: 0 };
}

/** Feed one measured refresh duration; returns the next state. */
export function nextBackoffState(state: BackoffState, dtMs: number): BackoffState {
  if (dtMs > SLOW_OP_MS) {
    // A slow op (or a timeout — callers feed failures too) escalates once
    // and resets any recovery streak.
    return {
      rung: Math.min(state.rung + 1, FOCUS_LADDER_MS.length - 1),
      fastStreak: 0,
    };
  }
  if (dtMs < FAST_OP_MS) {
    const fastStreak = state.fastStreak + 1;
    if (fastStreak >= FAST_STREAK_TO_RECOVER && state.rung > 0) {
      return { rung: state.rung - 1, fastStreak: 0 };
    }
    return { rung: state.rung, fastStreak };
  }
  // Middling op (1s-1.5s): neither signal — hold the rung, reset the streak.
  return { rung: state.rung, fastStreak: 0 };
}

/** The focused-cadence interval for a state (blurred/hidden are caller's). */
export function focusIntervalMs(state: BackoffState): number {
  return FOCUS_LADDER_MS[state.rung]!;
}
