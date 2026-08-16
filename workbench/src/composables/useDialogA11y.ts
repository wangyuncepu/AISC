/**
 * Stage 6 (UX-03): modal-dialog accessibility — focus trap + opener restore.
 *
 * - Captures the opener element on mount (focus returns to it on close).
 * - Traps Tab / Shift+Tab inside the panel (cyclic), Escape closes.
 * - Inert on the rest of the app is provided by the modal overlay (the caller
 *   renders `<div class="overlay" role="presentation">` covering the app);
 *   this composable covers keyboard focus, which inert alone does not.
 *
 * Usage: `useDialogA11y(panelRef, () => emit("close"))`.
 */
import { onBeforeUnmount, onMounted, type Ref } from "vue";

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), " +
  "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function useDialogA11y(panel: Ref<HTMLElement | null>, onClose: () => void): void {
  let opener: Element | null = null;

  function keydown(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "Tab" && panel.value) {
      const items = Array.from(panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel.value)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  onMounted(() => {
    opener = document.activeElement;
    window.addEventListener("keydown", keydown);
  });
  onBeforeUnmount(() => {
    window.removeEventListener("keydown", keydown);
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
  });
}
