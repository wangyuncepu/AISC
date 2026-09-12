/**
 * Vitest setup (jsdom). 手测 r5 收尾 (2026-09-12): jsdom does not implement
 * Element.scrollIntoView — the command palette's cursor-follow scroll threw
 * unhandled rejections on every run, leaving `vitest run` exit=1 even with
 * all 481 tests passing (a masked gate). Stub it globally here.
 */
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
