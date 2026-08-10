/**
 * LaunchSummary image-missing build button (G-14 bugfix, 2026-08-10).
 *
 * Root cause: the build button was gated on `imageMissing = image fail && action
 * !== reuse`, so a workspace with a matching existing runtime (recommended
 * action "reuse") hid the button while the gate still showed 镜像失败 - a dead
 * end. The button is now driven by `imageNotFound` = image check fail with
 * `AISC_ERR_IMAGE_NOT_FOUND` (genuinely missing tag), independent of action,
 * and the Docker-unreachable case (DOCKER_UNAVAILABLE) stays button-free.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { i18n } from "../../../i18n";
import { useRuntimeStore } from "../../../stores/runtime";
import LaunchSummary from "../LaunchSummary.vue";
import type { PreflightReport, RecommendedAction } from "../../../types";

vi.mock("../../../lib/ipc", () => ({
  buildImage: vi.fn(),
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

function preflight(action: RecommendedAction, imageError: string | null): PreflightReport {
  return {
    spec: {},
    checks: [
      { id: "docker", status: "pass", error_code: null, detail: null },
      { id: "workspace", status: "pass", error_code: null, detail: null },
      {
        id: "image",
        status: imageError ? "fail" : "pass",
        error_code: imageError,
        detail: imageError ? "Image not found" : null,
      },
      { id: "network", status: "pass", error_code: null, detail: null },
      { id: "runtime_conflict", status: "pass", error_code: null, detail: null },
    ],
    can_start: !imageError,
    recommended_action: action,
    matching_runtime_id: action === "reuse" || action === "restart" ? "rid" : null,
    conflicts: {},
    observed_at: "t",
  };
}

function setup(action: RecommendedAction, imageError: string | null) {
  const s = useRuntimeStore();
  s.preflight = preflight(action, imageError);
  s.launch.image = "super-claude:latest";
  return s;
}

function buildBtn(wrapper: ReturnType<typeof mount>): boolean {
  return wrapper.text().includes("构建镜像") || wrapper.text().includes("Build image");
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "zh-CN";
});

describe("build button visibility (G-14 bugfix)", () => {
  it("reuse action + missing image shows the build button and message", () => {
    const s = setup("reuse", "AISC_ERR_IMAGE_NOT_FOUND");
    const wrapper = mount(LaunchSummary, { global: { plugins: [i18n] } });
    expect(buildBtn(wrapper)).toBe(true);
    expect(wrapper.find(".gate-msg.config").exists()).toBe(true);
    void s;
  });

  it("start action + missing image shows the build button", () => {
    const s = setup("start", "AISC_ERR_IMAGE_NOT_FOUND");
    const wrapper = mount(LaunchSummary, { global: { plugins: [i18n] } });
    expect(buildBtn(wrapper)).toBe(true);
    void s;
  });

  it("reuse action + Docker-unreachable image check shows no build button", () => {
    const s = setup("reuse", "AISC_ERR_DOCKER_UNAVAILABLE");
    const wrapper = mount(LaunchSummary, { global: { plugins: [i18n] } });
    expect(buildBtn(wrapper)).toBe(false);
    void s;
  });

  it("image present shows no build button", () => {
    const s = setup("start", null);
    const wrapper = mount(LaunchSummary, { global: { plugins: [i18n] } });
    expect(buildBtn(wrapper)).toBe(false);
    void s;
  });
});
