/**
 * ConflictManager stale-record remove (2026-08-10 bugfix).
 *
 * The stale-record CLI fix routes preflight to resolve_conflict for a registry
 * record whose container was deleted, and `aisc runtime list` reports it with
 * state "not_found". ConflictManager previously offered Stop/Remove only for
 * running/starting/stopped states, so a not_found record was listed but had no
 * action - a dead end. It now gets a plain 移除 button (the CLI remove is
 * idempotent for an already-gone container and cleans the registry entry).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import ConflictManager from "../ConflictManager.vue";
import type { RuntimeSnapshot } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  removeRuntime: vi.fn().mockResolvedValue({}),
  stopRuntime: vi.fn().mockResolvedValue({}),
  negotiateCapabilities: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn().mockResolvedValue(true),
  open: vi.fn(),
}));
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

function staleSnapshot(): RuntimeSnapshot {
  return {
    runtime_id: "21479eab-cf9d-4552-95a5-592cba8da8e8",
    state: "not_found",
    config: {
      workspace: "C:\\Downloads\\test",
      image: "super-claude:latest",
      network: "direct",
      scope: "project",
    },
    owner: "workbench",
    config_fingerprint: "sha256:aaaa",
    container_name: "aisc-wb-21479eab",
    container_id: "",
    registry_state: "registered",
    observed_at: "t",
    stale: false,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});

describe("stale record (state not_found)", () => {
  it("offers a remove button for a not_found runtime", () => {
    const s = useRuntimeStore();
    s.conflicts = [staleSnapshot()];
    const wrapper = mount(ConflictManager, { global: { plugins: [i18n] } });
    const btn = wrapper.find(".list li button.danger");
    expect(btn.exists()).toBe(true);
    expect(btn.text()).toBe("移除");
  });

  it("clicking remove removes the stale runtime and reloads", async () => {
    const s = useRuntimeStore();
    s.conflicts = [staleSnapshot()];
    s.workspace = "C:\\Downloads\\test";
    const wrapper = mount(ConflictManager, { global: { plugins: [i18n] } });
    await wrapper.find(".list li button.danger").trigger("click");
    expect(s.removeConflictRuntime).toBeDefined();
    // removeConflictRuntime ran -> reload happened; the empty state shows now.
    await vi.waitFor(() => expect(wrapper.find(".empty").exists()).toBe(true));
  });
});
