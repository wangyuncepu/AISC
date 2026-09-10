/**
 * P1-2 (2.1.11): linearize a spool page for history replay.
 *
 * The raw PTY stream carries full-screen choreography — scroll-down
 * (`CSI n T`) inserts blank lines, ED/CUP redraw whole regions, alt-screen
 * switches move content into a buffer the scrollback never shows. Live,
 * those sequences paint a viewport; replayed over a long scrollback they
 * leave big bands of never-written blank lines (measured: 100×`CSI 10 T`
 * ⇒ a 199-line band — the reported "big blank area at the top").
 *
 * This filter rewrites a replayed page into a linear log: every redraw
 * round appends instead of repositioning. SGR (colors) and EL
 * (in-line erase) survive; screen-level geometry does not.
 *
 * Byte-oriented on purpose: ESC sequences are pure ASCII, so UTF-8
 * multibyte payload (any byte ≥ 0x80) passes through untouched.
 */

const ESC = 0x1b;

export function linearizeSpoolPage(data: Uint8Array): Uint8Array {
  const out = new Uint8Array(data.length + 64); // worst case: A/B grow by ≤ 1 byte per sequence
  let w = 0;
  let i = 0;
  const n = data.length;

  const emit = (byte: number): void => {
    if (w >= out.length) return;
    out[w++] = byte;
  };

  while (i < n) {
    const b = data[i];
    if (b !== ESC) {
      if (w < out.length) out[w++] = b;
      i++;
      continue;
    }
    // ESC seen — parse a CSI sequence: ESC [ <params(ASCII) > <final byte>
    if (i + 1 >= n || data[i + 1] !== 0x5b /* [ */) {
      // Two-byte escape (ESC 7/8/D/M …) — drop cursor ops, keep the byte
      // count moving. ESC M (RI) is a scroll-shape op: degrade to LF.
      if (i + 1 < n && data[i + 1] === 0x4d /* M */) emit(0x0a);
      i += 2;
      continue;
    }
    // CSI: scan params/intermediates to the final byte.
    let j = i + 2;
    while (j < n && data[j] >= 0x20 && data[j] <= 0x2f) j++; // intermediates
    let end = j;
    while (end < n && !(data[end] >= 0x40 && data[end] <= 0x7e)) end++;
    if (end >= n) break; // truncated tail — nothing more to do
    const final = data[end];
    const paramStart = j;
    const paramText = String.fromCharCode(
      ...Array.from(data.subarray(paramStart, end)).filter((c) => c >= 0x30 && c <= 0x3f),
    );
    const isPrivate = paramText.includes("?");

    const copySeq = (): void => {
      for (let k = i; k <= end; k++) {
        if (w < out.length) out[w++] = data[k];
      }
    };

    switch (final) {
      // Screen geometry — strip entirely (this is the blank-band source).
      case 0x54: // CSI n T — scroll down: THE big blank injector
      case 0x53: // CSI n S — scroll up
      case 0x4a: // CSI n J — erase display
      case 0x48: // CSI r;c H — cursor position
      case 0x66: // CSI r;c f — HVP
      case 0x72: // CSI t;b r — DECSTBM scroll region
        break;
      // Cursor up/down — degrade to a line feed so each redraw round
      // appends (up-move is how TUIs rewrite the block they just printed).
      case 0x41: // CUU
      case 0x42: // CUD
        emit(0x0a);
        break;
      // Alt-screen toggles — strip: replay must stay in the normal buffer.
      case 0x68: // DECSET
      case 0x6c: // DECRST
        if (isPrivate && /^(1049|47|1047|1048)$/.test(paramText.replace("?", ""))) {
          break; // stripped
        }
        copySeq();
        break;
      // Everything else (SGR `m`, EL `K`, etc.) — keep verbatim.
      default:
        copySeq();
        break;
    }

    i = end + 1;
  }
  return out.subarray(0, w);
}
