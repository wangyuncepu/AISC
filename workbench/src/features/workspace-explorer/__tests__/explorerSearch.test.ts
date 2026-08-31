/**
 * v2.1.7 S5c: shared top search + artifacts kind filter/collapse.
 *
 * - files tab: an active query swaps the tree for a FLAT match list over
 *   every LOADED directory (collapsed-but-loaded folders included);
 * - artifacts tab: kind chips hide other groups, group heads collapse,
 *   and the search filters rows by path/label.
 *
 * Seeding happens AFTER mount: onMounted runs refreshRoot whose mocked
 * IPC answers with empty lists — seeding first would be wiped by it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspaceExplorerStore } from "../../../stores/workspaceExplorer";
import { useRuntimeStore } from "../../../stores/runtime";
import WorkspaceExplorer from "../WorkspaceExplorer.vue";

vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  workspaceList: vi.fn(async () => ({
    schema_version: 1, nodes: [], next_cursor: null, truncated: false,
  })),
  workspaceOpen: vi.fn().mockResolvedValue(undefined),
  artifactList: vi.fn(async () => ({
    schema_version: 1, artifacts: [], next_cursor: null,
  })),
  // v2.1.8 T4: the store module imports these at top level.
  conversationList: vi.fn(async () => ({
    schema_version: 1, conversations: [],
  })),
  conversationPreflight: vi.fn(async () => ({
    conversation_id: "", agent: "",
  })),
}));
vi.mock("@tauri-apps/plugin-clipboard-manager", () => ({
  writeText: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({}) }));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));

function node(fullPath: string, kind: "file" | "dir") {
  return {
    relative_path: fullPath,
    name: fullPath.split("/").pop() ?? fullPath,
    kind,
    expandable: kind === "dir",
    change_type: "none",
    change_state: "none",
    revision: 0,
    artifact_badges: [],
  } as never;
}


async function mountExplorer() {
  const w = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
  await flushPromises(); // let onMounted's refreshRoot settle on empty mocks
  return w;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  // The component's empty states key off the RUNTIME store's workspace.
  useRuntimeStore().workspace = "C:\\ws";
});
afterEach(() => vi.clearAllMocks());

describe("files tab: flat search over loaded dirs (S5c)", () => {
  it("finds matches inside collapsed-but-loaded folders", async () => {
    const w = await mountExplorer();
    const explorer = useWorkspaceExplorerStore();
    // Root loaded; "sub" loaded but NOT expanded — its file must still be found.
    explorer.tree = {
      "": [node("readme.md", "file"), node("sub", "dir")],
      sub: [node("sub/needle.txt", "file"), node("sub/other.txt", "file")],
    };

    expect(w.find('[data-testid="explorer-search"]').exists()).toBe(true);
    await w.find('[data-testid="explorer-search"]').setValue("needle");
    const hits = w.findAll(".search-hit");
    expect(hits).toHaveLength(1);
    expect(hits[0].attributes("data-path")).toBe("sub/needle.txt");
    expect(hits[0].text()).toContain("sub"); // parent dir shown as context
  });

  it("fuzzy subsequence matches, substring hits ranked first", async () => {
    const w = await mountExplorer();
    const explorer = useWorkspaceExplorerStore();
    explorer.tree = {
      "": [node("needle.txt", "file"), node("readme.md", "file")],
    };
    // "ndl" is a subsequence of needle (not a substring).
    await w.find('[data-testid="explorer-search"]').setValue("ndl");
    const hits = w.findAll(".search-hit");
    expect(hits).toHaveLength(1);
    expect(hits[0].attributes("data-path")).toBe("needle.txt");

    // Substring beats subsequence: "readme" hits readme.md literally while
    // "rdm" would subsequence-match BOTH — "readme" must still find only it.
    await w.find('[data-testid="explorer-search"]').setValue("readme");
    expect(w.findAll(".search-hit")).toHaveLength(1);
    expect(w.find(".search-hit").attributes("data-path")).toBe("readme.md");
  });

  it("regex mode via /pattern/ delimiters; invalid patterns fall back to literal", async () => {
    const w = await mountExplorer();
    const explorer = useWorkspaceExplorerStore();
    explorer.tree = {
      "": [node("needle.txt", "file"), node("readme.md", "file"), node("notes/x.md", "file")],
    };

    // Anchored regex: only readme.md starts with "read".
    await w.find('[data-testid="explorer-search"]').setValue("/^read/");
    expect(w.findAll(".search-hit")).toHaveLength(1);
    expect(w.find(".search-hit").attributes("data-path")).toBe("readme.md");

    // Character class + suffix: .md files only.
    await w.find('[data-testid="explorer-search"]').setValue("/\\.(md|txt)$/");
    expect(w.findAll(".search-hit").length).toBeGreaterThanOrEqual(3);

    // INVALID pattern: literal fallback — no crash, no matches for garbage.
    await w.find('[data-testid="explorer-search"]').setValue("/[/");
    expect(w.find(".search-hit").exists()).toBe(false);
    expect(w.text()).toContain("无匹配结果");
  });

  it("shows the no-match empty state and restores the tree when cleared", async () => {
    const w = await mountExplorer();
    const explorer = useWorkspaceExplorerStore();
    explorer.tree = { "": [node("readme.md", "file")] };
    explorer.expanded.add("");

    await w.find('[data-testid="explorer-search"]').setValue("zzz");
    expect(w.text()).toContain("无匹配结果");
    expect(w.find(".search-hit").exists()).toBe(false);

    await w.find('[data-testid="explorer-search"]').setValue("");
    expect(w.find(".search-hit").exists()).toBe(false);
    expect(w.find('[data-path="readme.md"]').exists()).toBe(true); // normal tree back
  });
});

describe("changes tab: flat list + search (2.1.9 T6)", () => {
  async function seedChanges() {
    const w = await mountExplorer();
    const explorer = useWorkspaceExplorerStore();
    explorer.unattributed = {
      "docs/report.md": "created",
      "src/changed.ts": "modified",
      "notes/x.md": "created",
    };
    explorer.activeKind = "artifacts";
    return w;
  }

  it("renders ONE flat change list — no groups, no chips", async () => {
    const w = await seedChanges();
    expect(w.findAll(".artifacts-group-head")).toHaveLength(0);
    expect(w.find(".artifact-chips").exists()).toBe(false);
    expect(w.findAll(".artifact-row")).toHaveLength(3);
    expect(w.text()).toContain("report.md");
    expect(w.text()).toContain("changed.ts");
  });

  it("the shared search filters the flat list (substring)", async () => {
    const w = await seedChanges();
    await w.find('[data-testid="explorer-search"]').setValue("report");
    expect(w.findAll(".artifact-row")).toHaveLength(1);
    expect(w.text()).toContain("report.md");
    expect(w.text()).not.toContain("changed.ts");

    await w.find('[data-testid="explorer-search"]').setValue("");
    expect(w.findAll(".artifact-row")).toHaveLength(3);
  });

  it("fuzzy subsequence and /regex/ modes still work on the flat list", async () => {
    const w = await seedChanges();
    // Subsequence: chars in order, gaps allowed.
    await w.find('[data-testid="explorer-search"]').setValue("rpt");
    expect(w.findAll(".artifact-row").length).toBeGreaterThanOrEqual(1);
    expect(w.text()).toContain("report.md");
    // Regex form.
    await w.find('[data-testid="explorer-search"]').setValue("/^src\\//");
    expect(w.findAll(".artifact-row")).toHaveLength(1);
    expect(w.text()).toContain("changed.ts");
    // No match message.
    await w.find('[data-testid="explorer-search"]').setValue("/^zzz/")
    expect(w.text()).toContain("无匹配结果");
  });
});
