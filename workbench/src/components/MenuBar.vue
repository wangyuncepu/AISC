<script setup lang="ts">
/**
 * W2 (shell-redesign, user ruling a/b): the VS Code-style IN-WINDOW menu
 * bar — 操作 / 编辑 / 帮助. Dropdowns teleport to body (zoom-aware via
 * useTeleportedZoom). The 操作 menu's window items are W3-aware: until
 * one-window-per-workspace lands they open workspace TABS (the launcher);
 * the labels match the user's ruling verbatim so W3 only swaps the action.
 *
 * v1 semantics:
 * - 新建窗口 → launcher page (W3: a real WebviewWindow)
 * - 从文件夹打开工作区 → OS folder dialog, then the recent-open flow
 *   (target switch + existence probe + selectRecentWorkspace)
 * - 打开最近的工作区 / 从远程机器打开工作区 → same flow by path / machine
 * - 编辑：设置（Ctrl+,）、命令面板（Ctrl+Shift+P）
 * - 帮助：关于（the doctor dialog carries the version quartet）、文档
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import { useToastStore } from "../stores/toast";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspacesStore } from "../stores/workspaces";
import { useSettingsStore } from "../stores/settings";
import { useTeleportedZoom } from "../lib/useTeleportedZoom";
import { useDoctorStore } from "../stores/doctor";
import { openWorkspaceWindow } from "../lib/workspaceWindow";

const { t } = useI18n();
const facade = useRuntimeStore();
const doctor = useDoctorStore();
const ws = useWorkspacesStore();
const settings = useSettingsStore();
const toast = useToastStore();
const { zoomStyle } = useTeleportedZoom();

// P2-2 → W3: the global status label rides the menu bar's right end now
// (the workspace strip is retired). Same quiet-text language.
const STATUS_KEY: Record<string, string> = {
  picker: "app.status.picker",
  preflight: "app.preflight",
  summary: "app.status.summary",
  starting: "app.starting",
  cancelled: "app.status.cancelled",
  building: "app.status.building",
  conflict: "app.status.conflict",
  ready: "app.status.ready",
  stopping: "app.stopping",
  error: "app.error.title",
};
const statusRaw = computed(() => facade.status);
const statusLabel = computed(() =>
  facade.dockerStarting
    ? t("app.dockerStartingStatus")
    : t(STATUS_KEY[facade.status] ?? "app.unknown")
);

const openMenu = ref<"ops" | "edit" | "help" | null>(null);
const menuBtn = ref<Record<string, HTMLButtonElement | null>>({});

function toggle(which: "ops" | "edit" | "help"): void {
  openMenu.value = openMenu.value === which ? null : which;
}

function closeMenu(): void {
  const which = openMenu.value;
  openMenu.value = null;
  if (which) menuBtn.value[which]?.focus();
}

function onDocMousedown(e: MouseEvent): void {
  const el = e.target as HTMLElement;
  if (!el.closest(".menubar") && !el.closest(".menubar-drop")) closeMenu();
}
function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && openMenu.value) {
    e.preventDefault();
    closeMenu();
  }
}
onMounted(() => {
  document.addEventListener("mousedown", onDocMousedown);
  window.addEventListener("keydown", onKeydown, { capture: true });
});
onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocMousedown);
  window.removeEventListener("keydown", onKeydown, { capture: true });
});

/** The recent-open flow lifted out of the picker's onRecentClick (W2):
 * target switch on path-kind mismatch, existence probe, then the ACTIVE
 * launcher instance takes the path into its state machine. */
/** 手测 r2#2: the drive target is PROCESS-GLOBAL (one machine per app
 * run — remote/local CLI capabilities cannot mix). The menu therefore
 * NEVER flips it silently: same-kind recents spawn a window directly;
 * cross-kind opens REQUIRE the explicit confirm below. No openLauncher()
 * here either — the CURRENT window must not be yanked to the picker. */
async function openByPath(path: string, machine?: string | null): Promise<void> {
  closeMenu();
  // Same rule as the picker (R4): a POSIX path names a REMOTE workspace.
  const pathRemote = path.startsWith("/");
  const nowRemote = settings.target?.kind === "remote";
  const targetMachine = pathRemote
    ? (machine ?? settings.target?.machine?.name
      ?? settings.doc?.remoteMachines?.[0]?.name ?? null)
    : null;
  if (pathRemote !== nowRemote) {
    const ok = await confirm(t(pathRemote ? "menubar.switchToRemoteConfirm" : "menubar.switchToLocalConfirm", {
      machine: targetMachine ?? "",
    }));
    if (!ok) return;
  }
  if (!(await ws.workspacePathExists(path))) {
    toast.error(t("menubar.pathMissing", { path }));
    return;
  }
  void openWorkspaceWindow({ workspace: path, machine: targetMachine });
}

async function openFromFolder(): Promise<void> {
  closeMenu();
  const picked = await open({
    directory: true, multiple: false, title: t("menubar.openFolder"),
  });
  if (typeof picked === "string") {
    void openWorkspaceWindow({ workspace: picked });
  }
}

async function openFromMachine(): Promise<void> {
  closeMenu();
  const machine = settings.target?.machine?.name
    ?? settings.doc?.remoteMachines?.[0]?.name ?? null;
  if (!machine) {
    toast.error(t("menubar.noMachines"));
    return;
  }
  // A remote launcher window: the drive target switches on boot, the
  // picker's remote browse carries the rest.
  void openWorkspaceWindow({ machine });
}

/** 手测 r2#1/#2: VS Code-style flyout, classified 本地/远程（按机器）——
 * the kinds must never silently mix (process-global drive target). */
function baseOf(p: string): string {
  return p.replace(/[\/]+$/, "").split(/[\/]/).pop() || p;
}
const recentsLocal = computed(() =>
  ws.recentWorkspaces.filter((r) => !r.path.startsWith("/")).slice(0, 8)
    .map((r) => ({ path: r.path, label: baseOf(r.path) })));
const recentsRemote = computed(() =>
  ws.recentWorkspaces.filter((r) => r.path.startsWith("/")).slice(0, 8)
    .map((r) => ({ path: r.path, label: baseOf(r.path) })));

function menuPos(which: string): { left: string; top: string } {
  const btn = menuBtn.value[which];
  if (!btn) return { left: "8px", top: "32px" };
  const r = btn.getBoundingClientRect();
  return { left: `${r.left}px`, top: `${r.bottom + 2}px` };
}

function newWindow(): void {
  closeMenu();
  void openWorkspaceWindow();
}
function openSettings(): void {
  closeMenu();
  ws.openSettingsTab();
}
function openPalette(): void {
  closeMenu();
  window.dispatchEvent(new CustomEvent("aisc:open-palette"));
}
function openAbout(): void {
  closeMenu();
  doctor.openDialog();
}
async function openDocs(): Promise<void> {
  closeMenu();
  window.open("https://github.com/wangyuncepu/AISC#readme", "_blank", "noopener");
}
</script>

<template>
  <div class="menubar" role="menubar" :aria-label="t('menubar.label')">
    <button
      :ref="(el) => (menuBtn['ops'] = el as HTMLButtonElement | null)"
      class="menubar-btn"
      :class="{ open: openMenu === 'ops' }"
      aria-haspopup="menu"
      :aria-expanded="openMenu === 'ops'"
      @click="toggle('ops')"
    >{{ t("menubar.ops") }}</button>
    <button
      :ref="(el) => (menuBtn['edit'] = el as HTMLButtonElement | null)"
      class="menubar-btn"
      :class="{ open: openMenu === 'edit' }"
      aria-haspopup="menu"
      :aria-expanded="openMenu === 'edit'"
      @click="toggle('edit')"
    >{{ t("menubar.edit") }}</button>
    <button
      :ref="(el) => (menuBtn['help'] = el as HTMLButtonElement | null)"
      class="menubar-btn"
      :class="{ open: openMenu === 'help' }"
      aria-haspopup="menu"
      :aria-expanded="openMenu === 'help'"
      @click="toggle('help')"
    >{{ t("menubar.help") }}</button>

    <span class="mb-spacer" />
    <span class="mb-status" :data-status="statusRaw" :title="statusLabel">
      {{ statusLabel }}
    </span>

    <Teleport to="body">
      <ul
        v-if="openMenu"
        class="menubar-drop menu"
        role="menu"
        :style="{ ...menuPos(openMenu), ...zoomStyle }"
      >
        <template v-if="openMenu === 'ops'">
          <li role="menuitem" tabindex="0" @click="newWindow">
            {{ t("menubar.newWindow") }}
          </li>
          <li role="menuitem" tabindex="0" @click="openFromFolder">
            {{ t("menubar.openFolder") }}
          </li>
          <!-- 手测 r2#1: VS Code-style flyout — hover reveals the classified
               recents (本地 first, 远程 grouped under the machine rule). -->
          <li
            v-if="recentsLocal.length || recentsRemote.length"
            class="has-sub"
            role="menuitem"
            tabindex="0"
            aria-haspopup="menu"
          >
            {{ t("menubar.openRecent") }}<span class="sub-arrow">▸</span>
            <ul class="menubar-sub" role="menu">
              <li v-if="recentsLocal.length" class="sub-head" role="presentation">
                {{ t("menubar.groupLocal") }}
              </li>
              <li
                v-for="r in recentsLocal"
                :key="r.path"
                class="recent"
                role="menuitem"
                tabindex="0"
                @click="openByPath(r.path)"
              >
                <span class="recent-name">{{ r.label }}</span>
                <span class="recent-path">{{ r.path }}</span>
              </li>
              <li v-if="recentsRemote.length" class="sub-head" role="presentation">
                {{ t("menubar.groupRemote") }}
              </li>
              <li
                v-for="r in recentsRemote"
                :key="r.path"
                class="recent"
                role="menuitem"
                tabindex="0"
                @click="openByPath(r.path)"
              >
                <span class="recent-name">{{ r.label }}</span>
                <span class="recent-path">{{ r.path }}</span>
              </li>
              <li v-if="!recentsLocal.length && !recentsRemote.length" class="dim" role="presentation">
                {{ t("menubar.noRecents") }}
              </li>
            </ul>
          </li>
          <li class="sep" role="separator" />
          <li role="menuitem" tabindex="0" @click="openFromMachine">
            {{ t("menubar.openRemote") }}
          </li>
        </template>
        <template v-else-if="openMenu === 'edit'">
          <li role="menuitem" tabindex="0" @click="openSettings">
            {{ t("workspbar.settings") }}
            <kbd>Ctrl+,</kbd>
          </li>
          <li role="menuitem" tabindex="0" @click="openPalette">
            {{ t("palette.title") }}
            <kbd>Ctrl+Shift+P</kbd>
          </li>
        </template>
        <template v-else>
          <li role="menuitem" tabindex="0" @click="openAbout">
            {{ t("menubar.about") }}
          </li>
          <li role="menuitem" tabindex="0" @click="openDocs">
            {{ t("menubar.docs") }}
          </li>
        </template>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.menubar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  background: var(--surface);
  border-bottom: var(--border-w) solid var(--border);
}
.menubar-btn {
  background: none;
  border: none;
  color: var(--text-2);
  font-size: var(--font-sm);
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.menubar-btn:hover { background: var(--surface-hover); color: var(--text); }
.menubar-btn.open { background: var(--accent-soft); color: var(--accent); }
.mb-spacer { flex: 1; }
.mb-status {
  font-size: var(--font-sm);
  color: var(--text-muted);
  white-space: nowrap;
}
.mb-status[data-status="ready"] { color: var(--success); }
.mb-status[data-status="error"],
.mb-status[data-status="blocked"] { color: var(--error); }
@media (max-width: 700px) { .mb-status { display: none; } } /* compact: keep the bar readable */
</style>

<style>
/* Unscoped: the dropdown teleports to body (outside any scoped boundary). */
.menubar-drop {
  position: fixed;
  z-index: var(--z-menu);
  min-width: 240px;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
}
.menubar-drop li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 14px;
  font-size: var(--font-sm);
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
}
.menubar-drop li:hover { background: var(--accent-soft); color: var(--text); }
.menubar-drop li.sep { height: 1px; padding: 0; margin: 4px 8px; background: var(--border); }
.menubar-drop li.dim { color: var(--text-faint); cursor: default; }
/* 手测 r2#1: the flyout submenu — hover (or focus-within) reveals it. */
.menubar-drop li.has-sub { position: relative; }
.menubar-drop li.has-sub .sub-arrow { color: var(--text-faint); }
.menubar-drop li.has-sub .menubar-sub {
  display: none;
  position: absolute;
  left: 100%;
  top: -5px;
  min-width: 320px;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
}
.menubar-drop li.has-sub:hover .menubar-sub,
.menubar-drop li.has-sub:focus-within .menubar-sub { display: block; }
.menubar-sub .sub-head {
  padding: 4px 14px 2px;
  font-size: var(--font-xs);
  color: var(--text-faint);
  letter-spacing: 0.5px;
  cursor: default;
}
.menubar-sub li.recent { padding: 5px 14px; }
/* 手测 r1#1: VS Code-style recents — name bold, full path dimmed below. */
.menubar-drop li.recent {
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 5px 14px;
}
.menubar-drop li.recent .recent-name { font-weight: 600; color: var(--text); }
.menubar-drop li.recent .recent-path {
  font-size: var(--font-xs);
  color: var(--text-faint);
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.menubar-drop kbd {
  font-family: inherit;
  font-size: var(--font-xs);
  color: var(--text-muted);
}
</style>
