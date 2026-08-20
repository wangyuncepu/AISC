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
    const explorer = useWorkspaceExplorerStore();
    expect(explorer.preview?.text).toBe("hi");
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
    // Clamped into the viewport (drawer sits at the right edge).
    expect(menu.attributes("style")).toContain("left: 1040px");
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
