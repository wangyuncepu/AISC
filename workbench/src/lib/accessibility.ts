/**
 * Stage 6 (UX-03): accessibility helpers.
 */

/** True when the OS/user requests reduced motion (prefers-reduced-motion). */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
