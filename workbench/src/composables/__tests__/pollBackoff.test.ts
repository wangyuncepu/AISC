/**
 * O6 (opt-batch, D-11): adaptive poll-backoff ladder semantics.
 */
import { describe, expect, it } from "vitest";
import {
  FAST_STREAK_TO_RECOVER,
  FOCUS_LADDER_MS,
  focusIntervalMs,
  initialBackoffState,
  nextBackoffState,
} from "../pollBackoff";

describe("adaptive poll backoff (O6, D-11)", () => {
  it("a fast machine never leaves rung 0 (zero behavior change)", () => {
    let s = initialBackoffState();
    for (let i = 0; i < 10; i++) s = nextBackoffState(s, 300);
    expect(s.rung).toBe(0);
    expect(focusIntervalMs(s)).toBe(FOCUS_LADDER_MS[0]);
  });

  it("one slow op escalates one rung; the ladder caps at the top", () => {
    let s = initialBackoffState();
    s = nextBackoffState(s, 1800); // > 1500ms
    expect(s.rung).toBe(1);
    s = nextBackoffState(s, 2500);
    expect(s.rung).toBe(2);
    s = nextBackoffState(s, 2800);
    expect(s.rung).toBe(2); // capped at 20s
    expect(focusIntervalMs(s)).toBe(FOCUS_LADDER_MS[2]);
  });

  it("three consecutive fast ops recover one rung (and only one)", () => {
    let s = initialBackoffState();
    s = nextBackoffState(s, 2000);
    s = nextBackoffState(s, 2000);
    expect(s.rung).toBe(2);
    s = nextBackoffState(s, 400);
    s = nextBackoffState(s, 400);
    expect(s.rung).toBe(2); // two fast are not enough
    s = nextBackoffState(s, 400);
    expect(s.rung).toBe(1); // third recovers one
    expect(s.fastStreak).toBe(0);
  });

  it("a slow op resets the recovery streak", () => {
    let s = initialBackoffState();
    s = nextBackoffState(s, 2000); // rung 1
    s = nextBackoffState(s, 400);
    s = nextBackoffState(s, 400);
    s = nextBackoffState(s, 1600); // slow again — streak gone
    expect(s.rung).toBe(2); // (also escalates, slow op)
    s = nextBackoffState(s, 400);
    s = nextBackoffState(s, 400);
    expect(s.rung).toBe(2); // streak was reset — no recovery yet
  });

  it("a middling op holds the rung and resets the streak", () => {
    let s = initialBackoffState();
    s = nextBackoffState(s, 2000); // rung 1
    s = nextBackoffState(s, 400);
    s = nextBackoffState(s, 1200); // 1s..1.5s — neither signal
    expect(s.rung).toBe(1);
    expect(s.fastStreak).toBe(0);
    expect(FAST_STREAK_TO_RECOVER).toBe(3);
  });
});
