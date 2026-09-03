/**
 * PP r8 (user request 2026-09-03): the WebView2 default context menu is
 * suppressed app-wide — the only context menus in the Workbench are our own
 * Vue ones, which never rely on the native menu.
 */
import { describe, expect, it } from "vitest";
import { blockNativeContextMenu } from "../contextMenu";

describe("blockNativeContextMenu (PP r8)", () => {
  it("prevents the default action of every document contextmenu event", () => {
    blockNativeContextMenu();
    const e = new MouseEvent("contextmenu", { cancelable: true, bubbles: true });
    document.body.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
  });
});
