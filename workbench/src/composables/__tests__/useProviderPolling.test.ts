/**
 * PERF P7 fix regression (manual-test 2026-09-06): the provider ladder used
 * to escalate on FAILED probes too — right after a workspace start the first
 * probe (aisc spawn ~750ms + cold in-container cc-switch) takes >1.5s, so
 * the retry cadence jumped 15→30→60s and the agent page sat on
 * 「无法确认 Provider 状态」for a minute+ before showing 已配置.
 *
 * Contract after the fix:
 *  - a FAILED probe retries at the BASE cadence (15s ±10%), never a rung;
 *  - a slow-but-SUCCESSFUL probe still escalates (the churn protection);
 *  - a runtime restart resets the ladder (fresh container, fresh timings).
 *
 * Assertions are on the INTERVALS between consecutive calls (the cadence
 * semantics), not absolute wall-clock windows — the ±10% jitter makes
 * absolute windows flaky by construction.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reactive } from "vue";

const fakeStore = reactive({
  tabs: [{ tabId: "t1", agent: "claude" }] as Array<{ tabId: string; agent: string }>,
  activeTabId: "t1",
  runtimeState: "running",
  loadProviderStatus: vi.fn().mockResolvedValue(true),
});

vi.mock("../../stores/runtime", () => ({
  useRuntimeStore: () => fakeStore,
}));

import { useProviderPolling } from "../useProviderPolling";

/** Fake-clock timestamps of each probe call (Date is faked with the timers). */
const callTimes: number[] = [];
/** Outcome the next probe returns. */
let nextOutcome: boolean | { delayMs: number } = true;

function recordCall(): Promise<boolean> {
  callTimes.push(Date.now());
  const outcome = nextOutcome;
  if (typeof outcome === "object") {
    return new Promise((resolve) => {
      setTimeout(() => resolve(true), outcome.delayMs);
    });
  }
  return Promise.resolve(outcome);
}

/** Advance the fake clock in small steps until n probes have run. */
async function advanceUntil(n: number, budgetMs = 200_000): Promise<void> {
  const deadline = Date.now() + budgetMs;
  while (callTimes.length < n) {
    if (Date.now() >= deadline) throw new Error(`only ${callTimes.length}/${n} probes after ${budgetMs}ms`);
    await vi.advanceTimersByTimeAsync(500);
  }
}

function intervals(): number[] {
  return callTimes.slice(1).map((t, i) => t - callTimes[i]!);
}

beforeEach(() => {
  vi.useFakeTimers();
  // jsdom defaults to hidden=prerender / hasFocus=false — the poller treats
  // that as "paused" and never schedules. Make the page visible+focused.
  Object.defineProperty(document, "hidden", { value: false, configurable: true });
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  Object.defineProperty(document, "hasFocus", { value: () => true, configurable: true });
  fakeStore.tabs = [{ tabId: "t1", agent: "claude" }];
  fakeStore.activeTabId = "t1";
  fakeStore.runtimeState = "running";
  callTimes.length = 0;
  nextOutcome = true;
  fakeStore.loadProviderStatus.mockReset().mockImplementation(recordCall);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useProviderPolling ladder semantics (manual-test fix)", () => {
  it("a failed probe retries at the base cadence — never a ladder rung", async () => {
    nextOutcome = false; // every probe fails (container still warming)
    const p = useProviderPolling();
    p.start();
    await advanceUntil(4);
    p.stop();

    // All retries at the BASE 15s ±10% — the old code fed failures to the
    // ladder and stretched the cadence to 30/60s.
    for (const dt of intervals()) {
      expect(dt).toBeGreaterThanOrEqual(13_500);
      expect(dt).toBeLessThanOrEqual(16_500);
    }
  });

  it("a slow-but-successful probe escalates (the P7 churn protection stays)", async () => {
    nextOutcome = { delayMs: 2_000 }; // > SLOW_OP_MS, succeeds
    const p = useProviderPolling();
    p.start();
    await advanceUntil(3);
    p.stop();

    // Interval between call STARTS = probe duration (2s) + rung-1 cadence
    // (30s ±10%) → 29s..35s.
    const dt = intervals()[0]!;
    expect(dt).toBeGreaterThanOrEqual(28_000);
    expect(dt).toBeLessThanOrEqual(36_000);
  });

  it("a runtime restart resets the ladder to the base cadence", async () => {
    nextOutcome = { delayMs: 2_000 }; // slow success → rung 1
    const p = useProviderPolling();
    p.start();
    await advanceUntil(2);
    await vi.advanceTimersByTimeAsync(3_000); // let probe 2 COMPLETE before the flip

    // Warm container now: post-restart probes are fast and succeed.
    nextOutcome = true;
    fakeStore.runtimeState = "stopped";
    await vi.advanceTimersByTimeAsync(0); // let the watcher observe the change
    fakeStore.runtimeState = "running"; // reset + immediate tick (probe 3)
    await advanceUntil(4);
    p.stop();

    // intervals: [0] pre-restart rung-1 gap; [1] restart-tick gap (immediate,
    // unasserted); [2] the post-restart scheduled gap — base cadence again.
    const [before, , after] = intervals();
    expect(before!).toBeGreaterThanOrEqual(28_000);
    expect(after!).toBeGreaterThanOrEqual(13_500);
    expect(after!).toBeLessThanOrEqual(16_500);
  });
});
