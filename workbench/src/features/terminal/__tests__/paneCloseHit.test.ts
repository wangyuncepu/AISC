/**
 * O1 (opt-batch, D-11): pane × vs xterm scrollbar — hit-area contract.
 *
 * 手测报障: 分屏的 × 点不了. Root cause: .pane-close (z2) shared a stacking
 * context with the xterm scrollbar (.visible z11, pinned to the right edge,
 * pointer-active while visible) and overlapped its band; the truncation
 * banner (right:10px) visually covered the rest of the corner.
 *
 * jsdom does no layout and SFC styles are not injected, so the geometry is
 * pinned as a SOURCE contract on the two scoped rules (same paradigm as
 * tokens.test.ts / layerContract.test.ts); the click path itself is exercised
 * by mounting PaneTree against the real store.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import PaneTree from "../PaneTree.vue";

const mockIpc = vi.hoisted(() => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  getProviderStatus: vi.fn().mockResolvedValue({}),
  closeSession: vi.fn().mockResolvedValue({ reason: "user_close", exitCode: null }),
  loadHistory: vi.fn().mockResolvedValue({ schema_version: 2, revision: 0, workspaces: [] }),
  saveHistory: vi.fn().mockResolvedValue(1),
  negotiateCapabilities: vi.fn(),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  ackSessionExit: vi.fn().mockResolvedValue("acknowledged"),
  openSession: vi.fn().mockResolvedValue({}),
  writeSession: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../../lib/ipc", () => mockIpc);
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn().mockResolvedValue(true), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: vi.fn(() => ({
    isFocused: vi.fn().mockResolvedValue(true),
    isMinimized: vi.fn().mockResolvedValue(false),
  })),
}));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(false),
  requestPermission: vi.fn().mockResolvedValue("denied"),
  sendNotification: vi.fn().mockResolvedValue(undefined),
}));
// PaneTree renders Terminal for live panes; xterm cannot run in jsdom. The
// click target (.pane-close) lives OUTSIDE Terminal, so the leaf stubs are fine.
vi.mock("../Terminal.vue", () => ({ default: { name: "Terminal", template: "<div class='term-stub' />" } }));
vi.mock("../GuidePane.vue", () => ({ default: { name: "GuidePane", template: "<div class='guide-stub' />" } }));

const SRC = resolve(process.cwd(), "src");

/** Style blocks of a .vue source (tokens.test.ts paradigm). */
function styleBlocks(file: string): string[] {
  const src = readFileSync(join(SRC, file), "utf8");
  const blocks: string[] = [];
  const re = /<style[^>]*>([\s\S]*?)<\/style>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) blocks.push(m[1]!);
  return blocks;
}

/** Declaration value of `prop` inside the `selector { … }` rule of a block. */
function decl(selector: string, prop: string): string {
  const blocks = styleBlocks("features/terminal/PaneTree.vue")
    .concat(styleBlocks("features/terminal/Terminal.vue"));
  for (const block of blocks) {
    const at = block.indexOf(selector);
    if (at < 0) continue;
    const open = block.indexOf("{", at);
    const close = block.indexOf("}", open);
    const m = block.slice(open + 1, close).match(new RegExp(`${prop}\\s*:\\s*([^;]+);`));
    if (m) return m[1]!.trim();
  }
  throw new Error(`rule ${selector} { ${prop}: … } not found`);
}

function px(value: string): number {
  const n = Number.parseInt(value, 10);
  expect(Number.isFinite(n), `expected a px value, got "${value}"`).toBe(true);
  return n;
}

describe("O1: × clears the scrollbar band and stacks above it (D-11)", () => {
  it(".pane-close sits right of the xterm scrollbar column (≤14px) + 4px margin", () => {
    // × band = [right, right+20]. The scrollbar (z11, pointer-active when
    // .visible) owns the right ≤14px — the × must not enter it.
    expect(px(decl(".pane-close", "right"))).toBeGreaterThanOrEqual(18);
  });

  it(".pane-close z-index resolves above the scrollbar's 11", () => {
    const z = decl(".pane-close", "z-index");
    expect(z).toBe("var(--z-overlay)"); // token, never a bare magic number
    const styles = readFileSync(join(SRC, "styles.css"), "utf8");
    const m = styles.match(/--z-overlay:\s*(\d+)/);
    expect(m, "--z-overlay must stay a numeric token").toBeTruthy();
    expect(Number(m![1])).toBeGreaterThan(11); // scrollbar .visible z
  });

  it(".truncation-banner is staggered off the × band (no overlap at [18,38]px)", () => {
    // banner grows leftward from its right anchor → the anchor itself must
    // clear the × band's inner edge (right 18 + width 20).
    expect(px(decl(".truncation-banner", "right"))).toBeGreaterThanOrEqual(38);
  });
});

describe("O1: clicking × closes the pane (component)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    i18n.global.locale.value = "zh-CN";
  });

  async function splitFixture(): Promise<{ s: ReturnType<typeof useRuntimeStore>; tabId: string; paneId: string }> {
    const s = useRuntimeStore();
    s.runtimeState = "running";
    s.runtimeId = "rid";
    const tabId = s.createTab("bash")!;
    const paneId = s.splitTabPane(tabId, "horizontal", "bash")!;
    await new Promise((r) => setTimeout(r, 0));
    return { s, tabId, paneId };
  }

  it("multi-leaf pane renders ×; click closes the leaf and collapses the split", async () => {
    const { s, tabId, paneId } = await splitFixture();
    const wrapper = mount(PaneTree, {
      props: { tabId, tree: s.tabs.find((t) => t.tabId === tabId)!.tree },
      global: { plugins: [i18n] },
    });

    const x = wrapper.findAll(".pane-close");
    expect(x.length).toBe(2); // one per leaf of the split
    // The exact interaction that failed in the field: pointerdown over the
    // corner (scrollbar fading in) + click must still reach the × handler.
    // findAll is DOM order → [0] is the FIRST leaf (pane id = tabId).
    await x[0]!.trigger("pointerdown");
    await x[0]!.trigger("click");

    const tab = s.tabs.find((t) => t.tabId === tabId)!;
    expect(tab.panes[tabId]).toBeUndefined(); // first leaf removed
    expect(tab.tree.kind).toBe("pane"); // parent split collapsed…
    // …onto the surviving sibling (narrow the union for vue-tsc).
    expect(tab.tree.kind === "pane" && tab.tree.paneId === paneId).toBe(true);
    // Single pane left → no more close buttons anywhere.
    expect(wrapper.find(".pane-close").exists()).toBe(false);
    wrapper.unmount();
  });
});
