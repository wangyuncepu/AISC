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
import { shouldSendSize, type TermSize } from "./resizeSync";
import { WORKSPACE_PATH_MIME } from "../../lib/workspaceDnd";
import { containerPathFor, quoteForTerminal } from "./dropPath";
import { resolveRenderer, terminalTheme } from "./renderer";
import { effectiveTheme } from "../../theme";
import { findLeaf } from "../../stores/paneTree";
import { prefersReducedMotion } from "../../lib/accessibility";
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
/** G-17: the session type of this pane's leaf (bash / claude / codex /
 *  cc-switch) — drives TUI-specific behaviors. */
const leafSessionType = computed(
  () => (tab.value ? findLeaf(tab.value.tree, props.paneId)?.sessionType ?? null : null)
);
/** G-17: cc-switch panes are a config TUI - no split offered (user feedback). */
const isCcSwitch = computed(() => leafSessionType.value === "cc-switch");

let term: Terminal | null = null;
let fit: FitAddon | null = null;
let webgl: WebglAddon | null = null;
let searchAddon: SearchAddon | null = null;
let resizeTimer: number | null = null;
let resizeObserver: ResizeObserver | null = null;
// B-05: size-convergence state. `lastConfirmedSize` is the size the PTY
// actually accepted (not merely what fit proposed); `resizeSyncFailed`
// forces the heal tick to retry after a rejected resize_session.
let lastConfirmedSize: TermSize | null = null;
let resizeSyncFailed = false;
let healTimer: number | null = null;

// B-05 手测 2 (narrow-TUI guard): full-screen TUIs (claude/codex/cc-switch)
// render structural garbage below a minimum width; instead of showing the
// wreckage, cover the pane with a "widen the window" hint. The session keeps
// running underneath — widening lifts the overlay and the final WINCH-driven
// redraw lands cleanly. bash wraps fine and is exempt.
const NARROW_TUI_MIN_COLS = 60;
const termCols = ref(80);
const narrowTui = computed(
  () =>
    leafSessionType.value !== null &&
    leafSessionType.value !== "bash" &&
    visible.value &&
    termCols.value < NARROW_TUI_MIN_COLS,
);

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
    // Stage 6 (UX-03): reduced motion zeroes the terminal smooth scroll too.
    smoothScrollDuration: prefersReducedMotion() ? 0 : s?.smooth_scroll_duration,
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

/** Write a batch of base64 chunks in a SINGLE term.write (fewer xterm parses;
 * per-chunk writes make high-throughput output render slowly). */
function writeChunks(chunks: string[]): void {
  if (!term || chunks.length === 0) return;
  const totalB64 = chunks.reduce((n, c) => n + c.length, 0);
  const decoded = new Uint8Array(((totalB64 / 4) | 0) * 3);
  let off = 0;
  for (const b64 of chunks) {
    const u8 = b64ToUint8(b64);
    decoded.set(u8, off);
    off += u8.length;
  }
  term.write(decoded.subarray(0, off));
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
  writeChunks(store.paneStreams[props.paneId] ?? []);
  consumed = store.streamCursor[props.paneId] ?? 0;
  if (visible.value) term.refresh(0, term.rows - 1);
  setTimeout(doResize, 0);
}

/** B-06: settle-once resize. Windows restore/maximize animates the window
 *  through a burst of intermediate sizes; acting on each step reflows the
 *  whole scrollback + forces a full TUI redraw per step (visible squeeze +
 *  flicker, 手测三轮). Reset the timer on every event and do ONE fit+send
 *  after 150ms of quiet — a discrete maximize lands ~150ms later, a drag
 *  snaps once on pause. The 2s heal tick backstops anything missed. */
function scheduleResize(reason: string) {
  if (resizeTimer !== null) window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null;
    if (!visible.value) return;
    doResize(`settle:${reason}`);
  }, 150);
}

/** Named wrapper so removeEventListener stays paired after the reason
 *  parameter was added for the B-05 probe. */
function onWindowResize() {
  scheduleResize("window");
}

function doResize(reason = "tick") {
  if (!visible.value || !term || !fit || !sessionLive.value) {
    // B-05 TEMP probe: a real event that got blocked (not the 2s tick).
    if (reason !== "tick") {
      store.logTerminalProbe(`blocked:${reason}:vis=${visible.value}:live=${sessionLive.value}`);
    }
    return;
  }
  try {
    const before = `${term.cols}x${term.rows}`;
    const boxW = container.value?.clientWidth ?? -1;
    fit.fit();
    termCols.value = term.cols; // narrow-TUI guard tracks the fitted grid
    if (before !== `${term.cols}x${term.rows}`) {
      store.logTerminalProbe(`fit:${reason}:${before}->${term.cols}x${term.rows}:box=${boxW}`);
    }
    const sid = sessionId.value;
    // B-05 (fix F1): only send when the backend session is Running — a
    // Starting/Closing entry makes resize_session fail, which would just
    // noise the sync state. Fitting the xterm side above is still correct.
    if (!sid || pane.value?.sessionState !== "running") return;
    const size: TermSize = { cols: term.cols, rows: term.rows };
    // B-05 手测三轮: never drag a full-screen TUI below its readable floor.
    // claude/codex renderers WEDGE at absurd widths and stop responding to
    // WINCH — after that even maximizing cannot revive them. Below the floor
    // the narrow overlay covers the pane visually while the PTY keeps its
    // last usable size (or the 80-col spawn default). bash wraps fine.
    if (leafSessionType.value !== null && leafSessionType.value !== "bash" && size.cols < NARROW_TUI_MIN_COLS) {
      store.logTerminalProbe(`floor:${reason}:${size.cols}x${size.rows}`);
      return;
    }
    // F5: idempotent skip — nothing to do when the PTY already confirmed
    // this exact grid and the last send succeeded.
    if (!shouldSendSize(lastConfirmedSize, size, resizeSyncFailed)) return;
    store.logTerminalProbe(`send:${reason}:${size.cols}x${size.rows}`);
    resizeSession(sid, size.cols, size.rows)
      .then(() => {
        lastConfirmedSize = size;
        resizeSyncFailed = false;
        store.logTerminalProbe(`ok:${size.cols}x${size.rows}`);
      })
      .catch((err: unknown) => {
        // B-05 (fix F2): a swallowed failure used to leave the PTY stuck at
        // the 80×24 spawn default forever. Record it on the shared timeline
        // (store choke point per the P4.5 layer contract) and let the heal
        // tick retry.
        resizeSyncFailed = true;
        const code =
          err && typeof err === "object" && "code" in err
            ? String((err as { code?: unknown }).code)
            : undefined;
        store.logTerminalResizeError(code);
        store.logTerminalProbe(`fail:${code ?? "unknown"}`);
      });
  } catch (e) {
    /* container not laid out yet */
    store.logTerminalProbe(`throw:${reason}:${String(e)}`);
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

/** Stage 6 (UX-03): open the context menu from the keyboard (Menu key or
 *  Shift+F10) at the terminal centre, then move focus to the first item so
 *  arrows/Tab navigate immediately. Other keys pass through to xterm. */
function onTerminalKeydown(e: KeyboardEvent) {
  if (e.key !== "ContextMenu" && !(e.shiftKey && e.key === "F10")) return;
  e.preventDefault();
  const el = container.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const x = Math.min(r.left + r.width / 2, window.innerWidth - 180);
  const y = Math.min(r.top + r.height / 2, window.innerHeight - 150);
  ctxMenu.value = { x, y };
  window.setTimeout(() => {
    el.querySelector<HTMLElement>(".ctx-menu button:not([disabled])")?.focus();
  }, 0);
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

/** Stage 11 (11d): drop target for a file dragged from the Explorer.
 *
 * Only the controlled workspace-path MIME is accepted (external/OS file
 * drags are ignored — the handler does not preventDefault for them, so the
 * browser keeps its default behaviour). The drop writes the shell-quoted
 * CONTAINER path (`/root/app/...`, D11-15) into the session via the existing
 * writeSession path — no Enter is appended, nothing executes (D11-09), and
 * the terminal regains focus so typing continues after the token. */
const dropActive = ref(false);

function onDragOver(e: DragEvent) {
  if (!e.dataTransfer) return;
  // Array.from: `types` is a DOMStringList on some engines, an array on others.
  if (!Array.from(e.dataTransfer.types).includes(WORKSPACE_PATH_MIME)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  dropActive.value = true;
}

function onDragLeave() {
  dropActive.value = false;
}

async function onDrop(e: DragEvent) {
  e.preventDefault();
  dropActive.value = false;
  const relativePath = e.dataTransfer?.getData(WORKSPACE_PATH_MIME) ?? "";
  const sid = sessionId.value;
  if (!relativePath || !sid || !sessionLive.value) {
    // Refuse quietly: local view message only, the PTY is untouched (02 §4).
    term?.write(`\r\n\x1b[90m${t("terminal.dropRejected")}\x1b[0m\r\n`);
    return;
  }
  const token = quoteForTerminal(containerPathFor(relativePath));
  try {
    await writeSession(sid, Array.from(new TextEncoder().encode(token)));
    term?.focus();
  } catch {
    term?.write(`\r\n\x1b[90m${t("terminal.dropRejected")}\x1b[0m\r\n`);
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
  // 10e (B-08): Shift+Escape is the keyboard exit from the terminal — bare
  // Tab must stay PTY input (completion), so keyboard users need one combo
  // that lifts focus back to the app chrome (the active tab in the bar).
  if (e.shiftKey && !mod && key === "escape") {
    e.preventDefault();
    document.querySelector<HTMLElement>(".tabbar .tab.active .tab-main")?.focus();
    return false;
  }
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

// S1.3: persistent truncation notice (setup-top-level so the template can see
// it; the terminal-flow note below marks the point in the scrollback).
const streamTruncated = computed(() => store.paneStreamMeta[props.paneId]?.truncated ?? false);
const streamTruncatedBytes = computed(
  () => store.paneStreamMeta[props.paneId]?.truncatedBytes ?? 0
);
// Number of chunks this Terminal has written to the xterm; advances by
// streamCursor (not array length, which freezes once the rolling window is
// full). Shared by the stream watcher and rebuildTerminal.
let consumed = 0;

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
  termCols.value = term?.cols ?? 80;

  resizeObserver = new ResizeObserver(() => scheduleResize("observer"));
  if (container.value) resizeObserver.observe(container.value);
  window.addEventListener("resize", onWindowResize);

  // B-05 (fix F1, remount case): a Terminal that mounts onto an
  // ALREADY-running pane (pane restructure remount) gets no state
  // transition, so sync immediately.
  if (pane.value?.sessionState === "running") doResize("mount");

  // B-05 (fix F3): self-heal tick. The size mismatch shows up randomly (no
  // reproducible trigger), so convergence cannot rely on user-driven resize
  // events. While live + visible, re-check every 2s; already converged is a
  // zero-IPC no-op, drift or a failed send triggers one resend.
  healTimer = window.setInterval(() => {
    if (sessionLive.value && visible.value) doResize();
  }, 2000);

  // Re-fit when this tab becomes the active (visible) view. v-show toggles
  // display:none; xterm does not repaint automatically on re-display, which
  // leaves a blank screen while the buffer/session stay intact. Force a full
  // viewport repaint after the re-fit.
  watch(visible, (v) => {
    if (v) {
      setTimeout(() => {
        doResize("show");
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
  // re-anchors past any dropped head. New chunks are written as ONE batch per
  // flush. Remounts never re-open the session.
  watch(
    () => store.streamCursor[props.paneId] ?? 0,
    () => {
      const arr = store.paneStreams[props.paneId] ?? [];
      const total = store.streamCursor[props.paneId] ?? 0;
      const from = computeDisplayFrom(consumed, total, arr.length);
      if (from < arr.length) writeChunks(arr.slice(from));
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
      // B-05 (fix F1): the moment the backend accepts the session, sync the
      // fitted grid to the PTY immediately (bypassing the debounce). Until
      // the first resize lands the PTY runs at the 80×24 spawn default while
      // xterm shows the fitted width — every readline/TUI redraw then lands
      // on the wrong columns (long-input overwrite).
      if (st === "running") doResize("running");
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
  // output is complete. The terminal-flow note marks the point; the fixed
  // banner stays visible because the note scrolls out of view under output.
  watch(
    () => store.paneStreamMeta[props.paneId]?.truncated,
    (truncated) => {
      if (!truncated) return;
      const bytes = store.paneStreamMeta[props.paneId]?.truncatedBytes ?? 0;
      term?.write(
        // dim gray (手测反馈): the notice stays informative but must not read
        // like a warning — truncation under sustained output is normal.
        `\r\n\x1b[90m${t("terminal.outputTruncated", { bytes: formatBytes(bytes) })}\x1b[0m\r\n`
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
  if (healTimer !== null) window.clearInterval(healTimer);
  window.removeEventListener("resize", onWindowResize);
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
    :class="{ 'drop-target': dropActive }"
    @contextmenu="onContextMenu"
    @keydown="onTerminalKeydown"
    @click="onTerminalClick"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- S1.3: fixed, persistent truncation notice (the terminal-flow note
         scrolls away under sustained output). -->
    <div v-if="streamTruncated" class="truncation-banner" role="status">
      {{ t("terminal.outputTruncated", { bytes: formatBytes(streamTruncatedBytes) }) }}
    </div>
    <!-- B-05 手测 2: a full-screen TUI below the minimum width renders
         structural garbage — cover it with a widen-the-window hint instead.
         The session keeps running underneath; widening lifts the overlay
         and the final WINCH redraw lands at the readable size. -->
    <div
      v-if="narrowTui"
      class="narrow-overlay"
      data-testid="narrow-tui-overlay"
      role="status"
    >
      <p class="narrow-title">{{ t("terminal.narrowTui.title") }}</p>
      <p class="narrow-detail">
        {{ t("terminal.narrowTui.detail", { cols: termCols, min: NARROW_TUI_MIN_COLS, agent: leafSessionType }) }}
      </p>
    </div>
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

    <!-- G-11 context menu (10e: unified pop motion) -->
    <Transition name="pop">
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
    </Transition>

    <!-- G-17: choose the session type for the new split pane -->
    <Transition name="pop">
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
    </Transition>
  </div>
</template>

<style scoped>
.terminal {
  height: 100%;
  width: 100%;
  position: relative;
}
/* Stage 11 (11d): lightweight drop-target affordance while a workspace file
 * hovers over this pane (03 §6). */
.terminal.drop-target {
  outline: var(--focus-ring-width) dashed var(--accent);
  outline-offset: calc(-2 * var(--focus-ring-width));
}

/* S1.3: persistent truncation notice pinned to the top edge (does not consume
 * terminal scrollback, so it cannot be pushed out of view).
 * 手测反馈 (2026-08-20): truncation under sustained output is NORMAL — the
 * notice must not read like a warning. Small muted corner chip, no bar. */
.truncation-banner {
  position: absolute;
  top: 4px;
  right: 10px;
  z-index: var(--z-overlay);
  padding: 1px 8px;
  font-size: var(--font-xs);
  color: var(--text-muted);
  opacity: 0.55;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-full);
  pointer-events: none;
}

/* B-05 手测 2: opaque cover for a TUI below its minimum readable width. */
.narrow-overlay {
  position: absolute;
  inset: 0;
  z-index: var(--z-overlay);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  text-align: center;
  background: var(--bg);
}
.narrow-title {
  margin: 0;
  font-size: var(--font-md);
  font-weight: 600;
  color: var(--text);
}
.narrow-detail {
  margin: 0;
  max-width: 40ch;
  font-size: var(--font-sm);
  color: var(--text-muted);
}

/* --- search overlay (top-right, above the terminal) --- */
.search-overlay {
  position: absolute;
  top: 8px;
  right: 12px;
  z-index: var(--z-menu);
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  font-size: var(--font-sm);
}
.search-overlay input {
  width: 140px;
  padding: 3px 6px;
  background: var(--surface-hover);
  color: var(--text-2);
  border: none;
  border-radius: var(--radius-sm);
  outline: none;
}
.search-overlay button {
  padding: 3px 6px;
  background: transparent;
  color: var(--text-2);
  border: none;
  border-radius: var(--radius-sm);
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
  z-index: var(--z-overlay);
  display: flex;
  flex-direction: column;
  min-width: 140px;
  padding: 4px;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-2);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
}
.ctx-menu button {
  padding: 6px 12px;
  text-align: left;
  background: transparent;
  color: var(--text-2);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--font-md);
  transition: background-color var(--duration-normal) var(--ease);
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
