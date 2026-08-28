/**
 * svc-4+ (web services): the Services tab inside the Workspace Explorer —
 * parallel to 文件/变更, same cross-fade. Covers the capability gate, row
 * rendering (label fallback, gateway port), copy (clipboard) and the
 * ids-only open path through the runtime store.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import { useWorkspaceExplorerStore } from "../../../stores/workspaceExplorer";
import WorkspaceExplorer from "../WorkspaceExplorer.vue";
import type { RuntimeServicesResult } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  workspaceList: vi.fn(async () => ({
    schema_version: 1, nodes: [], next_cursor: null, truncated: false,
  })),
  workspaceOpen: vi.fn().mockResolvedValue(undefined),
  runtimeServices: vi.fn(),
  openRuntimeServiceUrl: vi.fn().mockResolvedValue("http://p3000.localhost:47831/"),
}));
vi.mock("@tauri-apps/plugin-clipboard-manager", () => ({
  writeText: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({}) }));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));

const RID = "11111111-1111-4111-8111-111111111111";

const PAYLOAD: RuntimeServicesResult = {
  schema_version: "aisc.runtime-services/v1",
  runtime_id: RID,
  gateway: { state: "ready", container_port: 45871, host_port: 47831, host: "127.0.0.1" },
  services: [
    { port: 3000, protocol: "http", name: "docs preview", state: "registered", url: "http://p3000.localhost:47831/" },
    { port: 5173, protocol: "http", name: "", state: "registered", url: "http://p5173.localhost:47831/" },
  ],
  observed_at: "2026-08-25T00:00:00Z",
};

function setup(capability: boolean) {
  const runtime = useRuntimeStore();
  runtime.workspace = "C:\\ws";
  runtime.runtimeId = RID;
  runtime.runtimeState = "running";
  runtime.capability = { runtime_services: capability } as never;
  runtime.webServices = PAYLOAD;
  const explorer = useWorkspaceExplorerStore();
  explorer.activeKind = "services";
  return { runtime, explorer };
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("svc-4+ explorer services tab", () => {
  it("renders rows with label fallback and gateway port", () => {
    setup(true);
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    try {
      const tab = wrapper.find('[role="tab"][aria-selected="true"]');
      expect(tab.text()).toBe("服务");
      expect(wrapper.find(".services-gateway").text()).toContain("47831");
      const rows = wrapper.findAll(".service-row");
      expect(rows).toHaveLength(2);
      expect(rows[0].text()).toContain("docs preview");
      expect(rows[0].text()).toContain("3000");
      expect(rows[1].text()).toContain("端口 5173");
    } finally {
      wrapper.unmount();
    }
  });

  it("open routes through the store with ids only", async () => {
    const { runtime } = setup(true);
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    try {
      const open = vi.spyOn(runtime, "openWebService");
      await wrapper.findAll(".service-row")[0].findAll("button")[1].trigger("click");
      expect(open).toHaveBeenCalledWith(3000);
      open.mockRestore();
    } finally {
      wrapper.unmount();
    }
  });

  it("copy puts the canonical URL on the clipboard", async () => {
    setup(true);
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    try {
      await wrapper.findAll(".service-row")[1].findAll("button")[0].trigger("click");
      expect(writeText).toHaveBeenCalledWith("http://p5173.localhost:47831/");
    } finally {
      wrapper.unmount();
    }
  });

  it("hides the tab without the runtimeServices capability", () => {
    setup(false);
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    try {
      const tabs = wrapper.findAll('[role="tab"]').map((b) => b.text());
      expect(tabs).not.toContain("服务");
      expect(tabs).toContain("文件");
      expect(tabs).toContain("变更");
    } finally {
      wrapper.unmount();
    }
  });

  it("shows the unavailable reason instead of dead links", () => {
    const { runtime } = setup(true);
    runtime.webServices = {
      ...PAYLOAD,
      gateway: { state: "unavailable", container_port: 45871, host_port: 0, host: "127.0.0.1", reason: "legacy_runtime" },
      services: [],
    };
    const wrapper = mount(WorkspaceExplorer, { global: { plugins: [i18n] } });
    try {
      expect(wrapper.text()).toContain("该运行时创建于服务访问功能之前");
      expect(wrapper.findAll(".service-row")).toHaveLength(0);
    } finally {
      wrapper.unmount();
    }
  });
});
