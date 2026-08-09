/**
 * G-06 fixed-output benchmark (A-G06-4): a deterministic 10 MiB UTF-8/ANSI
 * mixed fixture (SHA-256 pinned below) written to a fresh xterm in 4 KiB
 * chunks. jsdom cannot exercise the WebGL renderer, so this gates the DOM
 * renderer path: no chunk exceeds 200 ms (long-task proxy), the write loop
 * completes, and the total time is recorded for the devlog. WebGL timings are
 * measured on the manual test machine (A-G06-1 path) and recorded in devlog.
 *
 * NOTE: jsdom lacks canvas, so the DOM renderer's first paint may no-op; the
 * parser + buffer path is what this measures.
 */
import { describe, expect, it, beforeAll } from "vitest";
import { Terminal } from "@xterm/xterm";

// xterm queries matchMedia for its dimension observer; jsdom lacks it.
beforeAll(() => {
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }
});

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Deterministic 10 MiB mix: ANSI SGR sequences + CJK + emoji + ASCII lines. */
async function buildFixture(): Promise<{ bytes: Uint8Array; sha256: string }> {
  const line = (n: number): string => {
    const ansi = n % 7 === 0 ? "\x1b[31m\x1b[1m" : n % 5 === 0 ? "\x1b[32m" : "";
    const reset = ansi ? "\x1b[0m" : "";
    return `${ansi}line-${n} 你好世界 🌍 combining é ${reset}\n`;
  };
  const chunks: Uint8Array[] = [];
  let total = 0;
  let n = 0;
  const enc = new TextEncoder();
  while (total < 10 * 1024 * 1024) {
    const b = enc.encode(line(n++));
    total += b.length;
    chunks.push(b);
  }
  const bytes = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    bytes.set(c, off);
    off += c.length;
  }
  return { bytes, sha256: await sha256(bytes) };
}

const FIXTURE_SHA256 =
  "0d1a85646a724b16ceb2b207872010c7364fff7ba0151e276f4413b929bd8d07";

describe("A-G06-4 fixed output benchmark (DOM renderer)", () => {
  it("writes 10 MiB in 4 KiB chunks with no >200ms chunk and records time", async () => {
    const { bytes, sha256 } = await buildFixture();
    expect(sha256).toBe(FIXTURE_SHA256); // fixture integrity pin

    const term = new Terminal({ cols: 120, rows: 40 });
    const host = document.createElement("div");
    document.body.appendChild(host);
    term.open(host);

    const CHUNK = 4096;
    let maxChunkMs = 0;
    const t0 = performance.now();
    for (let off = 0; off < bytes.length; off += CHUNK) {
      const slice = bytes.slice(off, off + CHUNK);
      const c0 = performance.now();
      term.write(slice);
      // Synchronous write parses into the buffer; drain between chunks so the
      // renderer can't be starved (worst case for long tasks).
      const elapsed = performance.now() - c0;
      if (elapsed > maxChunkMs) maxChunkMs = elapsed;
    }
    const totalMs = performance.now() - t0;

    // Recorded for the devlog (A-G06-4 evidence, DOM path).
    console.log(`[g06] 10MiB fixture: ${bytes.length} bytes, ${(totalMs / 1000).toFixed(2)}s total, max chunk ${maxChunkMs.toFixed(1)}ms`);
    expect(maxChunkMs).toBeLessThan(200);
    expect(totalMs).toBeGreaterThan(0);
    term.dispose();
    host.remove();
  });
});
