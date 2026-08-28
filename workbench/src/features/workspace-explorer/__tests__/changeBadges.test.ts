/**
 * v2.1.7 S7 (④/Gate-S7): the change badge system — 变更类型 × 来源.
 *
 * Facts-only rendering: attributed rows show agent + action (+ previous
 * path for renames); unattributed rows show the watcher-derived type with
 * the honest "original unknown" note; a collapsible legend explains the
 * system; icons+text+tooltip so color is never the only signal (A-21774).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useWorkspaceExplorerStore } from "../../../stores/workspaceExplorer";
import { useRuntimeStore } from "../../../stores/runtime";
import WorkspaceExplorer from "../WorkspaceExplorer.vue";
import type { ArtifactRecord } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  workspaceList: vi.fn(async () => ({
    schema_version: 1, nodes: [], next_cursor: null, truncated: false,
  })),
  workspaceOpen: vi.fn().mockResolvedValue(undefined),
  artifactList: vi.fn(async () => ({
    schema_version: 1, artifacts: [], next_cursor: null,
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

function art(over: Partial<ArtifactRecord>): ArtifactRecord {
  return {
    schema_version: 1,
    artifact_id: "id-" + Math.random().toString(36).slice(2, 8),
    workspace_relative_path: "x.md",
    action: "created",
    kind: "deliverable",
    media_type: null,
    label: "",
    open_with: "preview",
    producer: { agent: "claude", session_id: "s", runtime_id: "r" },
    state: "present",
    provenance: "manifest",
    recorded_at: "2026-08-28T00:00:00Z",
    previous_path: null,
    extra: {},
    ...over,
  } as ArtifactRecord;
}

async function mountWithArtifacts(records: ArtifactRecord[]) {
  const w = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
  await flushPromises();
  const explorer = useWorkspaceExplorerStore();
  explorer.artifacts = records;
  explorer.unattributed = {};
  explorer.activeKind = "artifacts";
  await flushPromises();
  return w;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
  useRuntimeStore().workspace = "C:\\ws";
});
afterEach(() => vi.clearAllMocks());

describe("change badges (S7)", () => {
  it("attributed rows carry an agent badge with the recorded action", async () => {
    const w = await mountWithArtifacts([
      art({ workspace_relative_path: "docs/report.md", action: "created" }),
    ]);
    const badge = w.find(".artifact-row .change-badge, .unattributed .change-badge");
    expect(badge.exists()).toBe(true);
    expect(badge.attributes("data-type")).toBe("created");
    expect(badge.attributes("data-source")).toBe("agent");
    expect(badge.text()).toContain("claude"); // agent name visible
    expect(badge.attributes("aria-label")).toContain("claude 登记");
  });

  it("an attributed rename shows 已移动 with the recorded previous path", async () => {
    const w = await mountWithArtifacts([
      art({
        workspace_relative_path: "docs/new.md",
        action: "renamed",
        previous_path: "docs/old.md",
      }),
    ]);
    const badge = w.find(".artifact-row .change-badge, .unattributed .change-badge");
    expect(badge.attributes("data-type")).toBe("renamed");
    expect(badge.text()).toContain("移动");
    // The tooltip carries the REAL recorded old path (A-21773: fact, not guess).
    expect(badge.attributes("title")).toContain("docs/old.md");
  });

  it("unattributed rows show the dashed watcher-type badge", async () => {
    const w = await mountWithArtifacts([]);
    const explorer = useWorkspaceExplorerStore();
    explorer.unattributed = { "notes/x.md": "modified" };
    await flushPromises();

    const badge = w.find(".artifact-row .change-badge, .unattributed .change-badge");
    expect(badge.exists()).toBe(true);
    expect(badge.attributes("data-source")).toBe("unattributed");
    expect(badge.attributes("data-type")).toBe("modified");
    expect(badge.text()).toContain("修改");
    // The unknown-rename note must NOT appear for a modified fact.
    expect(badge.attributes("title")).not.toContain("原路径未知");
  });

  it("no legend row — badges self-describe via tooltip (2026-08-28 manual test)", async () => {
    const w = await mountWithArtifacts([
      art({ workspace_relative_path: "x.md", action: "created" }),
    ]);
    expect(w.find(".badge-legend").exists()).toBe(false);
    expect(w.find(".legend-chip").exists()).toBe(false);
    // The badge's own tooltip still teaches the source semantics.
    const badge = w.find(".artifact-row .change-badge, .unattributed .change-badge");
    expect(badge.attributes("title")).toContain("登记");
  });
});
