/**
 * P2-1 (A2 反馈语法统一): the GLOBAL toast primitive — one queue, one host
 * (ToastHost.vue, mounted once in App), any feature pushes feedback through
 * `useToastStore().push(...)`. VS Code parity: transient outcomes surface
 * as toasts, not inline state each feature re-invents.
 *
 * Design notes (手测 r2 裁决纳入):
 * - ALL toasts render bottom-center (the position the cc-switch switch
 *   feedback made familiar) and scale with ui.font_scale — same place,
 *   same size language as the rest of the UI.
 * - Errors outlive successes (6s vs 3s) — a failure the user must be able
 *   to read cannot race away at success speed.
 * - "progress" kind is STICKY by default (no timer) and updateable in
 *   place (`update(id, message)`) — long ops (e.g. provider 切换中… xS)
 *   show a live card that the completion toast replaces in the SAME spot.
 * - Optional single action (VS Code style: "重新加载" / "打开…") — clicking
 *   it runs the callback and dismisses the toast.
 * - IDs are monotonic; `dismiss(id)` is the only removal path besides the
 *   per-item timer. Timers are cleaned on dismissal (no leaks on rapid
 *   push/dismiss cycles).
 */
import { defineStore } from "pinia";
import { ref } from "vue";

export type ToastKind = "info" | "success" | "error" | "progress";

export interface ToastAction {
  label: string;
  run: () => void;
}

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
}

/** Default lifetime per kind. 0 = sticky (no auto-dismiss timer). */
export const TOAST_DURATION_MS: Record<ToastKind, number> = {
  info: 3000,
  success: 3000,
  error: 6000,
  progress: 0,
};

export const useToastStore = defineStore("uiToast", () => {
  const toasts = ref<ToastItem[]>([]);
  const timers = new Map<number, number>();
  let seq = 0;

  function dismiss(id: number): void {
    const t = timers.get(id);
    if (t !== undefined) {
      window.clearTimeout(t);
      timers.delete(id);
    }
    toasts.value = toasts.value.filter((item) => item.id !== id);
  }

  function push(
    message: string,
    opts: { kind?: ToastKind; action?: ToastAction; durationMs?: number } = {},
  ): number {
    const kind = opts.kind ?? "info";
    const id = ++seq;
    toasts.value = [...toasts.value, { id, kind, message, action: opts.action }];
    const ms = opts.durationMs ?? TOAST_DURATION_MS[kind];
    if (ms > 0) {
      timers.set(id, window.setTimeout(() => dismiss(id), ms));
    }
    return id;
  }

  /** In-place message update for sticky/live toasts (progress cards). */
  function update(id: number, message: string): void {
    toasts.value = toasts.value.map((item) =>
      item.id === id ? { ...item, message } : item,
    );
  }

  /** Convenience wrappers — call sites read better and the kind can never
   * drift from the intent. */
  const info = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "info" });
  const success = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "success" });
  const error = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "error" });

  return { toasts, push, info, success, error, update, dismiss };
});
