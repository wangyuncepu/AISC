<script setup lang="ts">
/**
 * Minimal Workbench shell (S1.1 scaffold).
 *
 * Just a top bar + terminal area. The full UI (workspace picker, "启动 Bash",
 * "停止 Runtime", session tabs) is S1.4; this scaffold wires xterm + pinia and
 * proves the Tauri+Vue app renders.
 */
import Terminal from "./features/terminal/Terminal.vue";
</script>

<template>
  <div class="app">
    <header class="topbar">AISC Workbench</header>
    <main class="terminal-area">
      <Terminal />
    </main>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.topbar {
  padding: 6px 12px;
  background: #252526;
  color: #ccc;
  font-size: 13px;
  border-bottom: 1px solid #333;
}
.terminal-area {
  flex: 1;
  min-height: 0;
  padding: 4px;
  background: #1e1e1e;
}
</style>
