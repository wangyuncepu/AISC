/**
 * Stage 6 (A-UX02-1): responsive layout-tier classification.
 *
 * Tiers are by the effective app-box width (viewport / CSS zoom), so the
 * boundaries are exact: Compact < 640, Standard 640–1100, Wide > 1100.
 */
import { describe, expect, it } from "vitest";
import { layoutTierFor } from "../layout";

describe("layout tier (A-UX02-1)", () => {
  it("classifies compact below 640", () => {
    expect(layoutTierFor(320)).toBe("compact");
    expect(layoutTierFor(639)).toBe("compact");
  });

  it("classifies standard at 640–1100 inclusive", () => {
    expect(layoutTierFor(640)).toBe("standard");
    expect(layoutTierFor(800)).toBe("standard");
    expect(layoutTierFor(1100)).toBe("standard");
  });

  it("classifies wide above 1100", () => {
    expect(layoutTierFor(1101)).toBe("wide");
    expect(layoutTierFor(1280)).toBe("wide");
  });

  it("never crashes on degenerate widths", () => {
    expect(layoutTierFor(0)).toBe("compact");
    expect(layoutTierFor(Number.POSITIVE_INFINITY)).toBe("wide");
  });
});
