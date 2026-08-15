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
});
