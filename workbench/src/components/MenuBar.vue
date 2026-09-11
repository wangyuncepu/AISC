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
import { open } from "@tauri-apps/plugin-dialog";
import { useToastStore } from "../stores/toast";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspacesStore } from "../stores/workspaces";
import { useSettingsStore } from "../stores/settings";
import { useTeleportedZoom } from "../lib/useTeleportedZoom";
import { useDoctorStore } from "../stores/doctor";

const { t } = useI18n();
const facade = useRuntimeStore();
const doctor = useDoctorStore();
const ws = useWorkspacesStore();
const settings = useSettingsStore();
const toast = useToastStore();
const { zoomStyle } = useTeleportedZoom();

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
async function openByPath(path: string): Promise<void> {
  closeMenu();
  if (!ws.openLauncher()) {
    toast.error(t("workspbar.capHint"));
    return;
  }
  // Same rule as the picker (R4): a POSIX path names a REMOTE workspace.
  const pathRemote = path.startsWith("/");
  const nowRemote = settings.target?.kind === "remote";
  if (pathRemote !== nowRemote) {
    const name = settings.target?.machine?.name
      ?? settings.doc?.remoteMachines?.[0]?.name ?? null;
    await settings.switchTarget(pathRemote ? name : null);
  }
  if (!(await ws.workspacePathExists(path))) {
    toast.error(t("menubar.pathMissing", { path }));
    return;
  }
  facade.selectRecentWorkspace(path);
}

async function openFromFolder(): Promise<void> {
  closeMenu();
  const picked = await open({
    directory: true, multiple: false, title: t("menubar.openFolder"),
  });
  if (typeof picked === "string") void openByPath(picked);
}

async function openFromMachine(): Promise<void> {
  closeMenu();
  const machine = settings.target?.machine?.name
    ?? settings.doc?.remoteMachines?.[0]?.name ?? null;
  if (!machine) {
    toast.error(t("menubar.noMachines"));
    return;
  }
  await settings.switchTarget(machine);
  if (!ws.openLauncher()) toast.error(t("workspbar.capHint"));
}

const recents = computed(() =>
  ws.recentWorkspaces.slice(0, 8).map((r) => ({
    path: r.path,
    label: r.path.replace(/[\/]+$/, "").split(/[\/]/).pop() || r.path,
  })));

function menuPos(which: string): { left: string; top: string } {
  const btn = menuBtn.value[which];
  if (!btn) return { left: "8px", top: "32px" };
  const r = btn.getBoundingClientRect();
  return { left: `${r.left}px`, top: `${r.bottom + 2}px` };
}

function newWindow(): void {
  closeMenu();
  if (!ws.openLauncher()) toast.error(t("workspbar.capHint"));
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
          <li class="sep" role="separator" />
          <li
            v-for="r in recents"
            :key="r.path"
            role="menuitem"
            tabindex="0"
            :title="r.path"
            @click="openByPath(r.path)"
          >
            {{ t("menubar.recentPrefix") }}{{ r.label || r.path }}
          </li>
          <li v-if="!recents.length" class="dim" role="presentation">
            {{ t("menubar.noRecents") }}
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
.menubar-drop kbd {
  font-family: inherit;
  font-size: var(--font-xs);
  color: var(--text-muted);
}
</style>
