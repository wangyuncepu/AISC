/**
 * W3 (shell-redesign, ruling c): ONE workspace per window. Every
 * workspace-opening entry point (menu 操作 / boot param) funnels through
 * here — a fresh WebviewWindow running the same SPA with ?workspace=
 * (POSIX ⇒ remote, ?machine names the drive) or bare (?machine only ⇒ a
 * remote launcher). The OS taskbar owns cross-workspace switching.
 */
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { getCurrentWindow } from "@tauri-apps/api/window";

export interface WorkspaceWindowOpts {
  /** Absolute path; POSIX paths are REMOTE workspaces (R4 rule). */
  workspace?: string;
  /** Drive target to switch the new window to (remote machine name). */
  machine?: string | null;
}

function winUuid(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function openWorkspaceWindow(opts: WorkspaceWindowOpts = {}): Promise<void> {
  const params = new URLSearchParams();
  if (opts.workspace) params.set("workspace", opts.workspace);
  if (opts.machine) params.set("machine", opts.machine);
  const qs = params.toString();
  const url = `${location.pathname}${qs ? `?${qs}` : ""}`;
  const cur = getCurrentWindow();
  // Inherit the opener's size — new windows should feel like siblings, not
  // reset to a default. Fall back to a sane default if the size read fails.
  let inner = { width: 1280, height: 820 };
  try {
    const s = await cur.innerSize();
    // innerSize is PHYSICAL px; toLogical keeps DPI right.
    const f = await cur.scaleFactor();
    inner = { width: Math.max(640, Math.round(s.width / f)), height: Math.max(480, Math.round(s.height / f)) };
  } catch { /* default */ }
  const win = new WebviewWindow(`ws-${winUuid()}`, {
    url,
    title: "AISC Workbench",
    width: inner.width,
    height: inner.height,
    center: true,
  });
  win.once("tauri://error", (e) => console.warn("[w3] window spawn failed:", e));
}
