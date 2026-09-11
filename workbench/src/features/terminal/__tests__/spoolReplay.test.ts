/**
 * P1-2 (2.1.11): the spool-replay linearizer. Reproduced with a real
 * buffer (@xterm/headless, aligned to the xterm 6 line): replaying raw
 * full-screen choreography over a long scrollback leaves big blank bands
 * (100×`CSI 10 T` ⇒ a 199-line band — the reported "big blank area at the
 * top"). The linearizer strips screen-geometry sequences and degrades
 * cursor up/down to line feeds; SGR colors survive.
 */
import { describe, expect, it } from "vitest";
import { Terminal } from "@xterm/headless";
import { linearizeSpoolPage } from "../spoolReplay";

const enc = (s: string): Uint8Array => new TextEncoder().encode(s);
const dec = (u: Uint8Array): string => new TextDecoder().decode(u);

function write(t: Terminal, data: string): Promise<void> {
  return new Promise((resolve) => t.write(data, resolve));
}
function maxBlankRun(t: Terminal): number {
  const buf = t.buffer.active;
  let maxRun = 0, run = 0;
  for (let i = 0; i < buf.length; i++) {
    if ((buf.getLine(i)?.translateToString(true) ?? "") === "") {
      run++; if (run > maxRun) maxRun = run;
    } else run = 0;
  }
  return maxRun;
}

describe("linearizeSpoolPage — sequence rewriting", () => {
  it("strips scroll-down / erase-display / cursor-position / scroll-region", () => {
    const out = dec(linearizeSpoolPage(enc("a\x1b[10Tb\x1b[2Jc\x1b[5;10Hd\x1b[1;24re\x1b[3Sf")));
    expect(out).toBe("abcdef");
  });
  it("degrades cursor up/down to a single line feed", () => {
    const out = dec(linearizeSpoolPage(enc("x\x1b[3Ay\x1b[2Bz")));
    expect(out).toBe("x\ny\nz");
  });
  it("strips alt-screen toggles but keeps other DECSET/DECRST verbatim", () => {
    const out = dec(linearizeSpoolPage(enc("a\x1b[?1049hb\x1b[?1049lc\x1b[?25hd")));
    expect(out).toBe("abc\x1b[?25hd"); // cursor visibility survives
  });
  it("keeps SGR (colors) and EL (in-line erase) verbatim", () => {
    const raw = "a\x1b[31mred\x1b[0mb\r\x1b[2Kc";
    expect(dec(linearizeSpoolPage(enc(raw)))).toBe(raw);
  });
  it("passes UTF-8 payload through untouched", () => {
    const raw = "中文内容\x1b[32m绿色\x1b[0m✓";
    expect(dec(linearizeSpoolPage(enc(raw)))).toBe(raw);
  });
  it("degrades ESC M (two-byte reverse index) to a line feed", () => {
    expect(dec(linearizeSpoolPage(enc("a\x1bMb")))).toBe("a\nb");
  });
});

describe("linearizeSpoolPage — end-to-end band elimination (real buffer)", () => {
  async function replayBand(page: string, linearize: boolean): Promise<number> {
    const t = new Terminal({ scrollback: 1000, cols: 80, rows: 24 });
    t.clear();
    const u8 = linearize ? linearizeSpoolPage(enc(page)) : enc(page);
    await write(t, new TextDecoder().decode(u8));
    await write(t, "tail\r\n");
    return maxBlankRun(t);
  }

  it("scroll-down choreography: band collapses after linearization", async () => {
    let s = "";
    for (let round = 0; round < 100; round++) {
      s += `head-${round}\r\n\x1b[10Ttail-${round}\r\n`;
    }
    const raw = await replayBand(s, false);
    const lin = await replayBand(s, true);
    expect(raw).toBeGreaterThan(100);   // the reproduced bug
    expect(lin).toBeLessThan(5);        // fixed
  });

  it("full-clear redraw: band collapses, content stays readable", async () => {
    let s = "";
    for (let round = 0; round < 60; round++) {
      for (let i = 0; i < 20; i++) s += `r${round}-${i} yyyyyyyyyyyyyyyyyyyy\r\n`;
      s += "\x1b[2J\x1b[H";
    }
    const raw = await replayBand(s, false);
    const lin = await replayBand(s, true);
    expect(raw).toBeGreaterThanOrEqual(20); // ~a full viewport of blank
    expect(lin).toBeLessThan(5);
  });
});
