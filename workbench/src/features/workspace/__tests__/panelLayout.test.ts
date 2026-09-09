/**
 * FIX-3: panel drag & collapse — source contracts on WorkspaceView.
 *
 * jsdom does no layout and SFC styles are not injected, and WorkspaceView's
 * ready branch needs the full workspace store chain — so the load-bearing
 * geometry is pinned as a SOURCE contract (same paradigm as
 * paneCloseHit.test.ts / tokens.test.ts), plus the i18n key pair check.
 * The numeric logic (clamp / persistence / appScale) lives in
 * lib/__tests__/panelLayout.test.ts.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { zhCN } from "../../../i18n/zh-CN";
import { enUS } from "../../../i18n/en-US";

const SRC = resolve(process.cwd(), "src");

function src(file: string): string {
  return readFileSync(join(SRC, file), "utf8");
}

describe("FIX-3 source contracts — WorkspaceView.vue", () => {
  const s = () => src("features/workspace/WorkspaceView.vue");

  it("dock width and min-width move together (the 240px floor must not push the rail open)", () => {
    const v = s();
    expect(v).toContain("minWidth: `${EXPLORER_COLLAPSED_W}px`");
    expect(v).toMatch(/const w = `\$\{panelLayout\.explorerWidth\}px`;\s*\n\s*return \{ width: w, minWidth: w \};/);
  });

  it("compact tier hands the width to the responsive rule (no inline width)", () => {
    expect(s()).toContain('if (props.tier === "compact") return undefined;');
    // the responsive rule itself now lives HERE (was a dead rule in App.vue)
    expect(s()).toContain(".tier-compact .explorer-dock:not(.collapsed)");
    expect(s()).toContain(".tier-compact .status-drawer");
  });

  it("handle hidden when collapsed or compact (no dead handles)", () => {
    expect(s()).toContain(
      `v-if="!panelLayout.explorerCollapsed && props.tier !== 'compact'"`);
  });

  it("Explorer content is KEPT ALIVE through collapse (v-show, never v-if)", () => {
    expect(s()).toContain('<WorkspaceExplorer v-show="!panelLayout.explorerCollapsed" />');
  });

  it("width transition rides ONLY on collapse/expand — drags and keyboard nudges stay instant", () => {
    const v = s();
    expect(v).toContain(".explorer-dock.anim");
    expect(v).toMatch(
      /\.explorer-dock\.anim \{\s*\n\s*transition: width var\(--duration-slow\) var\(--ease\),\s*\n\s*min-width var\(--duration-slow\) var\(--ease\);/);
    // the drag path drops .anim for the whole gesture
    expect(v).toContain("dockAnimating.value = false;");
    expect(v).toContain("dockAnimating.value = true;");
  });

  it("both separators are accessible (role + orientation + keyboard)", () => {
    const v = s();
    expect(v).toMatch(/class="dock-handle"[\s\S]{0,200}role="separator"/);
    expect(v).toMatch(/aria-orientation="vertical"/);
    expect(v).toMatch(/class="tab-divider"[\s\S]{0,200}role="separator"/);
    expect(v).toMatch(/aria-orientation="horizontal"/);
  });

  it("drag math is incremental with the appScale conversion (no rect reads)", () => {
    const v = s();
    expect(v).toContain("setExplorerWidth(startW + (ev.clientX - startX) / scale)");
    expect(v).toContain("setTabbarHeight(startH + (ev.clientY - startY) / scale)");
  });

  it("TabBar height: null keeps the natural height (no explicit style)", () => {
    expect(s()).toMatch(/panelLayout\.tabbarHeight != null\s*\n\s*\? \{ height: `\$\{panelLayout\.tabbarHeight\}px` \}\s*\n\s*: undefined/);
  });
});

describe("FIX-3 source contracts — App.vue dead rules removed", () => {
  it("the never-matching compact overrides are gone (only topbar rules remain)", () => {
    const v = src("App.vue");
    expect(v).not.toContain('[data-tier="compact"] .explorer-dock');
    expect(v).not.toContain('[data-tier="compact"] .status-drawer');
    expect(v).not.toContain('[data-tier="compact"] .sidebar');
    expect(v).toContain('[data-tier="compact"] .topbar'); // the live ones stay
    expect(v).toContain(':tier="layoutTier"');
  });
});

describe("FIX-3 i18n — both locales carry the new keys", () => {
  const keys = ["explorer.collapse", "explorer.expand", "explorer.resizeHandle", "explorer.tabbarResize"] as const;

  it("zh-CN and en-US agree on every key", () => {
    for (const k of keys) {
      expect(zhCN[k], `zh-CN missing ${k}`).toBeTruthy();
      expect(enUS[k], `en-US missing ${k}`).toBeTruthy();
    }
  });
});
