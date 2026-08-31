/**
 * v2.1.9 T6: the change badge reduced to its TYPE fact — the Changes panel
 * is a flat list (no kind sections/chips/attribution per user ruling
 * 2026-08-31: agent self-registration proved unreliable). Icon + hue +
 * text so color is never the only signal (A-21774); tooltip carries the
 * type text.
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
  conversationList: vi.fn(async () => ({ schema_version: 1, conversations: [] })),
  conversationPreflight: vi.fn(async () => ({ conversation_id: "", agent: "" })),
  conversationDelete: vi.fn(async () => ({ deleted: true, conversation_id: "", agent: "" })),
  conversationRename: vi.fn(async () => ({ renamed: true, conversation_id: "", agent: "", title: "" })),
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

async function mountFlat() {
  const w = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
  await flushPromises();
  const explorer = useWorkspaceExplorerStore();
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

describe("change badges (T6 flat panel)", () => {
  it("every change row carries a TYPE-only badge — icon + text, no agent/source labels", async () => {
    const w = await mountFlat();
    const explorer = useWorkspaceExplorerStore();
    explorer.unattributed = { "notes/x.md": "modified" };
    await flushPromises();

    const badge = w.find(".artifact-row .change-badge");
    expect(badge.exists()).toBe(true);
    expect(badge.attributes("data-type")).toBe("modified");
    expect(badge.text()).toContain("修改");
    // No source/agent layer anywhere on the badge (cut taxonomy).
    expect(badge.attributes("data-source")).toBeUndefined();
    expect(badge.text()).not.toContain("claude");
    expect(badge.text()).not.toContain("codex");
    expect(badge.text()).not.toContain("未归因");
  });

  it("the four types render distinct icons+hues (color never the only signal)", async () => {
    const w = await mountFlat();
    const explorer = useWorkspaceExplorerStore();
    explorer.unattributed = {
      "a.txt": "created",
      "b.txt": "modified",
      "c.txt": "deleted",
      "d.txt": "renamed",
    };
    await flushPromises();
    const badges = w.findAll(".artifact-row .change-badge");
    expect(badges).toHaveLength(4);
    const byType = new Map(badges.map((b) => [b.attributes("data-type"), b]));
    expect(["created", "modified", "deleted", "renamed"].every((t) => byType.has(t))).toBe(true);
    expect(byType.get("created")!.text()).toContain("新增");
    expect(byType.get("deleted")!.text()).toContain("删除");
    expect(byType.get("renamed")!.text()).toContain("移动");
  });

  it("no classification chrome: no chips, no group headers, no legend", async () => {
    const w = await mountFlat();
    const explorer = useWorkspaceExplorerStore();
    explorer.unattributed = { "x.md": "created" };
    await flushPromises();
    expect(w.find(".artifact-chips").exists()).toBe(false);
    expect(w.find(".artifact-chip").exists()).toBe(false);
    expect(w.findAll(".artifacts-group-head").length).toBe(0);
    expect(w.find(".badge-legend").exists()).toBe(false);
  });
});
