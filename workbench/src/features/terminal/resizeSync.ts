/**
 * B-05 (terminal stability): xterm ↔ PTY size convergence helpers.
 *
 * The PTY is spawned at 80×24 and only changes when `resize_session` lands;
 * xterm re-fits on layout events. Nothing used to force these two together
 * at session start, and a failed `resize_session` was silently swallowed —
 * so the two could sit at different widths while readline/TUI redraw math
 * lands on the wrong columns (long-input overwrite, garbled rows on tab
 * switch; see docs/plans/aisc-next-followup/b05-terminal-stability/plan.md).
 *
 * The convergence model: send on every decisive moment (session becomes
 * running, pane becomes visible, resize event), remember the CONFIRMED size,
 * skip when already converged, and let a periodic tick re-send on drift or
 * after a failure. All decisions flow through these pure helpers so the
 * policy stays testable without a DOM.
 */

/** A confirmed-or-candidate terminal grid size. */
export interface TermSize {
  cols: number;
  rows: number;
}

/** True when both sizes exist and are equal. Null (never synced) never
 *  matches — the first send must always go out. */
export function sameTermSize(a: TermSize | null, b: TermSize | null): boolean {
  return a !== null && b !== null && a.cols === b.cols && a.rows === b.rows;
}

/** True when a send is due: never synced, drifted from the confirmed size,
 *  or the previous send failed (retry). A no-op when already converged. */
export function shouldSendSize(
  lastConfirmed: TermSize | null,
  current: TermSize,
  failed: boolean,
): boolean {
  return failed || !sameTermSize(lastConfirmed, current);
}
