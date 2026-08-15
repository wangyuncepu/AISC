/**
 * Stage 3 (3c, WX-01): lazy tree + artifact store behavior.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkspaceExplorerStore } from "../workspaceExplorer";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));
vi.mock("../../lib/ipc", () => ({
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
  workspacePreview: vi.fn().mockResolvedValue({
    relative_path: "a.md",
    media_type: "text/markdown",
    size: 3,
    text: "hi",
    base64: null,
    truncated: false,
  }),
  workspaceReveal: vi.fn().mockResolvedValue(undefined),
  workspaceCopyPath: vi.fn().mockResolvedValue({ relative_path: "a.md", absolute_path: "/ws/a.md" }),
  workspaceWatchStart: vi.fn().mockResolvedValue(undefined),
  workspaceWatchStop: vi.fn().mockResolvedValue(undefined),
  artifactList: vi.fn().mockResolvedValue({
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
  }),
  artifactInspect: vi.fn(),
  artifactRefresh: vi.fn(),
}));

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("workspaceExplorer store", () => {
  it("loads root lazily and expands a dir", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    expect(s.rootNodes.map((n) => n.name)).toEqual(["src", "a.md"]);

    await s.toggleDir("src");
    expect(s.isExpanded("src")).toBe(true);
    expect(s.nodeChildren("src")).toHaveLength(1);
    expect(s.nodeChildren("src")[0].name).toBe("main.ts");
  });

  it("toggle collapses an expanded dir", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    await s.toggleDir("src");
    await s.toggleDir("src");
    expect(s.isExpanded("src")).toBe(false);
  });

  it("loads artifacts and exposes filtered getters", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadArtifacts();
    expect(s.artifacts).toHaveLength(1);
    expect(s.artifactDeliverables).toHaveLength(1);
    expect(s.artifactSourceChanges).toHaveLength(0);
  });

  it("preview captures the preview result", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.previewFile("a.md");
    expect(s.preview?.text).toBe("hi");
    s.clearPreview();
    expect(s.preview).toBeNull();
  });

  it("switch workspace resets tree", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    expect(s.rootNodes.length).toBeGreaterThan(0);
    s.setWorkspace("/other");
    expect(s.rootNodes).toHaveLength(0);
  });
});
