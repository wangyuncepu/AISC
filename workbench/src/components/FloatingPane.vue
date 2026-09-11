<script setup lang="ts">
/**
 * W1 (shell-redesign): the VS Code-style FLOATING pane host — settings and
 * the data dashboard open as floating panels over the workspace (scrim +
 * centered panel + Esc/backdrop/× close), not as workspace-strip tabs.
 * Same shape as DoctorDialog; the body rides the default slot.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

defineProps<{ title: string; wide?: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();
const { t } = useI18n();
const paneRef = ref<HTMLElement | null>(null);

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    emit("close");
  }
}

onMounted(() => {
  void nextTick(() => paneRef.value?.focus({ preventScroll: true }));
  window.addEventListener("keydown", onKeydown, { capture: true });
});
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown, { capture: true }));
</script>

<template>
  <Teleport to="body">
    <div class="float-backdrop" @mousedown.self="emit('close')">
      <div
        ref="paneRef"
        class="float-pane"
        :class="{ wide }"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header class="float-head">
          <h2>{{ title }}</h2>
          <span class="spacer" />
          <button
            type="button"
            class="float-close"
            :aria-label="t('common.dismiss')"
            @click="emit('close')"
          >×</button>
        </header>
        <div class="float-body">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.float-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-dialog);
  background: var(--scrim);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4vh 4vw;
}
.float-pane {
  display: flex;
  flex-direction: column;
  width: min(720px, 92vw);
  max-height: 88vh;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-2);
  overflow: hidden;
}
.float-pane.wide { width: min(960px, 94vw); }
.float-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: var(--space-2) var(--space-3);
  border-bottom: var(--border-w) solid var(--border);
}
.float-head h2 { margin: 0; font-size: var(--font-md); }
.spacer { flex: 1; }
.float-close {
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: var(--font-lg);
  cursor: pointer;
  line-height: 1;
}
.float-close:hover { color: var(--text); }
.float-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-3);
}
</style>
