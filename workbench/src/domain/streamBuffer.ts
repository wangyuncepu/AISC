/**
 * Stage 1 (S1.3, F-03): bounded terminal output buffer.
 *
 * The store no longer pushes every PTY chunk into a deep-reactive array. Chunks
 * are collected into a non-reactive pending queue and flushed in batches; each
 * flush runs through `appendWithBudget`, which returns a NEW chunks array so a
 * single reactive replacement fires (not one per chunk). Budgets make overflow
 * observable (`truncated` + `truncatedBytes`) instead of silent growth.
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
 * A chunk is kept only if the chunk-count budget and the byte budget both have
 * room; otherwise it is counted as truncated. Ordering is preserved up to the
 * truncation point. The returned `chunks` is a fresh array (callers assign it
 * to a ref to fire exactly one reactive update per flush).
 */
export function appendWithBudget(
  state: StreamBufferState,
  incoming: string[],
  opts: { byteBudget?: number; chunkBudget?: number } = {},
): StreamBufferState {
  const byteBudget = opts.byteBudget ?? OUTPUT_BYTE_BUDGET;
  const chunkBudget = opts.chunkBudget ?? OUTPUT_CHUNK_BUDGET;

  let chunks = state.chunks;
  let bytes = state.bytes;
  let truncatedBytes = state.truncatedBytes;
  let truncated = state.truncated;

  if (incoming.length === 0) {
    return { chunks, bytes, truncated, truncatedBytes };
  }

  // Truncation is terminal: once the budget is exceeded, every later chunk is
  // counted as dropped so the buffer can never resume silently.
  if (truncated) {
    for (const chunk of incoming) {
      truncatedBytes += chunk.length;
    }
    return { chunks, bytes, truncated, truncatedBytes };
  }

  let dirty = false;
  for (const chunk of incoming) {
    if (chunks.length >= chunkBudget || bytes + chunk.length > byteBudget) {
      truncated = true;
      truncatedBytes += chunk.length;
      continue;
    }
    if (!dirty) {
      chunks = chunks.slice(); // copy-on-first-write
      dirty = true;
    }
    chunks.push(chunk);
    bytes += chunk.length;
  }
  return { chunks, bytes, truncated, truncatedBytes };
}

/** True when the byte budget has any room left for the given chunk. */
export function hasBudget(state: StreamBufferState, chunk: string, byteBudget = OUTPUT_BYTE_BUDGET): boolean {
  return !state.truncated && state.bytes + chunk.length <= byteBudget;
}
