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

/** Visibility WITHOUT offsetParent: per spec offsetParent is null for every
 * element under a position:fixed ancestor — the dialog overlay — so the old
 * filter emptied the list and the trap silently no-oped (B-07/B-08 root
 * cause: Tab leaked to the terminal, which then swallowed Escape). The
 * jQuery-style box test sees fixed-position children fine. */
function visible(el: HTMLElement): boolean {
  return el === document.activeElement ||
    el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0;
}

export function useDialogA11y(panel: Ref<HTMLElement | null>, onClose: () => void): void {
  let opener: Element | null = null;

  function keydown(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "Tab" && panel.value) {
      // 10e r2: FULL trap. The old boundary-only logic let focus escape
      // whenever it sat on an element outside the visible list (the overlay
      // itself, a filtered-out item) — Shift+Tab then reached the status
      // drawer under the dialog (user report). Consume every Tab and move
      // within the panel unconditionally.
      const items = Array.from(panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);
      if (items.length === 0) return;
      const active = document.activeElement;
      const inPanel = active instanceof Node && panel.value.contains(active);
      const idx = inPanel ? items.indexOf(active as HTMLElement) : -1;
      e.preventDefault();
      if (e.shiftKey) {
        (idx <= 0 ? items[items.length - 1] : items[idx - 1]).focus();
      } else {
        (idx === -1 ? items[0] : items[(idx + 1) % items.length]).focus();
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
