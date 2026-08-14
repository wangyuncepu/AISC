/**
 * Stage 1 (S1.3, F-03): bounded terminal output buffer.
 *
 * The store no longer pushes every PTY chunk into a deep-reactive array. Chunks
 * are collected into a non-reactive pending queue and flushed in batches; each
 * flush runs through `appendWithBudget`, which returns a NEW chunks array so a
 * single reactive replacement fires (not one per chunk). Budgets make overflow
 * observable (`truncated` + `truncatedBytes`) instead of silent growth.
 *
 * The buffer is a ROLLING window: when the byte/chunk budget is exceeded the
 * OLDEST chunks are dropped so the terminal keeps rendering the newest output
 * (a terminal that freezes after truncation is a bug, not a budget). Dropped
 * bytes are always counted in `truncatedBytes`.
 */

export const OUTPUT_BYTE_BUDGET = 4 * 1024 * 1024; // per-pane, base64 bytes
export const OUTPUT_CHUNK_BUDGET = 4096; // per-pane chunk count

export interface StreamMeta {
  truncated: boolean;
  truncatedBytes: number;
}

export interface StreamBufferState {
  chunks: string[];
  bytes: number;
  truncated: boolean;
  truncatedBytes: number;
}

export function emptyStream(): StreamBufferState {
  return { chunks: [], bytes: 0, truncated: false, truncatedBytes: 0 };
}

/**
 * Append `incoming` chunks under the given budgets, returning a new state.
 *
 * New chunks are appended, then the OLDEST are dropped from the head until the
 * buffer fits the budgets — a rolling window that keeps the newest output. The
 * returned `chunks` is a fresh array (callers assign it to a ref to fire
 * exactly one reactive update per flush). `truncatedBytes` counts every byte
 * dropped over time.
 */
export function appendWithBudget(
  state: StreamBufferState,
  incoming: string[],
  opts: { byteBudget?: number; chunkBudget?: number } = {},
): StreamBufferState {
  const byteBudget = opts.byteBudget ?? OUTPUT_BYTE_BUDGET;
  const chunkBudget = opts.chunkBudget ?? OUTPUT_CHUNK_BUDGET;

  if (incoming.length === 0) {
    return state;
  }

  let chunks = state.chunks.slice(); // copy-on-write: single reactive replacement
  let bytes = state.bytes;
  let truncated = state.truncated;
  let dropped = 0;

  for (const chunk of incoming) {
    chunks.push(chunk);
    bytes += chunk.length;
  }
  // Drop from the HEAD until within budgets so the newest output stays visible.
  while ((chunks.length > chunkBudget || bytes > byteBudget) && chunks.length > 0) {
    const removed = chunks.shift()!;
    bytes -= removed.length;
    dropped += removed.length;
    truncated = true;
  }
  return {
    chunks,
    bytes,
    truncated,
    truncatedBytes: state.truncatedBytes + dropped,
  };
}

/** True when the byte budget has any room left for the given chunk. */
export function hasBudget(state: StreamBufferState, chunk: string, byteBudget = OUTPUT_BYTE_BUDGET): boolean {
  return !state.truncated && state.bytes + chunk.length <= byteBudget;
}

/**
 * Where to start displaying inside a rolling window.
 *
 * The window holds the most recent `bufLen` of `totalLen` emitted chunks
 * (`arr[0]` is global index `totalLen - bufLen`). A consumer that already
 * displayed `consumed` chunks starts at `max(consumed, startGlobal)`, mapped
 * back to an array index. Handles head-dropping without re-displaying old
 * chunks and without a length-based watch (which never fires once the window
 * is full).
 */
export function computeDisplayFrom(consumed: number, totalLen: number, bufLen: number): number {
  if (bufLen <= 0) return 0;
  const startGlobal = Math.max(0, totalLen - bufLen);
  return Math.max(consumed, startGlobal) - startGlobal;
}
