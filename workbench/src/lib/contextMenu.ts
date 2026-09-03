/**
 * PP r8 (user request 2026-09-03): the ONLY context menus in the Workbench
 * are our own Vue ones (terminal / explorer / tab bar / workspace bar) —
 * the WebView2 default menu (Cut/Copy/Paste…) never belongs in the product.
 *
 * Calling preventDefault on a document-level contextmenu listener suppresses
 * the native menu app-wide without touching our own menus: they render their
 * own DOM on the same event and never rely on the native one. Clipboard
 * actions stay available via Ctrl+C/Ctrl+V (and our menus' own entries).
 */
export function blockNativeContextMenu(doc: Document = document): void {
  doc.addEventListener("contextmenu", (e) => e.preventDefault());
}
