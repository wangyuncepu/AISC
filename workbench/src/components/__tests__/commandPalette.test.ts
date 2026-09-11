import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createI18n } from "vue-i18n";
import { zhCN } from "../../i18n/zh-CN";
import CommandPalette from "../CommandPalette.vue";
import type { CommandCtx } from "../../lib/commands";

const i18n = createI18n({ legacy: false, locale: "zh-CN", messages: { "zh-CN": zhCN } });

function makeCtx(): CommandCtx {
  return {
    active: {
      createTab: vi.fn(),
      openCcSwitch: vi.fn(),
      splitPane: vi.fn(),
      status: "ready",
      workspace: "C:\\ws",
    },
    app: {
      openSettings: vi.fn(),
      openNetworkUsage: vi.fn(),
      openPicker: vi.fn(),
      runDoctor: vi.fn(),
      toggleSidebar: vi.fn(),
      showView: vi.fn(),
      servicesSupported: () => false,
    },
  };
}

describe("P2-4 command palette", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    i18n.global.locale.value = "zh-CN";
  });

  it("renders grouped commands and filters by query", async () => {
    const ctx = makeCtx();
    const w = mount(CommandPalette, {
      props: { makeCtx: () => ctx },
      // Teleport stub: assert against the wrapper (the palette ships to body).
      global: { plugins: [i18n], stubs: { teleport: true } },
    });
    // All app+tab groups render (services hidden — capability off).
    expect(w.text()).toContain("标签页与会话");
    expect(w.text()).toContain("视图");
    expect(w.text()).toContain("应用");
    expect(w.text()).not.toContain("服务");
    await w.find("input").setValue("诊断");
    expect(w.findAll(".palette-item").length).toBe(1);
    expect(w.text()).toContain("运行诊断");
    w.unmount();
  });

  it("Enter runs the cursor command and closes; Esc closes without running", async () => {
    const ctx = makeCtx();
    const w = mount(CommandPalette, {
      props: { makeCtx: () => ctx, onClose: () => {} },
      global: { plugins: [i18n], stubs: { teleport: true } },
    });
    await w.find("input").setValue("诊断");
    await w.find("input").trigger("keydown", { key: "Enter" });
    expect(ctx.app.runDoctor).toHaveBeenCalledOnce();
    expect(w.emitted("close")).toHaveLength(1);
    w.unmount();
  });

  it("arrow keys move the cursor (wrap-around), mouse hover sets it", async () => {
    const ctx = makeCtx();
    const w = mount(CommandPalette, {
      props: { makeCtx: () => ctx },
      // Teleport stub: assert against the wrapper (the palette ships to body).
      global: { plugins: [i18n], stubs: { teleport: true } },
    });
    const items = () => w.findAll(".palette-item");
    expect(items()[0]!.classes()).toContain("cursor");
    await w.find("input").trigger("keydown", { key: "ArrowUp" });
    expect(items()[items().length - 1]!.classes()).toContain("cursor");
    await w.find("input").trigger("keydown", { key: "ArrowDown" });
    expect(items()[0]!.classes()).toContain("cursor");
    await items()[2]!.trigger("mousemove");
    expect(items()[2]!.classes()).toContain("cursor");
    w.unmount();
  });

  it("no match renders the empty state", async () => {
    const w = mount(CommandPalette, {
      props: { makeCtx: () => makeCtx() },
      global: { plugins: [i18n], stubs: { teleport: true } },
    });
    await w.find("input").setValue("zzz-no-such-command");
    expect(w.find(".palette-empty").text()).toContain("没有匹配");
    w.unmount();
  });
});
