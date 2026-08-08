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
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Channel } from "@tauri-apps/api/core";
import "@xterm/xterm/css/xterm.css";
import { useRuntimeStore } from "../../stores/runtime";
import { closeSession, openSession, resizeSession, writeSession } from "../../lib/ipc";
import type { PtyEvent } from "../../types";

const props = defineProps<{ tabId: string }>();
const store = useRuntimeStore();

const container = ref<HTMLDivElement | null>(null);
const tab = computed(() => store.tabs.find((t) => t.tabId === props.tabId));
const sessionId = computed(() => tab.value?.sessionId ?? null);
const visible = computed(() => store.activeTabId === props.tabId);

let term: Terminal | null = null;
let fit: FitAddon | null = null;
let channel: Channel<PtyEvent> | null = null;
let resizeTimer: number | null = null;
let resizeObserver: ResizeObserver | null = null;
let closed = false;

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
        term.write(
          `\r\n\x1b[90m[Session exited: ${ev.reason}${ev.exitCode !== null ? `, code ${ev.exitCode}` : ""}]\x1b[0m\r\n`
        );
        store.onTabSessionExit(props.tabId, ev.reason, ev.exitCode);
        break;
      case "error":
        term.write(`\r\n\x1b[31m[Session error: ${ev.code} ${ev.message}]\x1b[0m\r\n`);
        store.onTabOpenFail(props.tabId);
        break;
    }
  };
  openSession(store.runtimeId, sid, agent, channel)
    .then(() => store.onTabOpenOk(props.tabId))
    .catch((e) => {
      term?.write(`\r\n\x1b[31m[open_session failed: ${e?.code ?? e}]\x1b[0m\r\n`);
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
    const sid = sessionId.value;
    if (sid) resizeSession(sid, term.cols, term.rows).catch(() => {});
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
  term.writeln("AISC Workbench 终端就绪。");
  fit.fit();

  term.onData((data) => {
    const sid = sessionId.value;
    if (sid && !closed) {
      writeSession(sid, Array.from(new TextEncoder().encode(data))).catch(() => {});
    }
  });

  resizeObserver = new ResizeObserver(scheduleResize);
  if (container.value) resizeObserver.observe(container.value);
  window.addEventListener("resize", scheduleResize);

  // Re-fit when this tab becomes the active (visible) view.
  watch(visible, (v) => {
    if (v) setTimeout(doResize, 0);
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
