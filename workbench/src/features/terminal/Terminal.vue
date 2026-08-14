<script setup lang="ts">
/**
 * Terminal component (S2.2.a): tab-scoped PTY view.
 *
 * - Each non-idle tab renders one Terminal instance; only the active tab is
 *   visible (v-show in App.vue). Hidden tabs keep running (03 §六.8).
 * - Watches the tab's `sessionId`; on change opens a session via a Tauri
 *   Channel<PtyEvent> (channel created before the invoke, so no first-screen
 *   output is lost - S1.3 invariant).
 * - Output events: base64 bytes -> Uint8Array -> term.write.
 * - onData: UTF-8 encode -> write_session (paste capped backend-side).
 * - ResizeObserver throttled + re-fit when the tab becomes visible.
 * - PTY Exit is the single terminal signal (03 §五.2); reported to the store
 *   which merges duplicate terminate/exit results into one TabExit.
 *
 * G-03/G-11 (Step 11): SearchAddon (Ctrl+F search bar, prev/next, case,
 * Esc close), context menu (copy/paste/search/clear) via the Tauri clipboard
 * plugin (only read-text/write-text granted), and per-pane dispose of all
 * addons/listeners in onBeforeUnmount (03 §七).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Terminal, type ITerminalOptions } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { SearchAddon } from "@xterm/addon-search";
import { readText, writeText } from "@tauri-apps/plugin-clipboard-manager";
import "@xterm/xterm/css/xterm.css";
import { useRuntimeStore } from "../../stores/runtime";
import { computeDisplayFrom } from "../../domain/streamBuffer";
import { useSettingsStore } from "../../stores/settings";
import { AGENTS } from "../../stores/tabLayout";
import { resizeSession, writeSession } from "../../lib/ipc";
import { resolveRenderer, terminalTheme } from "./renderer";
import { effectiveTheme } from "../../theme";
import { findLeaf } from "../../stores/paneTree";
import type { LaunchAgent } from "../../types";

const { t } = useI18n();
const props = defineProps<{ tabId: string; paneId: string }>();
const store = useRuntimeStore();
const settingsStore = useSettingsStore();

const container = ref<HTMLDivElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);
// G-17: the Terminal is pane-scoped (a split tab has one instance per leaf).
// It is a PURE VIEW: the store owns the session channel + output buffer
// (paneStreams), so remounting a pane (tree restructure) never re-opens or
// drops the session.
const tab = computed(() => store.tabs.find((t) => t.tabId === props.tabId));
const pane = computed(() => tab.value?.panes[props.paneId] ?? null);
const sessionId = computed(() => pane.value?.sessionId ?? null);
const visible = computed(
  () => store.activeTabId === props.tabId && tab.value?.activePaneId === props.paneId
);
/** Whether this pane has a live session (paste/copy enabled, G-11). */
const sessionLive = computed(() => {
  const st = pane.value?.sessionState;
  return st === "starting" || st === "running" || st === "closing";
});
/** G-17: cc-switch panes are a config TUI - no split offered (user feedback). */
const isCcSwitch = computed(
  () => (tab.value ? findLeaf(tab.value.tree, props.paneId)?.sessionType === "cc-switch" : false)
);

let term: Terminal | null = null;
let fit: FitAddon | null = null;
let webgl: WebglAddon | null = null;
let searchAddon: SearchAddon | null = null;
let resizeTimer: number | null = null;
let resizeObserver: ResizeObserver | null = null;

// G-03 search overlay state.
const searchOpen = ref(false);
const searchTerm = ref("");
const caseSensitive = ref(false);
const searchResult = ref<{ current: number; total: number } | null>(null);
// G-11 context menu state.
const ctxMenu = ref<{ x: number; y: number } | null>(null);
/** G-17: after picking a split axis, choose which session type to open. */
const splitPicker = ref<{ x: number; y: number; axis: "horizontal" | "vertical" } | null>(null);
const hasSelection = ref(false);

/** G-06: build the Terminal from the typed settings (02 §三.4 table). Values
 * come from the backend; when settings are not yet loaded the xterm native
 * defaults are used (never a second hardcoded default copy). The renderer
 * enum is consumed by `mountWebgl`, never written into term.options. */
function terminalOptions(): ITerminalOptions {
  const s = settingsStore.doc?.terminal;
  return {
    fontFamily: s?.font_family || undefined,
    fontSize: s?.font_size,
    lineHeight: s?.line_height,
    letterSpacing: s?.letter_spacing,
    scrollback: s?.scrollback,
    smoothScrollDuration: s?.smooth_scroll_duration,
    convertEol: false,
    cursorBlink: true,
    theme: terminalTheme(effectiveTheme.value),
  };
}

/** G-06 (A-G06-1/2): load the WebglAddon per the Workbench renderer setting.
 * Construction failure and context loss both dispose the addon, falling back
 * to the DOM renderer - the session/PTY are untouched. */
function mountWebgl() {
  const choice = resolveRenderer(settingsStore.doc?.terminal.renderer ?? "auto", true);
  if (choice !== "webgl") return;
  try {
    const addon = new WebglAddon();
    addon.onContextLoss(() => {
      // Disposal hands rendering back to the DOM renderer automatically.
      addon.dispose();
      if (webgl === addon) webgl = null;
    });
    term!.loadAddon(addon);
    webgl = addon;
  } catch {
    /* construction failure (A-G06-2): stay on the DOM renderer */
  }
}

/** G-03/A-G03-1: load SearchAddon (per pane, disposed with the Terminal). */
function mountSearch() {
  try {
    const addon = new SearchAddon();
    addon.onDidChangeResults((r) => {
      searchResult.value = { current: r.resultIndex, total: r.resultCount };
    });
    term!.loadAddon(addon);
    searchAddon = addon;
  } catch {
    searchAddon = null;
  }
}

function onTermData(data: string) {
  const sid = sessionId.value;
  if (sid) {
    writeSession(sid, Array.from(new TextEncoder().encode(data))).catch(() => {});
  }
}

function b64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

/** Write one store-buffered output chunk to the xterm. */
function writeChunk(b64: string): void {
  if (term) term.write(b64ToUint8(b64));
}

/** G-06 (A-G06-3): rebuild the Terminal view in place for renderer/font-family
 * changes. The session is STORE-owned (output buffered in paneStreams), so the
 * rebuild disposes only the view and replays the buffer - the PTY/session are
 * untouched. */
function rebuildTerminal() {
  const host = container.value;
  if (!host || !term) return;
  term.dispose(); // also disposes loaded addons (webgl/fit/search)
  webgl = null;
  searchAddon = null;
  searchResult.value = null;
  term = new Terminal(terminalOptions());
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(host);
  term.writeln(t("terminal.welcome"));
  term.onData(onTermData);
  term.onSelectionChange(onSelectionChange);
  mountWebgl();
  mountSearch();
  for (const chunk of store.paneStreams[props.paneId] ?? []) writeChunk(chunk);
  if (visible.value) term.refresh(0, term.rows - 1);
  setTimeout(doResize, 0);
}

function scheduleResize() {
  if (!visible.value || resizeTimer !== null) return;
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null;
    doResize();
  }, 150);
}

function doResize() {
  if (!visible.value || !term || !fit || !sessionLive.value) return;
  try {
    fit.fit();
    const sid = sessionId.value;
    if (sid) resizeSession(sid, term.cols, term.rows).catch(() => {});
  } catch {
    /* container not laid out yet */
  }
}

// --- G-03/A-G03-1 search ---

function openSearch() {
  searchOpen.value = true;
  void nextTick(() => searchInput.value?.focus());
}

function closeSearch() {
  searchOpen.value = false;
  searchTerm.value = "";
  searchResult.value = null;
  searchAddon?.clearDecorations();
  term?.focus();
}

function doSearch() {
  if (!searchAddon) return;
  if (!searchTerm.value) {
    searchResult.value = null;
    searchAddon.clearDecorations();
    return;
  }
  searchAddon.findNext(searchTerm.value, { caseSensitive: caseSensitive.value });
}

function searchNext() {
  if (searchAddon && searchTerm.value) {
    searchAddon.findNext(searchTerm.value, { caseSensitive: caseSensitive.value });
  }
}

function searchPrev() {
  if (searchAddon && searchTerm.value) {
    searchAddon.findPrevious(searchTerm.value, { caseSensitive: caseSensitive.value });
  }
}

// --- G-11/A-G11-1 context menu ---

function onSelectionChange() {
  hasSelection.value = term?.hasSelection() ?? false;
}

function onContextMenu(e: MouseEvent) {
  e.preventDefault();
  // Clamp to the viewport so the menu never overflows the window.
  const x = Math.min(e.clientX, window.innerWidth - 180);
  const y = Math.min(e.clientY, window.innerHeight - 150);
  ctxMenu.value = { x, y };
}

function closeMenu() {
  ctxMenu.value = null;
  term?.focus(); // A-G11-1: menu close returns focus to the terminal
}

// --- G-17: split via the pane context menu + session-type picker ---
function openSplitPicker(axis: "horizontal" | "vertical", x: number, y: number) {
  splitPicker.value = { x, y, axis };
  ctxMenu.value = null;
}
function chooseSplitAgent(agent: LaunchAgent) {
  const p = splitPicker.value;
  splitPicker.value = null;
  term?.focus();
  if (!p) return;
  store.splitTabPane(props.tabId, p.axis, agent, true, props.paneId);
}

/** A-G03-2/A-G11-3: copy the current selection (keyboard + menu share this). */
async function doCopy() {
  const sel = term?.getSelection();
  if (!sel) return;
  try {
    await writeText(sel);
  } catch (err) {
    term?.write(`\r\n\x1b[31m${t("terminal.clipboardError", { message: String(err) })}\x1b[0m\r\n`);
  }
}

/** A-G03-2/A-G11-4: paste clipboard text into the session (1 MiB cap). */
async function doPaste() {
  try {
    const text = await readText();
    if (text && term) {
      // term.paste triggers onData -> write_session (respects 1 MiB cap, A-G11-4).
      term.paste(text);
    }
  } catch (err) {
    term?.write(`\r\n\x1b[31m${t("terminal.clipboardError", { message: String(err) })}\x1b[0m\r\n`);
  }
}

async function copySelection() {
  await doCopy();
  closeMenu();
}

async function pasteFromClipboard() {
  await doPaste();
  closeMenu();
}

function openSearchFromMenu() {
  closeMenu();
  openSearch();
}

function clearScreen() {
  term?.clear();
  closeMenu();
}

/** A-G03-1/A-G03-2: intercept Ctrl+F / copy / paste via xterm's custom key
 * handler so they work when the terminal has focus (a DOM listener on the
 * container misses keys captured by xterm's internal textarea). Returns true
 * to let the key reach the PTY, false to swallow it. */
function onTermCustomKey(e: KeyboardEvent): boolean {
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  // Ctrl/Cmd+Shift+C / Ctrl/Cmd+Shift+V: copy/paste (A-G03-2). Never reach
  // the PTY - plain Ctrl+C/V still work as SIGINT / literal-echo.
  if (mod && e.shiftKey && key === "c") {
    e.preventDefault();
    void doCopy();
    return false;
  }
  if (mod && e.shiftKey && key === "v") {
    e.preventDefault();
    void doPaste();
    return false;
  }
  // Ctrl/Cmd+F opens search (A-G03-1).
  if (mod && key === "f") {
    e.preventDefault();
    openSearch();
    return false;
  }
  // G-17: pane navigation + Ctrl+Shift+W close are handled by the WINDOW-level
  // capture handler in App.vue (runs before the terminal sees the key); the
  // xterm handler keeps only the terminal-specific bindings.
  // Esc closes the search overlay.
  if (e.key === "Escape" && searchOpen.value) {
    e.preventDefault();
    closeSearch();
    return false;
  }
  return true;
}

function onTerminalClick() {
  if (ctxMenu.value) ctxMenu.value = null;
  if (splitPicker.value) splitPicker.value = null;
}

onMounted(() => {
  term = new Terminal(terminalOptions());
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(container.value!);
  term.writeln(t("terminal.welcome"));
  term.onData(onTermData);
  term.onSelectionChange(onSelectionChange);
  term.attachCustomKeyEventHandler(onTermCustomKey);
  mountWebgl();
  mountSearch();
  fit.fit();

  resizeObserver = new ResizeObserver(scheduleResize);
  if (container.value) resizeObserver.observe(container.value);
  window.addEventListener("resize", scheduleResize);

  // Re-fit when this tab becomes the active (visible) view. v-show toggles
  // display:none; xterm does not repaint automatically on re-display, which
  // leaves a blank screen while the buffer/session stay intact. Force a full
  // viewport repaint after the re-fit.
  watch(visible, (v) => {
    if (v) {
      setTimeout(() => {
        doResize();
        term?.refresh(0, term.rows - 1);
      }, 0);
    }
  });

  // G-04 (Step 17, A-G04-2): apply the effective theme to the EXISTING xterm -
  // only its options change, never a rebuild / session / PTY.
  watch(effectiveTheme, (eff) => {
    if (!term) return;
    term.options.theme = terminalTheme(eff);
    term.refresh(0, term.rows - 1);
  });

  // G-17 / S1.3: stream the store-owned output buffer (replay what is already
  // there, then append live). The store now uses a ROLLING window (oldest
  // chunks dropped to stay within budget), so advancing by array length breaks:
  // once the window is full the length never changes and the terminal would
  // freeze. Advance by the monotonic streamCursor instead; computeDisplayFrom
  // re-anchors past any dropped head. Remounts never re-open the session.
  let consumed = 0;
  watch(
    () => store.streamCursor[props.paneId] ?? 0,
    () => {
      const arr = store.paneStreams[props.paneId] ?? [];
      const total = store.streamCursor[props.paneId] ?? 0;
      const from = computeDisplayFrom(consumed, total, arr.length);
      for (let i = from; i < arr.length; i++) writeChunk(arr[i]);
      consumed = Math.max(consumed, total);
    },
    { immediate: true }
  );
  // Session end hint: the STORE finalizes the pane state from the channel; this
  // view just reflects it (G-09: Workbench-written helper text follows locale).
  watch(
    () => pane.value?.sessionState,
    (st, prev) => {
      if (!prev || st === prev) return;
      if (st === "exited" || st === "disconnected") {
        const exit = pane.value?.exit;
        term?.write(
          `\r\n\x1b[90m[${t("terminal.exited")}: ${exit?.reason ?? st}${exit?.exitCode != null ? `, code ${exit.exitCode}` : ""}]\x1b[0m\r\n`
        );
      } else if (st === "failed") {
        term?.write(`\r\n\x1b[31m${t("terminal.openFailed", { code: "AISC_ERR_SESSION_FAILED" })}\x1b[0m\r\n`);
      }
    }
  );

  // S1.3 (F-A04): output truncation is observable - once the per-pane budget
  // is exceeded the store keeps dropping; surface it instead of pretending the
  // output is complete.
  watch(
    () => store.paneStreamMeta[props.paneId]?.truncated,
    (truncated) => {
      if (!truncated) return;
      const bytes = store.paneStreamMeta[props.paneId]?.truncatedBytes ?? 0;
      term?.write(
        `\r\n\x1b[33m${t("terminal.outputTruncated", { bytes: formatBytes(bytes) })}\x1b[0m\r\n`
      );
    },
    { immediate: true }
  );
});

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${bytes} B`;
}

// G-06 (A-G06-3): settings-driven updates. renderer/font_family rebuild the
// view in place (session_id/PTY untouched); the other terminal options apply
// immediately. Deep watch so in-dialog edits preview live and reverts heal.
watch(
  () => settingsStore.doc?.terminal,
  (t, prev) => {
    if (!term || !t) return;
    if (t.renderer !== prev?.renderer || t.font_family !== prev?.font_family) {
      rebuildTerminal();
      return;
    }
    term.options.fontSize = t.font_size;
    term.options.lineHeight = t.line_height;
    term.options.letterSpacing = t.letter_spacing;
    term.options.scrollback = t.scrollback;
    term.options.smoothScrollDuration = t.smooth_scroll_duration;
  },
  { deep: true }
);

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect();
  if (resizeTimer !== null) window.clearTimeout(resizeTimer);
  window.removeEventListener("resize", scheduleResize);
  term?.dispose(); // disposes fit/webgl/search addons + custom key handler (03 §七)
  term = null;
  fit = null;
  webgl = null;
  searchAddon = null;
});

// S3.3: allow the app-level tab shortcut (Ctrl/Cmd+1..4) to move keyboard focus
// into this terminal so typing works immediately after switching.
defineExpose({
  focus: () => {
    term?.focus();
  },
});
</script>

<template>
  <div
    ref="container"
    class="terminal"
    @contextmenu="onContextMenu"
    @click="onTerminalClick"
  >
    <!-- G-03 search overlay -->
    <div v-if="searchOpen" class="search-overlay" @click.stop>
      <input
        ref="searchInput"
        v-model="searchTerm"
        :placeholder="t('terminal.searchPlaceholder')"
        @input="doSearch"
        @keydown.enter.prevent="searchNext"
        @keydown.shift.enter.prevent="searchPrev"
        @keydown.esc.prevent="closeSearch"
      />
      <button class="nav" :aria-label="t('terminal.searchPrev')" @click="searchPrev">↑</button>
      <button class="nav" :aria-label="t('terminal.searchNext')" @click="searchNext">↓</button>
      <button
        class="case"
        :class="{ active: caseSensitive }"
        :aria-label="t('terminal.searchCase')"
        @click="caseSensitive = !caseSensitive; doSearch()"
      >Aa</button>
      <span class="result" :class="{ empty: searchResult?.total === 0 }">
        {{
          searchResult && searchResult.total > 0
            ? t("terminal.searchResult", { current: searchResult.current + 1, total: searchResult.total })
            : t("terminal.searchNoResult")
        }}
      </span>
      <button class="close" aria-label="Close" @click="closeSearch">×</button>
    </div>

    <!-- G-11 context menu -->
    <div
      v-if="ctxMenu"
      class="ctx-menu"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @contextmenu.prevent
      @click.stop
    >
      <button :disabled="!hasSelection" @click="copySelection">{{ t("terminal.copy") }}</button>
      <button :disabled="!sessionLive" @click="pasteFromClipboard">{{ t("terminal.paste") }}</button>
      <button @click="openSearchFromMenu">{{ t("terminal.search") }}</button>
      <button @click="clearScreen">{{ t("terminal.clear") }}</button>
      <!-- G-17: split this pane (choose a session type next); cc-switch panes
           are a config TUI and do not offer split -->
      <template v-if="!isCcSwitch">
        <span class="sep" />
        <button @click="openSplitPicker('horizontal', ctxMenu.x, ctxMenu.y)">
          {{ t("tabbar.menu.splitH") }}
        </button>
        <button @click="openSplitPicker('vertical', ctxMenu.x, ctxMenu.y)">
          {{ t("tabbar.menu.splitV") }}
        </button>
      </template>
    </div>

    <!-- G-17: choose the session type for the new split pane -->
    <div
      v-if="splitPicker"
      class="ctx-menu split-picker"
      :style="{ left: splitPicker.x + 'px', top: splitPicker.y + 'px' }"
      @contextmenu.prevent
      @click.stop
    >
      <span class="sep" />
      <button v-for="a in AGENTS" :key="a" @click="chooseSplitAgent(a)">
        {{ t(`tabbar.menu.${a}`) }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.terminal {
  height: 100%;
  width: 100%;
  position: relative;
}

/* --- search overlay (top-right, above the terminal) --- */
.search-overlay {
  position: absolute;
  top: 8px;
  right: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px;
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  font-size: 12px;
}
.search-overlay input {
  width: 140px;
  padding: 3px 6px;
  background: var(--surface-hover);
  color: var(--text-2);
  border: none;
  border-radius: 2px;
  outline: none;
}
.search-overlay button {
  padding: 3px 6px;
  background: transparent;
  color: var(--text-2);
  border: none;
  border-radius: 2px;
  cursor: pointer;
}
.search-overlay button:hover {
  background: var(--surface-hover);
}
.search-overlay button.case.active {
  color: var(--success);
}
.search-overlay .result {
  min-width: 42px;
  text-align: center;
  color: var(--text-muted);
}
.search-overlay .result.empty {
  color: var(--error);
}

/* --- context menu --- */
.ctx-menu {
  position: fixed;
  z-index: 20;
  display: flex;
  flex-direction: column;
  min-width: 140px;
  padding: 4px;
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 4px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}
.ctx-menu button {
  padding: 6px 12px;
  text-align: left;
  background: transparent;
  color: var(--text-2);
  border: none;
  border-radius: 2px;
  cursor: pointer;
  font-size: 13px;
}
.ctx-menu button:hover:not(:disabled) {
  background: var(--surface-active);
}
.ctx-menu button:disabled {
  color: var(--text-muted);
  cursor: default;
}
.ctx-menu .sep {
  height: 1px;
  margin: 4px 8px;
  background: var(--surface-hover);
}
</style>
