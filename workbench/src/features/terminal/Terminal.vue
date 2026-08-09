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
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Terminal, type ITerminalOptions } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { Channel } from "@tauri-apps/api/core";
import "@xterm/xterm/css/xterm.css";
import { useRuntimeStore } from "../../stores/runtime";
import { useSettingsStore } from "../../stores/settings";
import { closeSession, openSession, resizeSession, writeSession } from "../../lib/ipc";
import { resolveRenderer, TERMINAL_THEME } from "./renderer";
import type { PtyEvent } from "../../types";

const { t } = useI18n();
const props = defineProps<{ tabId: string }>();
const store = useRuntimeStore();
const settingsStore = useSettingsStore();

const container = ref<HTMLDivElement | null>(null);
const tab = computed(() => store.tabs.find((t) => t.tabId === props.tabId));
const sessionId = computed(() => tab.value?.sessionId ?? null);
const visible = computed(() => store.activeTabId === props.tabId);

let term: Terminal | null = null;
let fit: FitAddon | null = null;
let webgl: WebglAddon | null = null;
let channel: Channel<PtyEvent> | null = null;
let resizeTimer: number | null = null;
let resizeObserver: ResizeObserver | null = null;
let closed = false;

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
    theme: TERMINAL_THEME,
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

function onTermData(data: string) {
  const sid = sessionId.value;
  if (sid && !closed) {
    writeSession(sid, Array.from(new TextEncoder().encode(data))).catch(() => {});
  }
}

/** G-06 (A-G06-3): rebuild the Terminal view in place for renderer/font-family
 * changes. The session_id, PTY child and event channel stay untouched (the
 * channel callbacks close over the module-level `term` binding); the old
 * instance (and its addons/listeners) is disposed, so nothing accumulates. */
function rebuildTerminal() {
  const host = container.value;
  const sid = sessionId.value;
  if (!host || !term) return;
  term.dispose(); // also disposes loaded addons (webgl/fit)
  webgl = null;
  term = new Terminal(terminalOptions());
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(host);
  term.writeln(t("terminal.welcome"));
  term.onData(onTermData);
  mountWebgl();
  if (sid && !closed) {
    // Keep the existing channel; the PTY must NOT be reopened.
    setTimeout(doResize, 0);
  }
  if (visible.value) term.refresh(0, term.rows - 1);
}

function b64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

function openPty(sid: string) {
  const agent = tab.value?.agent;
  if (!agent || !store.runtimeId) return;
  channel = new Channel<PtyEvent>();
  channel.onmessage = (ev) => {
    if (!term) return;
    switch (ev.type) {
      case "output":
        term.write(b64ToUint8(ev.bytes));
        break;
      case "exit":
        closed = true;
        // G-09: Workbench-written exit helper text follows the locale
        // (A-G09-4); raw PTY bytes are never touched.
        term.write(
          `\r\n\x1b[90m[${t("terminal.exited")}: ${ev.reason}${ev.exitCode !== null ? `, code ${ev.exitCode}` : ""}]\x1b[0m\r\n`
        );
        store.onTabSessionExit(props.tabId, ev.reason, ev.exitCode);
        break;
      case "error":
        term.write(
          `\r\n\x1b[31m${t("terminal.sessionError", { code: ev.code, message: ev.message })}\x1b[0m\r\n`
        );
        store.onTabOpenFail(props.tabId);
        break;
    }
  };
  openSession(store.runtimeId, sid, agent, store.workspace.trim(), channel)
    .then(() => store.onTabOpenOk(props.tabId))
    .catch((e) => {
      term?.write(
        `\r\n\x1b[31m${t("terminal.openFailed", { code: e?.code ?? e })}\x1b[0m\r\n`
      );
      store.onTabOpenFail(props.tabId);
    });
}

function closePty(sid?: string) {
  const target = sid ?? sessionId.value;
  if (target && !closed) {
    closed = true;
    closeSession(target).catch(() => {});
  }
  channel = null;
}

function scheduleResize() {
  if (!visible.value || resizeTimer !== null) return;
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null;
    doResize();
  }, 150);
}

function doResize() {
  if (!visible.value || !term || !fit || closed) return;
  try {
    fit.fit();
    const sid = sessionId.value;
    if (sid) resizeSession(sid, term.cols, term.rows).catch(() => {});
  } catch {
    /* container not laid out yet */
  }
}

onMounted(() => {
  term = new Terminal(terminalOptions());
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(container.value!);
  term.writeln(t("terminal.welcome"));
  term.onData(onTermData);
  mountWebgl();
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

  watch(
    sessionId,
    (sid, oldSid) => {
      if (oldSid && sid !== oldSid) closePty(oldSid);
      if (sid) {
        closed = false;
        openPty(sid);
        setTimeout(doResize, 0); // fit after layout settles
      }
    },
    { immediate: true }
  );
});

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
  closePty();
  term?.dispose();
  term = null;
  fit = null;
  webgl = null;
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
  <div ref="container" class="terminal"></div>
</template>

<style scoped>
.terminal {
  height: 100%;
  width: 100%;
}
</style>
