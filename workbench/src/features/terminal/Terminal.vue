<script setup lang="ts">
/**
 * Terminal component (S1.4): wires the S1.3 PTY data plane to xterm.js.
 *
 * - Opens a session via a Tauri Channel<PtyEvent> (channel created before the
 *   invoke, so no first-screen output is lost).
 * - Output events: base64 bytes -> Uint8Array -> term.write.
 * - onData: UTF-8 encode -> write_session (paste capped backend-side).
 * - ResizeObserver throttled -> fit -> resize_session (05 §9.2).
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Channel } from "@tauri-apps/api/core";
import "@xterm/xterm/css/xterm.css";
import { useRuntimeStore } from "../../stores/runtime";
import { closeSession, openSession, resizeSession, writeSession } from "../../lib/ipc";
import type { PtyEvent } from "../../types";

const container = ref<HTMLDivElement | null>(null);
const store = useRuntimeStore();

let term: Terminal | null = null;
let fit: FitAddon | null = null;
let channel: Channel<PtyEvent> | null = null;
let resizeTimer: number | null = null;
let resizeObserver: ResizeObserver | null = null;
let closed = false;

const AGENT = "bash";

function b64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

function openPty(sessionId: string) {
  channel = new Channel<PtyEvent>();
  channel.onmessage = (ev) => {
    if (!term) return;
    switch (ev.type) {
      case "output":
        term.write(b64ToUint8(ev.bytes));
        break;
      case "exit":
        closed = true;
        term.write(`\r\n\x1b[90m[Session exited: ${ev.reason}${ev.exitCode !== null ? `, code ${ev.exitCode}` : ""}]\x1b[0m\r\n`);
        store.onSessionExited();
        break;
      case "error":
        term.write(`\r\n\x1b[31m[Session error: ${ev.code} ${ev.message}]\x1b[0m\r\n`);
        store.onSessionExited();
        break;
    }
  };
  openSession(store.runtimeId, sessionId, AGENT, channel).catch((e) => {
    term?.write(`\r\n\x1b[31m[open_session failed: ${e?.code ?? e}]\x1b[0m\r\n`);
    store.onSessionExited();
  });
}

function closePty(sid?: string) {
  const target = sid ?? store.sessionId;
  if (target && !closed) {
    closed = true;
    closeSession(target).catch(() => {});
  }
  channel = null;
}

function scheduleResize() {
  if (resizeTimer !== null) return;
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null;
    doResize();
  }, 150);
}

function doResize() {
  if (!term || !fit || closed) return;
  try {
    fit.fit();
    if (store.sessionId) {
      resizeSession(store.sessionId, term.cols, term.rows).catch(() => {});
    }
  } catch {
    /* container not laid out yet */
  }
}

onMounted(() => {
  term = new Terminal({
    fontFamily: "monospace",
    fontSize: 13,
    convertEol: false,
    cursorBlink: true,
  });
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(container.value!);
  term.writeln("AISC Workbench — 输入工作区并点击「启动 Bash」。");
  fit.fit();

  term.onData((data) => {
    if (store.sessionId && !closed) {
      writeSession(store.sessionId, Array.from(new TextEncoder().encode(data))).catch(() => {});
    }
  });

  resizeObserver = new ResizeObserver(scheduleResize);
  if (container.value) resizeObserver.observe(container.value);
  // Also re-fit when the window resizes (ResizeObserver may not fire for it).
  window.addEventListener("resize", scheduleResize);

  watch(
    () => store.sessionId,
    (sid, oldSid) => {
      if (oldSid && sid !== oldSid) closePty(oldSid);
      if (sid) {
        closed = false;
        openPty(sid);
        setTimeout(doResize, 0); // fit after layout settles
      }
    }
  );
});

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect();
  if (resizeTimer !== null) window.clearTimeout(resizeTimer);
  window.removeEventListener("resize", scheduleResize);
  closePty();
  term?.dispose();
  term = null;
  fit = null;
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
