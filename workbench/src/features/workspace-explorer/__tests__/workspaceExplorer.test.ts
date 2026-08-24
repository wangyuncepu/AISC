/**
 * Stage 3 (3f, A-WX05-1): Explorer keyboard/APG tree behavior.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import { useWorkspaceExplorerStore } from "../../../stores/workspaceExplorer";
import WorkspaceExplorer from "../WorkspaceExplorer.vue";

vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock("@tauri-apps/plugin-clipboard-manager", () => ({
  writeText: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  workspaceList: vi.fn(async (_ws: string, dir: string) => ({
    schema_version: 1,
    nodes:
      dir === ""
        ? [
            { relative_path: "src", name: "src", kind: "dir", expandable: true, artifact_badges: [], change_state: "unknown" },
            { relative_path: "a.md", name: "a.md", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ]
        : [
            { relative_path: "src/main.ts", name: "main.ts", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ],
    next_cursor: null,
    truncated: false,
  })),
  workspaceOpen: vi.fn().mockResolvedValue(undefined),
  workspaceCreateFile: vi.fn().mockResolvedValue({
    schema_version: 1,
    operation: "create_file",
    relative_path: "new.md",
    kind: "file",
  }),
  workspaceCreateDir: vi.fn().mockResolvedValue({
    schema_version: 1,
    operation: "create_dir",
    relative_path: "newdir",
    kind: "dir",
  }),
  workspaceCopyEntry: vi.fn().mockResolvedValue({
    schema_version: 1,
    operation: "copy",
    relative_path: "src/a.md",
    kind: "file",
  }),
  workspaceRename: vi.fn().mockResolvedValue({
    schema_version: 1,
    operation: "rename",
    relative_path: "renamed.md",
    kind: "file",
  }),
  workspacePreview: vi.fn().mockResolvedValue({ relative_path: "a.md", media_type: "text/markdown", size: 2, text: "hi", base64: null, truncated: false }),
  workspaceReveal: vi.fn().mockResolvedValue(undefined),
  workspaceCopyPath: vi.fn().mockResolvedValue({ relative_path: "a.md", absolute_path: "/ws/a.md" }),
  workspaceWatchStart: vi.fn().mockResolvedValue(undefined),
  workspaceWatchStop: vi.fn().mockResolvedValue(undefined),
  workspaceRescan: vi.fn().mockResolvedValue(undefined),
  artifactList: vi.fn().mockResolvedValue({ schema_version: 1, artifacts: [], next_cursor: null }),
  artifactInspect: vi.fn(),
  artifactRefresh: vi.fn(),
}));

async function setup() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const runtime = useRuntimeStore();
  runtime.workspace = "/ws";
  const explorer = useWorkspaceExplorerStore();
  explorer.setWorkspace("/ws");
  await explorer.loadDir(""); // pre-populate the tree so rows exist at mount
  return { runtime, explorer };
}

beforeEach(() => {
  i18n.global.locale.value = "zh-CN";
  // The ipc module mock is created once per file; without clearing, call
  // counts leak across tests and `not.toHaveBeenCalled` asserts on history.
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkspaceExplorer keyboard (3f, A-WX05-1)", () => {
  it("ArrowDown/ArrowUp move roving focus; Enter activates a file", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const tree = wrapper.find("[role=tree]");
    const rows = wrapper.findAll("[role=treeitem]");
    expect(rows.length).toBe(2);

    await tree.trigger("keydown", { key: "ArrowDown" });
    expect(rows[0].attributes("tabindex")).toBe("0");
    await tree.trigger("keydown", { key: "ArrowDown" });
    expect(rows[1].attributes("tabindex")).toBe("0");
    await tree.trigger("keydown", { key: "ArrowUp" });
    expect(rows[0].attributes("tabindex")).toBe("0");

    // Enter activates the focused node (dir toggles expand -> loads children).
    await tree.trigger("keydown", { key: "ArrowDown" }); // focus a.md
    await tree.trigger("keydown", { key: "Enter" });
    // Stage 11 (D11-01/19): Enter opens the file; it no longer previews.
    const { workspaceOpen, workspacePreview } = await import("../../../lib/ipc");
    expect(workspaceOpen).toHaveBeenCalledWith("/ws", "a.md");
    expect(workspacePreview).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("Escape closes the context menu", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const tree = wrapper.find("[role=tree]");
    await tree.trigger("keydown", { key: "ArrowDown" });
    await tree.trigger("keydown", { key: "F10", shiftKey: true });
    expect(wrapper.find("[role=menu]").exists()).toBe(true);
    await tree.trigger("keydown", { key: "Escape" });
    expect(wrapper.find("[role=menu]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("mouse right-click opens the context menu at the pointer", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    expect(rows.length).toBe(2);

    // jsdom has no real layout: stub the viewport so the clamp stays positive.
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    await rows[0].trigger("contextmenu", { clientX: 1100, clientY: 300 });

    const menu = wrapper.find("[role=menu]");
    expect(menu.exists()).toBe(true);
    // Clamped into the viewport (drawer sits at the right edge); Stage 11
    // widened the menu to 200px, so the clamp is 1000 now.
    expect(menu.attributes("style")).toContain("left: 1000px");
    expect(menu.attributes("style")).toContain("top: 300px");
    wrapper.unmount();
  });

  it("divides pointer coords by the app CSS zoom (font_scale != 1)", async () => {
    // Regression (2026-08-16): the app chrome applies `zoom: 1.35` when
    // ui.font_scale is raised. Under a non-1 zoom, `position: fixed` resolves
    // against the zoomed ancestor, so clientX must be divided by the zoom or
    // the menu lands at clientX * 1.35 (off the viewport) and never shows.
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const app = document.createElement("div");
    app.className = "app";
    document.body.appendChild(app);
    // Simulate zoom 1.35: rect is 1.35x the offsetWidth.
    Object.defineProperty(app, "offsetWidth", { value: 800, configurable: true });
    Object.defineProperty(app, "getBoundingClientRect", {
      value: () => ({ width: 1080 }),
      configurable: true,
    });
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });

    const rows = wrapper.findAll("[role=treeitem]");
    await rows[0].trigger("contextmenu", { clientX: 540, clientY: 405 });

    const menu = wrapper.find("[role=menu]");
    expect(menu.exists()).toBe(true);
    // 540 / 1.35 = 400px in the menu's local space.
    expect(menu.attributes("style")).toContain("left: 400px");
    expect(menu.attributes("style")).toContain("top: 300px");
    app.remove();
    wrapper.unmount();
  });

  it("clicking the backdrop closes the menu", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    await rows[0].trigger("contextmenu", { clientX: 100, clientY: 100 });
    expect(wrapper.find("[role=menu]").exists()).toBe(true);
    await wrapper.find(".explorer-menu-backdrop").trigger("mousedown");
    expect(wrapper.find("[role=menu]").exists()).toBe(false);
    wrapper.unmount();
  });
});

describe("WorkspaceExplorer artifacts panel (WX-04)", () => {
  it("artifact rows have no open/reveal buttons; dblclick opens and right-click shows the menu", async () => {
    const { artifactList, workspaceOpen } = await import("../../../lib/ipc");
    vi.mocked(artifactList).mockResolvedValue({
      schema_version: 1,
      artifacts: [
        {
          schema_version: 1,
          artifact_id: "aaaaaaaa-0000-4000-8000-000000000001",
          workspace_relative_path: "reports/result.md",
          action: "created",
          kind: "deliverable",
          media_type: "text/markdown",
          label: "报告",
          open_with: "preview",
          producer: { agent: "claude", session_id: "s", runtime_id: "r" },
          state: "present",
          provenance: "manifest",
          recorded_at: "t",
          previous_path: null,
          extra: {},
        },
      ],
      next_cursor: null,
    });

    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    // Switch to the Artifacts tab.
    await wrapper.findAll("[role=tab]")[1].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));

    const row = wrapper.find(".artifact-row");
    expect(row.exists()).toBe(true);
    // No Open / Reveal / Copy buttons in the artifacts panel.
    expect(wrapper.findAll(".artifact-row .explorer-mini").length).toBe(0);
    // Single-click previews; double-click opens.
    await row.trigger("dblclick");
    expect(workspaceOpen).toHaveBeenCalledWith("/ws", "reports/result.md");
    // Right-click opens the shared context menu.
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    await row.trigger("contextmenu", { clientX: 300, clientY: 300 });
    expect(wrapper.find("[role=menu]").exists()).toBe(true);
    wrapper.unmount();
  });

  it("shows the workspace-relative path when basenames collide", async () => {
    const { artifactList } = await import("../../../lib/ipc");
    vi.mocked(artifactList).mockResolvedValue({
      schema_version: 1,
      artifacts: [
        {
          schema_version: 1,
          artifact_id: "aaaaaaaa-0000-4000-8000-000000000001",
          workspace_relative_path: "a/result.md",
          action: "created",
          kind: "deliverable",
          media_type: "text/markdown",
          label: "",
          open_with: "preview",
          producer: { agent: "claude", session_id: "s", runtime_id: "r" },
          state: "present",
          provenance: "manifest",
          recorded_at: "t",
          previous_path: null,
          extra: {},
        },
        {
          schema_version: 1,
          artifact_id: "aaaaaaaa-0000-4000-8000-000000000002",
          workspace_relative_path: "b/result.md",
          action: "created",
          kind: "deliverable",
          media_type: "text/markdown",
          label: "",
          open_with: "preview",
          producer: { agent: "claude", session_id: "s", runtime_id: "r" },
          state: "present",
          provenance: "manifest",
          recorded_at: "t",
          previous_path: null,
          extra: {},
        },
      ],
      next_cursor: null,
    });

    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    await wrapper.findAll("[role=tab]")[1].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));

    const names = wrapper.findAll(".artifact-row .explorer-name").map((n) => n.text());
    // Ambiguous basename `result.md` → show the full relative path to disambiguate.
    expect(names).toEqual(["a/result.md", "b/result.md"]);
    wrapper.unmount();
  });

  it("shows relative paths for colliding unattributed entries (created + modified)", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const explorer = useWorkspaceExplorerStore();
    // Watcher projection: same basename, different folders, one created one modified.
    explorer.handleWorkspaceChanges([
      { relative_path: "a/result.md", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "b/result.md", change_type: "modified", kind: "file", revision: 2 },
    ]);
    await wrapper.findAll("[role=tab]")[1].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));

    const names = wrapper.findAll(".unattributed .explorer-name").map((n) => n.text());
    // Ambiguous basename across the panel → full relative path on BOTH rows.
    expect(names).toEqual(["a/result.md", "b/result.md"]);
    wrapper.unmount();
  });

  it("shows relative paths when a manifest artifact collides with an unattributed entry", async () => {
    const { artifactList } = await import("../../../lib/ipc");
    vi.mocked(artifactList).mockResolvedValue({
      schema_version: 1,
      artifacts: [
        {
          schema_version: 1,
          artifact_id: "aaaaaaaa-0000-4000-8000-000000000001",
          workspace_relative_path: "reports/result.md",
          action: "created",
          kind: "deliverable",
          media_type: "text/markdown",
          label: "",
          open_with: "preview",
          producer: { agent: "claude", session_id: "s", runtime_id: "r" },
          state: "present",
          provenance: "manifest",
          recorded_at: "t",
          previous_path: null,
          extra: {},
        },
      ],
      next_cursor: null,
    });

    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const explorer = useWorkspaceExplorerStore();
    explorer.handleWorkspaceChanges([
      { relative_path: "scratch/result.md", change_type: "created", kind: "file", revision: 1 },
    ]);
    await wrapper.findAll("[role=tab]")[1].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));

    const artifactName = wrapper.find(".artifact-row .explorer-name").text();
    const unattributedName = wrapper.find(".unattributed .explorer-name").text();
    // Both rows show the relative path because the basename is ambiguous.
    expect(artifactName).toBe("reports/result.md");
    expect(unattributedName).toBe("scratch/result.md");
    wrapper.unmount();
  });
});

/** Stage 11 (11c): single-click select / double-click open semantics (D11-01). */
describe("WorkspaceExplorer activation semantics (11c)", () => {
  it("single-click selects a file without previewing; double-click opens it", async () => {
    const { workspaceOpen, workspacePreview } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");

    await rows[1].trigger("click"); // a.md (file)
    expect(rows[1].attributes("aria-selected")).toBe("true");
    expect(workspacePreview).not.toHaveBeenCalled();

    await rows[1].trigger("dblclick");
    expect(workspaceOpen).toHaveBeenCalledWith("/ws", "a.md");
    wrapper.unmount();
  });

  it("directory single-click still toggles expansion", async () => {
    await setup();
    const explorer = useWorkspaceExplorerStore();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    expect(explorer.isExpanded("src")).toBe(false);
    await rows[0].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(explorer.isExpanded("src")).toBe(true);
    wrapper.unmount();
  });

  it("Space selects the focused node without activating it", async () => {
    const { workspaceOpen } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const tree = wrapper.find("[role=tree]");
    await tree.trigger("keydown", { key: "ArrowDown" }); // focus src
    await tree.trigger("keydown", { key: " " });
    const rows = wrapper.findAll("[role=treeitem]");
    expect(rows[0].attributes("aria-selected")).toBe("true");
    expect(workspaceOpen).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});

/** Stage 11 (11c): toolbar new-file/new-folder/refresh (D11-17). */
describe("WorkspaceExplorer toolbar (11c)", () => {
  it("new-file creates at the selection-aware target (selected dir)", async () => {
    const { workspaceCreateFile } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    await rows[0].trigger("click"); // select + expand src
    await new Promise((resolve) => setTimeout(resolve, 10));

    const buttons = wrapper.findAll(".explorer-actions button");
    expect(buttons.length).toBe(3);
    expect(buttons[0].attributes("aria-label")).toBe("新建文件");

    await buttons[0].trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    const input = wrapper.find("[data-testid=name-input]");
    expect(input.exists()).toBe(true);

    await input.setValue("made.ts");
    await input.trigger("keydown.enter");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(workspaceCreateFile).toHaveBeenCalledWith("/ws", "src", "made.ts");
    expect(wrapper.find("[data-testid=name-input]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("toolbar buttons stay disabled without a workspace", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    // Fresh runtime store: workspace defaults to "" (no workspace chosen).
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const buttons = wrapper.findAll(".explorer-actions button");
    expect(buttons.length).toBe(3);
    for (const b of buttons) {
      expect(b.attributes("disabled")).toBeDefined();
    }
    wrapper.unmount();
  });
});

/** Stage 11 (11c): target-aware context menus (03 §3). */
describe("WorkspaceExplorer context menus (11c)", () => {
  function stubViewport() {
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  }

  async function openRowMenu(wrapper: ReturnType<typeof mount>, rowIndex: number) {
    stubViewport();
    const rows = wrapper.findAll("[role=treeitem]");
    await rows[rowIndex].trigger("contextmenu", { clientX: 300, clientY: 300 });
    return wrapper.find("[role=menu]");
  }

  it("blank-area right-click opens the root menu; paste is disabled with a reason", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    stubViewport();
    await wrapper.find(".explorer-body").trigger("contextmenu", { clientX: 300, clientY: 300 });
    const menu = wrapper.find("[role=menu]");
    expect(menu.exists()).toBe(true);
    const ids = menu.findAll("button").map((b) => b.attributes("data-action"));
    expect(ids).toEqual(["new-file", "new-folder", "paste", "refresh"]);
    const paste = menu.find('[data-action="paste"]');
    expect(paste.attributes("disabled")).toBeDefined();
    expect(paste.attributes("title")).toBe("没有可粘贴的文件");
    wrapper.unmount();
  });

  it("dir row menu shows dir-target actions", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const menu = await openRowMenu(wrapper, 0); // src
    const ids = menu.findAll("button").map((b) => b.attributes("data-action"));
    expect(ids).toEqual([
      "toggle",
      "reveal",
      "new-file",
      "new-folder",
      "paste",
      "copy-entry",
      "rename",
      "refresh",
    ]);
    wrapper.unmount();
  });

  it("file row menu shows file-target actions", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const menu = await openRowMenu(wrapper, 1); // a.md
    const ids = menu.findAll("button").map((b) => b.attributes("data-action"));
    expect(ids).toEqual(["open", "reveal", "copy-entry", "copy-path", "rename"]);
    wrapper.unmount();
  });

  it("copy-file fills the in-app clipboard and never writes the system clipboard", async () => {
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const menu = await openRowMenu(wrapper, 1);
    await menu.find('[data-action="copy-entry"]').trigger("click");
    const explorer = useWorkspaceExplorerStore();
    expect(explorer.clipboard).toMatchObject({
      workspace: "/ws",
      sourceRelativePath: "a.md",
      kind: "file",
    });
    expect(writeText).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("copy-path still writes the system text clipboard", async () => {
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const menu = await openRowMenu(wrapper, 1);
    await menu.find('[data-action="copy-path"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(writeText).toHaveBeenCalledWith("/ws/a.md");
    wrapper.unmount();
  });

  it("paste copies the clipboard entry into the target dir and reports success", async () => {
    const { workspaceCopyEntry } = await import("../../../lib/ipc");
    await setup();
    const explorer = useWorkspaceExplorerStore();
    explorer.setClipboardEntry("a.md", "file");
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const menu = await openRowMenu(wrapper, 0); // src dir target
    await menu.find('[data-action="paste"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(workspaceCopyEntry).toHaveBeenCalledWith("/ws", "a.md", "src");
    const status = wrapper.find(".explorer-status");
    expect(status.exists()).toBe(true);
    expect(status.text()).toContain("已粘贴");
    wrapper.unmount();
  });
});

/** Stage 11 (11c): inline create/rename name input (D11-06). */
describe("WorkspaceExplorer inline naming (11c)", () => {
  function stubViewport() {
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  }

  async function startRename(wrapper: ReturnType<typeof mount>) {
    stubViewport();
    const rows = wrapper.findAll("[role=treeitem]");
    await rows[1].trigger("contextmenu", { clientX: 300, clientY: 300 }); // a.md
    await wrapper.find('[data-action="rename"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    return wrapper.find("[data-testid=name-input]");
  }

  it("rename commits via workspaceRename and closes the input", async () => {
    const { workspaceRename } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const input = await startRename(wrapper);
    expect((input.element as HTMLInputElement).value).toBe("a.md");
    await input.setValue("b.md");
    await input.trigger("keydown.enter");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(workspaceRename).toHaveBeenCalledWith("/ws", "a.md", "b.md");
    expect(wrapper.find("[data-testid=name-input]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("Enter inside the rename input does not leak to the tree (open)", async () => {
    // 手测回归 1: renaming a focused row and pressing Enter ALSO bubbled to
    // the tree handler, which opened the OLD path and errored. The input now
    // stops propagation and the tree handler ignores input-originated keys.
    const { workspaceOpen, workspaceRename } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    await rows[1].trigger("focus"); // roving focus on the row being renamed
    stubViewport();
    await rows[1].trigger("contextmenu", { clientX: 300, clientY: 300 }); // a.md
    await wrapper.find('[data-action="rename"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    const input = wrapper.find("[data-testid=name-input]");
    await input.setValue("b.md");
    await input.trigger("keydown.enter");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(workspaceRename).toHaveBeenCalledWith("/ws", "a.md", "b.md");
    expect(workspaceOpen).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("rename conflict keeps the input open with the stable error", async () => {
    const { workspaceRename } = await import("../../../lib/ipc");
    vi.mocked(workspaceRename).mockRejectedValueOnce({
      code: "WB_ERR_WORKSPACE_CONFLICT",
      message: "target exists",
    });
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    let input = await startRename(wrapper);
    await input.setValue("b.md");
    await input.trigger("keydown.enter");
    await new Promise((resolve) => setTimeout(resolve, 10));
    // Input survives with the localized conflict message next to it.
    input = wrapper.find("[data-testid=name-input]");
    expect(input.exists()).toBe(true);
    const error = wrapper.find(".name-error");
    expect(error.exists()).toBe(true);
    expect(error.text()).toBe("同名文件已存在，未覆盖");
    wrapper.unmount();
  });

  it("Escape cancels the rename and restores the plain row", async () => {
    const { workspaceRename } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const input = await startRename(wrapper);
    await input.trigger("keydown.esc");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(wrapper.find("[data-testid=name-input]").exists()).toBe(false);
    expect(workspaceRename).not.toHaveBeenCalled();
    // The row still shows the original name.
    const rows = wrapper.findAll("[role=treeitem]");
    expect(rows[1].text()).toContain("a.md");
    wrapper.unmount();
  });

  it("create input rejects invalid names instantly without calling IPC", async () => {
    const { workspaceCreateFile } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    stubViewport();
    await wrapper.find(".explorer-body").trigger("contextmenu", { clientX: 300, clientY: 300 });
    await wrapper.find('[data-action="new-file"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    const input = wrapper.find("[data-testid=name-input]");
    expect(input.exists()).toBe(true);

    await input.setValue("a/b");
    await input.trigger("keydown.enter");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(wrapper.find(".name-error").text()).toBe("名称不能包含 / 或 \\");
    expect(workspaceCreateFile).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("blur commits a valid create name", async () => {
    const { workspaceCreateFile } = await import("../../../lib/ipc");
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const buttons = wrapper.findAll(".explorer-actions button");
    await buttons[0].trigger("click"); // new file at root (no selection)
    await new Promise((resolve) => setTimeout(resolve, 10));
    const input = wrapper.find("[data-testid=name-input]");
    await input.setValue("blurred.md");
    await input.trigger("blur");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(workspaceCreateFile).toHaveBeenCalledWith("/ws", "", "blurred.md");
    wrapper.unmount();
  });
});

/** Stage 11 (11d): drag payload + type icons (D11-09/10). */
describe("WorkspaceExplorer drag & icons (11d)", () => {
  it("file dragstart sets ONLY the controlled relative-path MIME", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    const dt = { setData: vi.fn(), effectAllowed: "", types: [] as string[] };
    await rows[1].trigger("dragstart", { dataTransfer: dt }); // a.md
    expect(dt.setData).toHaveBeenCalledTimes(1);
    expect(dt.setData).toHaveBeenCalledWith("application/x-aisc-workspace-path", "a.md");
    expect(dt.effectAllowed).toBe("copy");
    wrapper.unmount();
  });

  it("dir rows never drag into the terminal", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const rows = wrapper.findAll("[role=treeitem]");
    expect(rows[0].attributes("draggable")).toBe("false"); // src (dir)
    expect(rows[1].attributes("draggable")).toBe("true"); // a.md (file)
    const dt = { setData: vi.fn(), effectAllowed: "", types: [] as string[] };
    await rows[0].trigger("dragstart", { dataTransfer: dt });
    expect(dt.setData).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("every row renders a fixed-size type icon (dirs show open/closed state)", async () => {
    await setup();
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    const icons = wrapper.findAll(".explorer-typeicon");
    expect(icons.length).toBe(2); // one per row, dirs included
    // The twisty column stays dir-only (files render an empty slot).
    const twisties = wrapper.findAll(".explorer-twisty");
    expect(twisties[0].text()).toBe("▸"); // collapsed dir
    expect(twisties[1].text()).toBe("");
    wrapper.unmount();
  });
});
