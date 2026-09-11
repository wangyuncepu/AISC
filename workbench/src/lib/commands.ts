/**
 * P2-4 (D-4 / ui-review A1): the COMMAND REGISTRY — the palette's data
 * source. One row per user-facing action, reusing the existing menu i18n
 * keys (the menus stay the ground truth for labels; the registry adds the
 * runnable + its shortcut so the palette and `aria-keyshortcuts` share it).
 *
 * Layer contract: entries carry labels via i18n KEYS (resolved at render,
 * never baked here) and actions as thunks resolved at INVOCATION time —
 * the registry never imports stores (the consumer injects a `ctx` of store
 * actions), keeping it pure data + trivially testable.
 */

export interface CommandEntry {
  id: string;
  /** i18n key for the display label. */
  labelKey: string;
  /** i18n key for the group header (palette renders groups). */
  groupKey: string;
  /** Shown right-aligned (VS Code style) + used for aria-keyshortcuts. */
  shortcut?: string;
  /** Availability — e.g. tabs need a ready workspace. */
  when?: (ctx: CommandCtx) => boolean;
  /** Sub-selection id — the palette swaps to a fixed follow-up list. */
  sub?: "split:h" | "split:v";
  run: (ctx: CommandCtx) => void;
}

export interface CommandCtx {
  /** runtime facade — the ACTIVE workspace's store surface. */
  active: {
    createTab: (agent: "bash" | "claude" | "codex") => void;
    splitPane: (dir: "h" | "v", agent: "bash" | "claude" | "codex") => void;
    status: string;
    workspace: string;
  };
  app: {
    openSettings: () => void;
    openNetworkUsage: () => void;
    openPicker: () => void;
    runDoctor: () => void;
    toggleSidebar: () => void;
    showView: (kind: "explorer" | "conversations" | "artifacts" | "services") => void;
    servicesSupported: () => boolean;
  };
}

const ready = (ctx: CommandCtx) => ctx.active.status === "ready";

/** The registry — a static list; availability via `when`. */
export function buildCommands(): CommandEntry[] {
  return [
    // --- Tabs / sessions (group: tab) ---
    {
      id: "tab.new.bash", labelKey: "tabbar.menu.bash", groupKey: "palette.group.tab",
      when: ready, run: (c) => c.active.createTab("bash"),
    },
    {
      id: "tab.new.claude", labelKey: "tabbar.menu.claude", groupKey: "palette.group.tab",
      when: ready, run: (c) => c.active.createTab("claude"),
    },
    {
      id: "tab.new.codex", labelKey: "tabbar.menu.codex", groupKey: "palette.group.tab",
      when: ready, run: (c) => c.active.createTab("codex"),
    },
    {
      id: "pane.split.h", labelKey: "tabbar.menu.splitH", groupKey: "palette.group.tab",
      // 手测 r2#3: SAME flow as the pane context menu — the axis opens a
      // session-type sub-step (rendered by the palette), the split runs with
      // the CHOSEN agent (never a silent default).
      when: ready, sub: "split:h",
      run: (c) => c.active.splitPane("h", "bash"),
    },
    {
      id: "pane.split.v", labelKey: "tabbar.menu.splitV", groupKey: "palette.group.tab",
      when: ready, sub: "split:v",
      run: (c) => c.active.splitPane("v", "bash"),
    },

    // --- Views (group: view) ---
    {
      id: "view.files", labelKey: "explorer.tab.files", groupKey: "palette.group.view",
      when: ready, run: (c) => c.app.showView("explorer"),
    },
    {
      id: "view.conversations", labelKey: "explorer.tab.conversations", groupKey: "palette.group.view",
      when: ready, run: (c) => c.app.showView("conversations"),
    },
    {
      id: "view.artifacts", labelKey: "explorer.tab.artifacts", groupKey: "palette.group.view",
      when: ready, run: (c) => c.app.showView("artifacts"),
    },
    {
      id: "view.services", labelKey: "explorer.tab.services", groupKey: "palette.group.view",
      when: (c) => ready(c) && c.app.servicesSupported(),
      run: (c) => c.app.showView("services"),
    },
    {
      id: "view.sidebar.toggle", labelKey: "palette.cmd.toggleSidebar",
      groupKey: "palette.group.view", shortcut: "Ctrl+B",
      run: (c) => c.app.toggleSidebar(),
    },

    // --- App (group: app) ---
    {
      id: "app.settings", labelKey: "workspbar.settings", groupKey: "palette.group.app",
      shortcut: "Ctrl+,", run: (c) => c.app.openSettings(),
    },
    {
      id: "app.networkUsage", labelKey: "workspbar.networkUsage", groupKey: "palette.group.app",
      run: (c) => c.app.openNetworkUsage(),
    },
    {
      // 手测 r1#2: OPEN A NEW launcher page — never reset the active
      // workspace (same + button semantics as the strip).
      id: "app.picker", labelKey: "palette.cmd.openPicker", groupKey: "palette.group.app",
      run: (c) => c.app.openPicker(),
    },
    {
      id: "app.doctor", labelKey: "palette.cmd.runDoctor", groupKey: "palette.group.app",
      run: (c) => c.app.runDoctor(),
    },
  ];
}
