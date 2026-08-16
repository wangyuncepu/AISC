/**
 * Stage 6 (A-UX03-1): accessibility helpers.
 */
import { describe, expect, it, vi } from "vitest";
import { prefersReducedMotion } from "../accessibility";

describe("accessibility helpers (UX-03)", () => {
  it("reports reduced motion when the media query matches", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    expect(prefersReducedMotion()).toBe(true);
    vi.unstubAllGlobals();
  });

  it("reports no reduced motion when it does not match", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
    expect(prefersReducedMotion()).toBe(false);
    vi.unstubAllGlobals();
  });
});
