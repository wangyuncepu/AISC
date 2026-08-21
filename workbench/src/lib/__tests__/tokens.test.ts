/**
 * Stage 6 (A-UX01-1) design-token gate — extended by Stage 10 (10b, A-UI10-02).
 *
 * - styles.css defines the design-token set (spacing/type/radius/shadow/
 *   z-index/duration/line-height/control-height/border/focus-ring) plus the
 *   semantic + status color tokens.
 * - Component `<style>` blocks must NOT contain raw hex color literals — every
 *   theme color is `var(--*)`. Guards against new hardcoded theme values
 *   ("组件无新增主题硬编码").
 * - 10b: every `var(--token)` reference must resolve (globally in styles.css
 *   or locally in the same <style> block); bare rgb()/rgba() needs a
 *   whitelist entry carrying file + reason + expiry stage; the eight native
 *   primitives and their variants must stay defined.
 *
 * Resolves src/ from the vitest cwd (workbench/), mirroring cliFixtures.test.ts.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");
const STYLES = join(SRC, "styles.css");

/** Required design-token families (one representative per family). */
const REQUIRED_TOKENS = [
  "--space-",  // spacing
  "--font-",   // type
  "--font-mono", // mono family (UI chrome only)
  "--leading-", // 10b line-height
  "--radius-", // radius
  "--control-h-", // 10b control heights
  "--shadow-", // shadow
  "--border-w", // 10b border widths
  "--focus-ring-", // 10b focus ring dimensions
  "--z-",      // z-index
  "--duration-", // duration (fast/normal/slow)
  "--bg",      // semantic colors exist too
  "--status-ok",
  "--scrim",   // 10b overlay backdrop
  "--accent-soft", // 10b tinted-state family
  "--success-soft",
  "--warn-soft",
  "--error-soft",
  "--info-soft",
];

/** The eight native primitives (10b) + contracted variants. */
const REQUIRED_PRIMITIVES = [
  ".ui-button",
  ".ui-button.primary",
  ".ui-button.quiet",
  ".ui-button.danger",
  ".ui-button.sm",
  ".ui-button.lg",
  ".ui-icon-button",
  ".ui-icon-button.sm",
  ".ui-field",
  ".ui-field.mono",
  ".ui-field.invalid",
  ".ui-panel",
  ".ui-panel.elevated",
  ".ui-section",
  ".ui-section-title",
  ".ui-section-row",
  ".ui-section-row.selected",
  ".ui-badge",
  ".ui-badge.ok",
  ".ui-badge.warn",
  ".ui-badge.error",
  ".ui-badge.info",
  ".ui-badge.accent",
  ".ui-menu",
  ".ui-menu-item",
  ".ui-feedback",
  ".ui-feedback.info",
  ".ui-feedback.success",
  ".ui-feedback.warn",
  ".ui-feedback.error",
];

/**
 * Bare rgb()/rgba() audit whitelist (10b). Each entry: max occurrences per
 * file, with reason + the stage gate that retires it. Shrinks in 10c/10d;
 * new entries need a reason and an expiry stage (04 §1).
 */
const RGBA_WHITELIST: Record<string, { max: number; reason: string; expiry: string }> = {
  "features/ccswitch/CcSwitchUiTab.vue": { max: 1, reason: "toast scrim", expiry: "10d → --scrim" },
  "features/doctor/DoctorDialog.vue": { max: 1, reason: "dialog scrim", expiry: "10d → --scrim" },
  "features/terminal/PaneTree.vue": { max: 1, reason: "pane divider tint", expiry: "10c → token" },
  "features/workspace/WorkspaceBar.vue": { max: 1, reason: "overlay scrim", expiry: "10c → --scrim" },
  "features/workspace/WorkspaceView.vue": { max: 1, reason: "overlay scrim", expiry: "10c → --scrim" },
};

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

/** Remove `var(--token, #fallback | rgba() fallback)` fallback expressions —
 *  those mirror the token's default for test mounts without styles.css, not
 *  hardcoded colors. */
function stripFallbacks(css: string): string {
  return css.replace(
    /var\(--[\w-]+,\s*(?:#[0-9a-fA-F]{3,6}|rgba?\([^)]*\))\s*\)/g,
    "var(--fallback)",
  );
}

/** Custom-property definitions (`--x: …`) in a CSS source. */
function cssDefinitions(css: string): Set<string> {
  const out = new Set<string>();
  const re = /(^|[\s{;])(--[\w-]+)\s*:/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) out.add(m[2]);
  return out;
}

/** Custom-property references (`var(--x)`) in a CSS source. */
function cssReferences(css: string): Set<string> {
  const out = new Set<string>();
  const re = /var\((--[\w-]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) out.add(m[1]);
  return out;
}

function vueFiles(): string[] {
  const files: string[] = [];
  collectVue(SRC, files);
  return files;
}

describe("design tokens (A-UX01-1)", () => {
  it("styles.css defines the design-token set", () => {
    const css = readFileSync(STYLES, "utf8");
    for (const tok of REQUIRED_TOKENS) {
      expect(css).toContain(tok);
    }
  });

  it("no raw hex color literals in component styles", () => {
    const offenders: string[] = [];
    for (const f of vueFiles()) {
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

describe("token reference contract (A-UI10-02, 10b)", () => {
  it("every var(--token) reference resolves to a definition", () => {
    const stylesCss = readFileSync(STYLES, "utf8");
    const globalDefs = cssDefinitions(stylesCss);
    const offenders: string[] = [];

    // styles.css itself must not reference phantom tokens either.
    for (const ref of cssReferences(stylesCss)) {
      if (!globalDefs.has(ref)) offenders.push(`styles.css: ${ref}`);
    }

    for (const f of vueFiles()) {
      const src = readFileSync(f, "utf8");
      for (const block of styleBlocks(src)) {
        const localDefs = cssDefinitions(block);
        for (const ref of cssReferences(block)) {
          if (!globalDefs.has(ref) && !localDefs.has(ref)) {
            offenders.push(`${relative(SRC, f)}: ${ref}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("bare rgb()/rgba() only appears in the audited whitelist", () => {
    const offenders: string[] = [];
    for (const f of vueFiles()) {
      const rel = relative(SRC, f).split("\\").join("/");
      const src = readFileSync(f, "utf8");
      const counts = styleBlocks(src)
        .map((block) =>
          (stripFallbacks(block).match(/rgba?\([^)]*\)/g) ?? []).length)
        .reduce((a, b) => a + b, 0);
      const entry = RGBA_WHITELIST[rel];
      if (counts === 0) continue;
      if (!entry) offenders.push(`${rel}: ${counts} bare rgba()/rgb() (not whitelisted)`);
      else if (counts > entry.max) {
        offenders.push(`${rel}: ${counts} > whitelisted max ${entry.max} (${entry.reason})`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("native primitives and variants stay defined in styles.css", () => {
    const css = readFileSync(STYLES, "utf8");
    const missing = REQUIRED_PRIMITIVES.filter((p) => !css.includes(p));
    expect(missing).toEqual([]);
  });
});
