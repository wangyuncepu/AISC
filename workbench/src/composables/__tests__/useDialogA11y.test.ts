/**
 * Stage 10 (10e, B-07): the shared dialog-a11y contract — Escape closes,
 * Tab/Shift+Tab stay trapped inside the panel, and the opener regains focus
 * on close. The baseline manual pass reported Escape dead everywhere; these
 * tests pin the logic so any regression is a runtime/IPC issue, not logic.
 */
import { mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { describe, expect, it, vi } from "vitest";
import { useDialogA11y } from "../useDialogA11y";

function keyEvent(key: string, shift = false): KeyboardEvent {
  return new KeyboardEvent("keydown", { key, shiftKey: shift, bubbles: true });
}

function mountDialog(onClose: () => void) {
  const opener = document.createElement("button");
  document.body.appendChild(opener);
  opener.focus();

  const Comp = defineComponent({
    setup() {
      const panel = ref<HTMLElement | null>(null);
      useDialogA11y(panel, onClose);
      return () =>
        h("div", { ref: panel, tabindex: "-1" }, [
          h("button", { id: "first" }, "first"),
          h("button", { id: "last" }, "last"),
        ]);
    },
  });
  const wrapper = mount(Comp, { attachTo: document.body });
  // jsdom has no layout — stub boxes so the composable's visibility test
  // (offsetWidth/height/client-rects) sees the buttons, as a browser would.
  for (const id of ["first", "last"]) {
    const el = wrapper.find(`#${id}`).element as HTMLElement;
    Object.defineProperty(el, "offsetWidth", { value: 40, configurable: true });
  }
  return { wrapper, opener };
}

describe("useDialogA11y (B-07)", () => {
  it("Escape calls onClose", () => {
    const onClose = vi.fn();
    const { wrapper } = mountDialog(onClose);
    window.dispatchEvent(keyEvent("Escape"));
    expect(onClose).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("Tab on the last item wraps to the first", () => {
    const onClose = vi.fn();
    const { wrapper } = mountDialog(onClose);
    const last = wrapper.find("#last").element as HTMLElement;
    last.focus();
    window.dispatchEvent(keyEvent("Tab"));
    expect(document.activeElement?.id).toBe("first");
    wrapper.unmount();
  });

  it("Shift+Tab on the first item wraps to the last", () => {
    const { wrapper } = mountDialog(vi.fn());
    const first = wrapper.find("#first").element as HTMLElement;
    first.focus();
    window.dispatchEvent(keyEvent("Tab", true));
    expect(document.activeElement?.id).toBe("last");
    wrapper.unmount();
  });

  it("Tab from focus outside the panel pulls back inside (full trap)", () => {
    const onClose = vi.fn();
    const { wrapper } = mountDialog(onClose);
    // Focus somewhere under the dialog (the drawer toggle outside the panel).
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    window.dispatchEvent(keyEvent("Tab"));
    expect(document.activeElement?.id).toBe("first");
    outside.remove();
    wrapper.unmount();
  });

  it("focus returns to the opener on unmount", () => {
    const openerEl = document.createElement("button");
    document.body.appendChild(openerEl);
    openerEl.focus();

    const Comp = defineComponent({
      setup() {
        const panel = ref<HTMLElement | null>(null);
        useDialogA11y(panel, () => undefined);
        return () => h("div", { ref: panel, tabindex: "-1" }, "body");
      },
    });
    const wrapper = mount(Comp, { attachTo: document.body });
    (wrapper.element as HTMLElement).focus();
    wrapper.unmount();
    expect(document.activeElement).toBe(openerEl);
    openerEl.remove();
  });
});
