/**
 * P2-1 (A2 反馈语法统一): the GLOBAL toast primitive — one queue, one host
 * (ToastHost.vue, mounted once in App), any feature pushes feedback through
 * `useToastStore().push(...)`. The cc-switch switch-success toast was the
 * lone local instance (Teleport + role=status — the shape was right, the
 * scope was not); it migrates onto this store. VS Code parity: transient
 * outcomes surface as toasts, not inline state each feature re-invents.
 *
 * Design notes:
 * - Errors outlive successes (6s vs 3s) — a failure the user must be able
 *   to read cannot race away at success speed.
 * - Optional single action (VS Code style: "重新加载" / "打开…") — clicking
 *   it runs the callback and dismisses the toast.
 * - IDs are monotonic; `dismiss(id)` is the only removal path besides the
 *   per-item timer. Timers are cleaned on dismissal (no leaks on rapid
 *   push/dismiss cycles).
 */
import { defineStore } from "pinia";
import { ref } from "vue";

export type ToastKind = "info" | "success" | "error";

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

export const TOAST_DURATION_MS: Record<ToastKind, number> = {
  info: 3000,
  success: 3000,
  error: 6000,
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
    timers.set(id, window.setTimeout(() => dismiss(id), ms));
    return id;
  }

  /** Convenience wrappers — call sites read better and the kind can never
   * drift from the intent. */
  const info = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "info" });
  const success = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "success" });
  const error = (m: string, o?: Parameters<typeof push>[1]) => push(m, { ...o, kind: "error" });

  return { toasts, push, info, success, error, dismiss };
});
