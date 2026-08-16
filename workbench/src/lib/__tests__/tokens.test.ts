/**
 * Stage 6 (A-UX01-1): design-token gate.
 *
 * - styles.css defines the design-token set (spacing/type/radius/shadow/
 *   z-index/duration) plus the semantic + status color tokens.
 * - Component `<style>` blocks must NOT contain raw hex color literals — every
 *   theme color is `var(--*)`. Guards against new hardcoded theme values
 *   ("组件无新增主题硬编码").
 *
 * Resolves src/ from the vitest cwd (workbench/), mirroring cliFixtures.test.ts.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");

/** Required design-token families (one representative per family). */
const REQUIRED_TOKENS = [
  "--space-",  // spacing
  "--font-",   // type
  "--radius-", // radius
  "--shadow-", // shadow
  "--z-",      // z-index
  "--duration-", // duration
  "--bg",      // semantic colors exist too
  "--status-ok",
];

function collectVue(dir: string, out: string[]): void {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) collectVue(p, out);
    else if (name.endsWith(".vue")) out.push(p);
  }
}

/** Extract the text inside every <style …> block of a .vue source. */
function styleBlocks(src: string): string[] {
  const blocks: string[] = [];
  const re = /<style[^>]*>([\s\S]*?)<\/style>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) blocks.push(m[1]);
  return blocks;
}

/** Remove `var(--token, #fallback)` fallback expressions — those mirror the
 *  token's default for test mounts without styles.css, not hardcoded colors. */
function stripFallbacks(css: string): string {
  return css.replace(/var\(--[\w-]+,\s*#[0-9a-fA-F]{3,6}\s*\)/g, "var(--fallback)");
}

describe("design tokens (A-UX01-1)", () => {
  it("styles.css defines the design-token set", () => {
    const css = readFileSync(join(SRC, "styles.css"), "utf8");
    for (const tok of REQUIRED_TOKENS) {
      expect(css).toContain(tok);
    }
  });

  it("no raw hex color literals in component styles", () => {
    const files: string[] = [];
    collectVue(SRC, files);
    const offenders: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      styleBlocks(src).forEach((block, i) => {
        const hex = stripFallbacks(block).match(/#[0-9a-fA-F]{3,6}\b/g) ?? [];
        if (hex.length) {
          offenders.push(`${relative(SRC, f)} (style ${i}): ${hex.join(", ")}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });
});
