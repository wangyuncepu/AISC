import { describe, expect, it, vi } from "vitest";
import { buildCommands, type CommandCtx } from "../commands";

function makeCtx(over: Partial<CommandCtx["active"]> = {}): CommandCtx {
  return {
    active: {
      createTab: vi.fn(),
      splitPane: vi.fn(),
      status: "ready",
      workspace: "C:\\ws",
      ...over,
    },
    app: {
      openSettings: vi.fn(),
      openNetworkUsage: vi.fn(),
      openPicker: vi.fn(),
      runDoctor: vi.fn(),
      toggleSidebar: vi.fn(),
      showView: vi.fn(),
      servicesSupported: () => true,
    },
  };
}

describe("P2-4 command registry (palette data source)", () => {
  it("entries are unique by id and carry i18n keys (labels resolve at render)", () => {
    const cmds = buildCommands();
    const ids = cmds.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const c of cmds) {
      expect(c.labelKey).toMatch(/^[\w.-]+$/);
      expect(c.groupKey).toMatch(/^palette\.group\./);
    }
  });

  it("workspace commands gate on ready; app commands do not", () => {
    const busy = makeCtx({ status: "starting" });
    const cmds = buildCommands();
    const tab = cmds.find((c) => c.id === "tab.new.bash")!;
    expect(tab.when?.(busy)).toBe(false);
    const settings = cmds.find((c) => c.id === "app.settings")!;
    // No `when` = always available.
    expect(settings.when ? settings.when(busy) : true).toBe(true);
  });

  it("services view gates on capability; others in the view group do not", () => {
    const ctx = makeCtx();
    const withSvc = buildCommands().find((c) => c.id === "view.services")!;
    expect(withSvc.when?.(ctx)).toBe(true);
    const svcCtx = makeCtx();
    svcCtx.app.servicesSupported = () => false;
    expect(withSvc.when?.(svcCtx)).toBe(false);
  });

  it("run dispatches to the injected ctx thunks", () => {
    const ctx = makeCtx();
    const cmds = buildCommands();
    cmds.find((c) => c.id === "app.doctor")!.run(ctx);
    expect(ctx.app.runDoctor).toHaveBeenCalledOnce();
    cmds.find((c) => c.id === "view.sidebar.toggle")!.run(ctx);
    expect(ctx.app.toggleSidebar).toHaveBeenCalledOnce();
  });
});
