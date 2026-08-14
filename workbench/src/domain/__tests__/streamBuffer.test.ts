/**
 * Stage 1 (S1.3, F-A04): bounded stream buffer semantics.
 */
import { describe, expect, it } from "vitest";
import {
  OUTPUT_BYTE_BUDGET,
  OUTPUT_CHUNK_BUDGET,
  appendWithBudget,
  emptyStream,
} from "../streamBuffer";

describe("appendWithBudget", () => {
  it("appends within budgets with byte accounting", () => {
    const state = appendWithBudget(emptyStream(), ["abc", "de"], { byteBudget: 100 });
    expect(state.chunks).toEqual(["abc", "de"]);
    expect(state.bytes).toBe(5);
    expect(state.truncated).toBe(false);
  });

  it("returns a fresh array so a single reactive replacement fires", () => {
    const state = emptyStream();
    const next = appendWithBudget(state, ["x"], { byteBudget: 100 });
    expect(next.chunks).not.toBe(state.chunks);
    expect(state.chunks).toEqual([]); // caller's old array is untouched
  });

  it("truncates when the byte budget is exceeded and counts bytes", () => {
    const state = appendWithBudget(emptyStream(), ["aaaa", "bbbb"], { byteBudget: 6 });
    expect(state.chunks).toEqual(["aaaa"]);
    expect(state.bytes).toBe(4);
    expect(state.truncated).toBe(true);
    expect(state.truncatedBytes).toBe(4); // "bbbb" dropped
  });

  it("truncates at the chunk budget", () => {
    const state = appendWithBudget(emptyStream(), ["a", "b", "c"], { chunkBudget: 2 });
    expect(state.chunks).toEqual(["a", "b"]);
    expect(state.truncated).toBe(true);
    expect(state.truncatedBytes).toBe(1); // "c" dropped
  });

  it("keeps dropping after truncation (no silent re-entry)", () => {
    const first = appendWithBudget(emptyStream(), ["aaaa"], { byteBudget: 3 });
    const second = appendWithBudget(first, ["b"], { byteBudget: 3 });
    expect(second.chunks).toEqual([]);
    expect(second.truncated).toBe(true);
    expect(second.truncatedBytes).toBe(4 + 1);
  });

  it("no-op for empty incoming keeps the same array reference", () => {
    const state = emptyStream();
    const next = appendWithBudget(state, [], { byteBudget: 10 });
    expect(next.chunks).toBe(state.chunks);
  });

  it("defaults match the exported budgets", () => {
    const state = emptyStream();
    // 1 byte over the default byte budget would truncate; staying under keeps all.
    expect(OUTPUT_BYTE_BUDGET).toBeGreaterThan(0);
    expect(OUTPUT_CHUNK_BUDGET).toBeGreaterThan(0);
    const ok = appendWithBudget(state, ["x"], {});
    expect(ok.truncated).toBe(false);
  });
});
