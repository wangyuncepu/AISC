<script setup lang="ts">
/**
 * Terminal component (S1.1 scaffold).
 *
 * Mounts an xterm.js instance + FitAddon. Real PTY byte streaming
 * (portable-pty via Tauri channels, per contract §九.2) lands in S1.3; this
 * scaffold only proves the terminal surface renders + fits.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const container = ref<HTMLDivElement | null>(null);
let term: Terminal | null = null;
let fit: FitAddon | null = null;

onMounted(() => {
  term = new Terminal({ fontFamily: "monospace", fontSize: 13 });
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(container.value!);
  fit.fit();
  term.writeln("AISC Workbench terminal ready.");
  term.writeln("(PTY wiring arrives in S1.3; this is the scaffold.)");
});

onBeforeUnmount(() => {
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
