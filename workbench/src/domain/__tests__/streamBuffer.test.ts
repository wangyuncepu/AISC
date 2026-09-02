/**
 * Stage 1 (S1.3, F-A04): bounded stream buffer semantics.
 * O2 (opt-batch, D-11): the RAW-offset parallel array (spool "load earlier"
 * anchor) rides along through appends and head drops.
 */
import { describe, expect, it } from "vitest";
import {
  OUTPUT_BYTE_BUDGET,
  OUTPUT_CHUNK_BUDGET,
  appendWithBudget,
  computeDisplayFrom,
  emptyStream,
  headOffset,
  type StreamChunk,
} from "../streamBuffer";

function chunks(...parts: Array<[string, number]>): StreamChunk[] {
  return parts.map(([b64, offset]) => ({ b64, offset }));
}

describe("appendWithBudget", () => {
  it("appends within budgets with byte accounting", () => {
    const state = appendWithBudget(emptyStream(), chunks(["abc", 0], ["de", 3]), { byteBudget: 100 });
    expect(state.chunks).toEqual(["abc", "de"]);
    expect(state.bytes).toBe(5);
    expect(state.truncated).toBe(false);
  });

  it("returns a fresh array so a single reactive replacement fires", () => {
    const state = emptyStream();
    const next = appendWithBudget(state, chunks(["x", 0]), { byteBudget: 100 });
    expect(next.chunks).not.toBe(state.chunks);
    expect(state.chunks).toEqual([]); // caller's old array is untouched
  });

  it("drops the OLDEST when the byte budget is exceeded, keeping newest", () => {
    const state = appendWithBudget(emptyStream(), chunks(["aaaa", 0], ["bbbb", 4]), { byteBudget: 6 });
    // "bbbb" is the newest and stays; "aaaa" is dropped from the head.
    expect(state.chunks).toEqual(["bbbb"]);
    expect(state.bytes).toBe(4);
    expect(state.truncated).toBe(true);
    expect(state.truncatedBytes).toBe(4); // "aaaa" dropped
  });

  it("drops the OLDEST at the chunk budget, keeping newest", () => {
    const state = appendWithBudget(emptyStream(), chunks(["a", 0], ["b", 1], ["c", 2]), { chunkBudget: 2 });
    expect(state.chunks).toEqual(["b", "c"]);
    expect(state.truncated).toBe(true);
    expect(state.truncatedBytes).toBe(1); // "a" dropped
  });

  it("keeps rendering after truncation (rolling window, not frozen)", () => {
    const first = appendWithBudget(emptyStream(), chunks(["aaaa", 0]), { byteBudget: 3 });
    expect(first.chunks).toEqual([]);
    expect(first.truncatedBytes).toBe(4);

    // New output still renders; oldest is dropped to stay within budget.
    const second = appendWithBudget(first, chunks(["b", 4]), { byteBudget: 3 });
    expect(second.chunks).toEqual(["b"]);
    expect(second.truncated).toBe(true);
    expect(second.truncatedBytes).toBe(4); // "b" fits, nothing new dropped
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
    const ok = appendWithBudget(state, chunks(["x", 0]), {});
    expect(ok.truncated).toBe(false);
  });
});

describe("raw offsets (O2, D-11)", () => {
  it("offsets run parallel to chunks through appends", () => {
    const a = appendWithBudget(emptyStream(), chunks(["aa", 0], ["bbb", 2]), { byteBudget: 100 });
    expect(a.offsets).toEqual([0, 2]);
    const b = appendWithBudget(a, chunks(["c", 5]), { byteBudget: 100 });
    expect(b.offsets).toEqual([0, 2, 5]);
  });

  it("head drop moves headOffset to the surviving window head", () => {
    const state = appendWithBudget(
      emptyStream(),
      chunks(["aa", 0], ["bb", 2], ["cc", 4]),
      { chunkBudget: 2 },
    );
    expect(state.chunks).toEqual(["bb", "cc"]);
    expect(headOffset(state)).toBe(2); // "aa" (offset 0) was dropped
  });

  it("headOffset is -1 for an empty buffer (unknown anchor)", () => {
    expect(headOffset(emptyStream())).toBe(-1);
  });

  it("offsets survive a truncated-to-empty window and re-anchor on recovery", () => {
    // Window empties under sustained overflow (chunk larger than budget)…
    const emptied = appendWithBudget(emptyStream(), chunks(["aaaa", 0]), { byteBudget: 3 });
    expect(emptied.chunks).toEqual([]);
    expect(headOffset(emptied)).toBe(-1);
    // …then new output re-populates the window with its own raw offsets.
    const refilled = appendWithBudget(emptied, chunks(["b", 4]), { byteBudget: 3 });
    expect(headOffset(refilled)).toBe(4);
  });
});

describe("computeDisplayFrom", () => {
  it("starts at 0 for a fresh window", () => {
    expect(computeDisplayFrom(0, 4096, 4096)).toBe(0);
  });

  it("advances from the consumer cursor when nothing was dropped", () => {
    // 4096 chunks emitted, 4096 kept, consumed 2048 -> continue at index 2048.
    expect(computeDisplayFrom(2048, 4096, 4096)).toBe(2048);
  });

  it("re-anchors when the head was dropped (rolling window)", () => {
    // 5000 emitted, 4096 kept (oldest 904 dropped), consumed 4096 -> arr[0]
    // is global 904, so the next new chunk (global 4096) is at index 3192.
    expect(computeDisplayFrom(4096, 5000, 4096)).toBe(3192);
  });

  it("skips dropped chunks a slow consumer has not seen", () => {
    // Consumer only displayed 3000 of 5000 emitted; 904 were dropped from the
    // head, so it must start at global 3000 -> index 3000 - (5000-4096).
    expect(computeDisplayFrom(3000, 5000, 4096)).toBe(3000 - 904);
  });

  it("empty buffer yields 0", () => {
    expect(computeDisplayFrom(0, 0, 0)).toBe(0);
  });
});
