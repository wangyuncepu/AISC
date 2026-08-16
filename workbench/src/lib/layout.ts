/**
 * Stage 6 (UX-02): responsive layout tiers.
 *
 * The tier is computed from the EFFECTIVE app-box width (viewport / CSS zoom),
 * not the raw viewport — the zoom system scales the 800px baseline, so a 320px
 * window still lays out at ~800px. Tiers (02-domain-contract.md):
 *   Compact  < 640px
 *   Standard 640–1100px
 *   Wide     > 1100px
 */
export type LayoutTier = "compact" | "standard" | "wide";

export function layoutTierFor(boxWidth: number): LayoutTier {
  if (boxWidth < 640) return "compact";
  if (boxWidth > 1100) return "wide";
  return "standard";
}
