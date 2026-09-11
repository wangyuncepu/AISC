import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useToastStore, TOAST_DURATION_MS } from "../toast";

describe("global toast store (P2-1)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("push queues by kind with default durations and auto-dismisses", () => {
    const toast = useToastStore();
    toast.push("saved", { kind: "success" });
    toast.push("boom", { kind: "error" });
    expect(toast.toasts.map((x) => x.kind)).toEqual(["success", "error"]);
    expect(toast.toasts[0].message).toBe("saved");

    vi.advanceTimersByTime(TOAST_DURATION_MS.success);
    expect(toast.toasts.map((x) => x.message)).toEqual(["boom"]);

    vi.advanceTimersByTime(TOAST_DURATION_MS.error);
    expect(toast.toasts).toHaveLength(0);
  });

  it("errors outlive successes (duration table)", () => {
    expect(TOAST_DURATION_MS.error).toBeGreaterThan(TOAST_DURATION_MS.success);
  });

  it("dismiss cancels the auto timer and removes only that item", () => {
    const toast = useToastStore();
    const a = toast.info("a");
    const b = toast.info("b");
    toast.dismiss(a);
    expect(toast.toasts.map((x) => x.id)).toEqual([b]);
    // a's timer must be gone: firing it later removes nothing.
    vi.advanceTimersByTime(TOAST_DURATION_MS.info * 2);
    // b still pending at one duration — advance removed b by its own timer.
    expect(toast.toasts).toHaveLength(0);
  });

  it("explicit duration overrides the kind default", () => {
    const toast = useToastStore();
    toast.push("sticky", { kind: "info", durationMs: 10_000 });
    vi.advanceTimersByTime(TOAST_DURATION_MS.info);
    expect(toast.toasts).toHaveLength(1);
    vi.advanceTimersByTime(10_000);
    expect(toast.toasts).toHaveLength(0);
  });

  it("wrappers pin the kind", () => {
    const toast = useToastStore();
    toast.success("s");
    toast.error("e");
    expect(toast.toasts.map((x) => x.kind)).toEqual(["success", "error"]);
  });

  it("progress kind is sticky and updateable in place", () => {
    const toast = useToastStore();
    const id = toast.push("切换中… 0s", { kind: "progress" });
    // No auto-dismiss at any duration — the completion path dismisses it.
    vi.advanceTimersByTime(60_000);
    expect(toast.toasts).toHaveLength(1);
    toast.update(id, "切换中… 3s");
    expect(toast.toasts[0]!.message).toBe("切换中… 3s");
    expect(toast.toasts[0]!.kind).toBe("progress");
    toast.dismiss(id);
    expect(toast.toasts).toHaveLength(0);
  });

  it("update of a foreign id is a no-op", () => {
    const toast = useToastStore();
    const id = toast.info("a");
    toast.update(id + 999, "x");
    expect(toast.toasts[0]!.message).toBe("a");
  });
});
