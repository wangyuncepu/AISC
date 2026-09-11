<script setup lang="ts">
/**
 * P2-1 (A2): the one global toast host — body-teleported so no pane's
 * zoom/scroll can clip it. 手测 r2 rulings: BOTTOM-center (the spot the
 * cc-switch switch feedback made familiar) and the stack carries the same
 * ui.font_scale zoom as the app chrome (the teleport escapes App's zoom
 * scope, so the zoom is re-applied HERE on the stack wrapper — position
 * offsets stay unscaled).
 * role="status" (polite live region) per item — errors use role="alert"
 * so SR users hear failures over chatter.
 */
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";
import { useToastStore } from "../stores/toast";
import { useSettingsStore } from "../stores/settings";

const { t } = useI18n();
const store = useToastStore();
const { toasts } = storeToRefs(store);

const settings = useSettingsStore();
// Same source App.vue's uiScale reads — G-01: immediate-effect font scale.
const uiScale = computed(() => settings.doc?.ui.font_scale ?? 1);

function runAction(id: number, run: () => void): void {
  run();
  store.dismiss(id);
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite">
      <div class="toast-stack" :style="{ zoom: uiScale }">
        <TransitionGroup name="toast">
          <p
            v-for="item in toasts"
            :key="item.id"
            class="ui-toast"
            :class="item.kind"
            :role="item.kind === 'error' ? 'alert' : 'status'"
          >
            <span
              v-if="item.kind !== 'progress'"
              class="glyph"
              aria-hidden="true"
            >{{ item.kind === "success" ? "✓" : item.kind === "error" ? "✕" : "ℹ" }}</span>
            <span class="msg">{{ item.message }}</span>
            <button
              v-if="item.action"
              type="button"
              class="toast-action"
              @click="runAction(item.id, item.action!.run)"
            >
              {{ item.action.label }}
            </button>
            <button
              v-if="item.kind !== 'progress'"
              type="button"
              class="toast-close"
              :aria-label="t('common.dismiss')"
              @click="store.dismiss(item.id)"
            >
              ×
            </button>
          </p>
        </TransitionGroup>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  bottom: 18px;
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
  pointer-events: none;
}
.toast-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.ui-toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: var(--space-2) var(--space-5);
  max-width: min(560px, 80vw);
  background: var(--surface-2);
  color: var(--text);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  /* 手测 r2: toast sizes with the UI font scale — md, not the sm a
   * top-bar notification would use. */
  font-size: var(--font-md);
}
.ui-toast .glyph { flex: none; }
.ui-toast.success {
  background: var(--success-bg);
  color: var(--success);
  border-color: var(--success);
}
.ui-toast.success .glyph { color: var(--success); }
.ui-toast.error { border-color: var(--error-fg); }
.ui-toast.error .glyph { color: var(--error-fg); }
/* Live progress cards (切换中… xS): neutral surface, no glyph/close — the
 * completion toast replaces it in place. */
.ui-toast.progress { color: var(--text-2); }
.ui-toast .msg { word-break: break-word; }
.toast-action {
  flex: none;
  border: none;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: var(--radius-sm);
  padding: 2px 10px;
  cursor: pointer;
  font-size: var(--font-sm);
}
.toast-close {
  flex: none;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--font-md);
  line-height: 1;
  padding: 0 2px;
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--duration-normal) var(--ease),
    transform var(--duration-normal) var(--ease);
}
.toast-enter-from { opacity: 0; transform: translateY(8px); }
.toast-leave-to { opacity: 0; }
.toast-move { transition: transform var(--duration-normal) var(--ease); }
</style>
