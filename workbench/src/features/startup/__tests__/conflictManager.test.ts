/**
 * runtime-lifecycle-ux Stage 4: the minimal BLOCK page.
 *
 * Stale runtimes never land here (reconcile auto-recycled them pre-preflight)
 * — only active_other_instance / unknown_owner / a generic blocked fallback.
 * Exactly three actions (re-check / back / diagnostics); the destructive
 * stop/remove/force-remove list is GONE (advanced cleanup lives in the
 * Runtime sidebar / Doctor).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import { useDoctorStore } from "../../../stores/doctor";
import ConflictManager from "../ConflictManager.vue";
import type { ReconcilePayload, RuntimeSnapshot } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  logUiEvent: vi.fn().mockResolvedValue(undefined),
  listRuntimes: vi.fn().mockResolvedValue({ runtimes: [] }),
  negotiateCapabilities: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
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

function payload(classification: ReconcilePayload["classification"]): ReconcilePayload {
  return {
    schema_version: "aisc.runtime-reconcile/v1",
    workspace_key: "k",
    classification,
    runtime_id: null,
    can_proceed: false,
    cleanup: { attempted: false, stopped: false, removed: false, registry_pruned: false },
    observed_at: "",
    error_code: null,
    technical_detail: null,
  };
}

function unverifiedSnapshot(): RuntimeSnapshot {
  return {
    runtime_id: "21479eab-cf9d-4552-95a5-592cba8da8e8",
    state: "not_found",
    config: { workspace: "C:\\test", image: "super-claude:latest", network: "direct", scope: "project" },
    owner: "",
    config_fingerprint: "",
    container_name: "aisc-wb-21479eab",
    container_id: "",
    registry_state: "registered",
    observed_at: "",
    stale: false,
  } as RuntimeSnapshot;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});
afterEach(() => vi.clearAllMocks());

describe("Stage 4 block page", () => {
  it("active_other_instance shows the other-instance block, never a runtime list", () => {
    const s = useRuntimeStore();
    s.status = "conflict";
    s.reconcile = payload("active_other_instance");
    const w = mount(ConflictManager, { global: { plugins: [i18n] } });
    try {
      expect(w.text()).toContain("另一个 Workbench 实例");
      // No destructive list/actions survive (01 §3.1).
      expect(w.text()).not.toContain("停止");
      expect(w.text()).not.toContain("强制移除");
      expect(w.findAll("li")).toHaveLength(0);
      const labels = w.findAll("button").map((b) => b.text());
      expect(labels).toEqual(["重新检测", "返回", "打开诊断"]);
    } finally {
      w.unmount();
    }
  });

  it("unknown_owner reports the unverifiable count without delete actions", () => {
    const s = useRuntimeStore();
    s.status = "conflict";
    s.reconcile = payload("unknown_owner");
    s.conflicts = [unverifiedSnapshot()];
    const w = mount(ConflictManager, { global: { plugins: [i18n] } });
    try {
      expect(w.text()).toContain("无法确认");
      expect(w.find('[data-testid="unverified-count"]').text()).toContain("1");
      expect(w.text()).not.toContain("移除");
    } finally {
      w.unmount();
    }
  });

  it("re-check / back / diagnostics are wired", async () => {
    const s = useRuntimeStore();
    s.status = "conflict";
    s.reconcile = payload("active_other_instance");
    const retry = vi.spyOn(s, "retryFromConflict");
    const back = vi.spyOn(s, "backToPicker");
    const doctor = useDoctorStore();
    const w = mount(ConflictManager, { global: { plugins: [i18n] } });
    try {
      await w.findAll("button")[0].trigger("click");
      await w.findAll("button")[1].trigger("click");
      await w.findAll("button")[2].trigger("click");
      expect(retry).toHaveBeenCalled();
      expect(back).toHaveBeenCalled();
      expect(doctor.open).toBe(true);
      retry.mockRestore();
      back.mockRestore();
    } finally {
      w.unmount();
    }
  });

  it("generic blocked fallback without a reconcile payload", () => {
    const s = useRuntimeStore();
    s.status = "conflict";
    const w = mount(ConflictManager, { global: { plugins: [i18n] } });
    try {
      expect(w.text()).toContain("启动已被阻断");
    } finally {
      w.unmount();
    }
  });
});
