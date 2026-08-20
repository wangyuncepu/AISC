/**
 * Stage 3 (3c, WX-01): lazy tree + artifact store behavior.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkspaceExplorerStore } from "../workspaceExplorer";
import { useSettingsStore } from "../settings";
import { artifactRefresh, workspaceList } from "../../lib/ipc";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));
vi.mock("../../lib/ipc", () => ({
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
  loadSettings: vi.fn().mockResolvedValue({
    schemaVersion: 1,
    revision: 0,
    aiscCliPath: null,
    ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: [], default_tab_agent: "bash" },
    terminal: { font_family: "", font_size: 14, line_height: 1.2, letter_spacing: 0, scrollback: 5000, renderer: "auto", smooth_scroll_duration: 100 },
    window: { remember_geometry: true, close_behavior: "quit", geometry: null },
    issues: [],
    corrupted: false,
    readOnly: false,
  }),
  saveSettings: vi.fn(),
  resetGuiSettings: vi.fn(),
  resolveLocale: vi.fn().mockResolvedValue("en-US"),
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

describe("workspaceExplorer refresh", () => {
  it("refreshRoot refreshes the artifact index before loading artifacts", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.refreshRoot();
    expect(artifactRefresh).toHaveBeenCalledWith("/ws");
  });

  it("root-level watcher changes never delete the loaded root tree", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    expect(s.rootNodes.length).toBeGreaterThan(0);

    s.handleWorkspaceChanges([
      { relative_path: "new.md", change_type: "created", kind: "file", revision: 1 },
    ]);

    expect(s.rootNodes.length).toBeGreaterThan(0);
    expect(s.unattributed["new.md"]).toBe("created");
  });

  it("directories (incl. empty folders) never surface as unattributed", async () => {
    // Root listing includes the new empty folder so the tree knows it is a dir.
    vi.mocked(workspaceList).mockImplementation(async (_ws: string, dir: string) => {
      if (dir === "") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "newdir", name: "newdir", kind: "dir", expandable: true, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      return { schema_version: 1, nodes: [], next_cursor: null, truncated: false };
    });

    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");

    // The watcher reports the new folder itself; with no children it is an
    // empty folder and must NOT appear in the Artifacts panel.
    s.handleWorkspaceChanges([
      { relative_path: "newdir", change_type: "created", kind: "dir", revision: 1 },
    ]);
    await new Promise((resolve) => setTimeout(resolve, 10)); // root reload
    await s.loadNewCreatedDirs(); // list its children (none)

    // Still tracked for recursion, but hidden from the display projection.
    expect(s.unattributed["newdir"]).toBe("created");
    expect(s.unattributedEntries.map((e) => e.relative_path)).toEqual([]);
  });
});

describe("workspaceExplorer user ignore (ui.explorer_ignore)", () => {
  it("drops ignored paths from the unattributed projection", async () => {
    const { loadSettings } = await import("../../lib/ipc");
    vi.mocked(loadSettings).mockResolvedValue({
      schemaVersion: 1,
      revision: 0,
      aiscCliPath: null,
      ui: { language: "auto", font_scale: 1.0, theme: "system", explorer_ignore: ["scratch", "logs"], default_tab_agent: "bash", default_new_page: "workspace" },
      terminal: { font_family: "", font_size: 14, line_height: 1.2, letter_spacing: 0, scrollback: 5000, renderer: "auto", smooth_scroll_duration: 100 },
      window: { remember_geometry: true, close_behavior: "quit", geometry: null },
      issues: [],
      corrupted: false,
      readOnly: false,
    });
    const settings = useSettingsStore();
    await settings.load();

    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    s.handleWorkspaceChanges([
      { relative_path: "keep.md", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "scratch/out.bin", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "src/logs/x.log", change_type: "created", kind: "file", revision: 1 },
    ]);

    // Ignored paths are never ingested into the unattributed map at all.
    expect(s.unattributed["keep.md"]).toBe("created");
    expect(s.unattributed["scratch/out.bin"]).toBeUndefined();
    expect(s.unattributed["src/logs/x.log"]).toBeUndefined();
    expect(s.unattributedEntries.map((e) => e.relative_path)).toEqual(["keep.md"]);
  });
});

describe("workspaceExplorer transient temp files", () => {
  it("drops atomic-write temp files from the unattributed projection", async () => {
    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    s.handleWorkspaceChanges([
      { relative_path: "reports/result.md", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "reports/result.md.tmp.1234", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "reports/result.md.tmp", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "src/notes.md~", change_type: "created", kind: "file", revision: 1 },
      { relative_path: "src/.#main.ts", change_type: "created", kind: "file", revision: 1 },
    ]);

    expect(s.unattributed["reports/result.md"]).toBe("created");
    expect(s.unattributed["reports/result.md.tmp.1234"]).toBeUndefined();
    expect(s.unattributed["reports/result.md.tmp"]).toBeUndefined();
    expect(s.unattributed["src/notes.md~"]).toBeUndefined();
    expect(s.unattributed["src/.#main.ts"]).toBeUndefined();
    expect(s.unattributedEntries.map((e) => e.relative_path)).toEqual(["reports/result.md"]);
  });
});

describe("workspaceExplorer new directory handling", () => {
  it("lists children of a newly-created directory and marks them unattributed", async () => {
    vi.mocked(workspaceList).mockImplementation(async (_ws: string, dir: string) => {
      if (dir === "") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "newdir", name: "newdir", kind: "dir", expandable: true, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      if (dir === "newdir") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "newdir/file.txt", name: "file.txt", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      return { schema_version: 1, nodes: [], next_cursor: null, truncated: false };
    });

    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");

    s.handleWorkspaceChanges([
      { relative_path: "newdir", change_type: "created", kind: "dir", revision: 1 },
    ]);

    // handleWorkspaceChanges schedules root reload -> new-dir listing.
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(s.tree["newdir"]?.map((n) => n.relative_path)).toEqual(["newdir/file.txt"]);
    expect(s.unattributed["newdir/file.txt"]).toBe("created");
  });
});

describe("workspaceExplorer nested tree + pagination", () => {
  it("visibleNodes recursively flattens expanded directories", async () => {
    vi.mocked(workspaceList).mockImplementation(async (_ws: string, dir: string) => {
      if (dir === "") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "src", name: "src", kind: "dir", expandable: true, artifact_badges: [], change_state: "unknown" },
            { relative_path: "a.md", name: "a.md", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      if (dir === "src") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "src/main.ts", name: "main.ts", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
            { relative_path: "src/lib", name: "lib", kind: "dir", expandable: true, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      if (dir === "src/lib") {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "src/lib/file.ts", name: "file.ts", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: null,
          truncated: false,
        };
      }
      return { schema_version: 1, nodes: [], next_cursor: null, truncated: false };
    });

    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    await s.toggleDir("src");
    await s.loadDir("src");
    await s.toggleDir("src/lib");
    await s.loadDir("src/lib");

    // Depth-first preorder matches the rendered tree: an expanded dir's
    // children appear immediately below it (APG tree keyboard order).
    expect(s.visibleNodes.map((n) => n.relative_path)).toEqual([
      "src",
      "src/main.ts",
      "src/lib",
      "src/lib/file.ts",
      "a.md",
    ]);
  });

  it("loadDir keeps pagination cursor and loadMore appends the next page", async () => {
    let calls = 0;
    vi.mocked(workspaceList).mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          schema_version: 1,
          nodes: [
            { relative_path: "a.md", name: "a.md", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
          ],
          next_cursor: "1",
          truncated: true,
        };
      }
      return {
        schema_version: 1,
        nodes: [
          { relative_path: "b.md", name: "b.md", kind: "file", expandable: false, artifact_badges: [], change_state: "unknown" },
        ],
        next_cursor: null,
        truncated: false,
      };
    });

    const s = useWorkspaceExplorerStore();
    s.setWorkspace("/ws");
    await s.loadDir("");
    expect(s.tree[""]).toHaveLength(1);
    expect(s.nextCursors[""]).toBe("1");
    expect(s.truncatedDirs[""]).toBe(true);

    await s.loadMore("");
    expect(s.tree[""]).toHaveLength(2);
    expect(s.nextCursors[""]).toBeNull();
    expect(s.truncatedDirs[""]).toBe(false);
  });
});
