/**
 * Stage 1 (S1.7, F-A08): terminal output throughput budget.
 *
 * A fixed 10 MiB fixture (PTY-sized ~2.5 KiB base64 chunks) must be processed
 * by appendWithBudget well under a hard deadline, stay within the byte budget,
 * and truncate observably with every dropped byte counted (F-A04/F-A08). The
 * reported ms is a stable bound, not a promise of a specific FPS.
 */
import { describe, expect, it } from "vitest";
import {
  OUTPUT_BYTE_BUDGET,
  appendWithBudget,
  emptyStream,
} from "../streamBuffer";

describe("S1.7 10 MiB output budget", () => {
  it("bounds memory, truncates observably, and never drops silently", () => {
    const chunk = "A".repeat(2560); // ~2.5 KiB base64 per chunk (PTY read size)
    const totalChunks = Math.ceil((10 * 1024 * 1024) / chunk.length);
    expect(totalChunks).toBeGreaterThan(4000);

    let state = emptyStream();
    const started = performance.now();
    for (let i = 0; i < totalChunks; i++) {
      state = appendWithBudget(state, [chunk]);
    }
    const elapsedMs = performance.now() - started;

    // Hard upper bound: 10 MiB processed well under 2s on any dev/CI machine.
    expect(elapsedMs).toBeLessThan(2000);

    // Default budget (4 MiB base64) is exceeded -> observable truncation.
    expect(state.truncated).toBe(true);
    const keptBytes = state.chunks.reduce((n, c) => n + c.length, 0);
    expect(keptBytes).toBeLessThanOrEqual(OUTPUT_BYTE_BUDGET);

    // Every byte is accounted for: kept + dropped === total, nothing swallowed.
    expect(state.truncatedBytes).toBeGreaterThan(0);
    expect(keptBytes + state.truncatedBytes).toBe(totalChunks * chunk.length);
    expect(state.chunks.length).toBeLessThanOrEqual(4096); // chunk budget
  });

  it("no reactive growth: batching replaces the array, never pushes per chunk", () => {
    const chunk = "x".repeat(512);
    let state = emptyStream();
    state = appendWithBudget(state, [chunk, chunk, chunk], { byteBudget: 10_000 });
    const replacement = appendWithBudget(state, [chunk], { byteBudget: 10_000 });
    // The consumer sees a fresh array each flush (single reactive write).
    expect(replacement.chunks).not.toBe(state.chunks);
    expect(replacement.chunks.length).toBe(4);
  });
});
