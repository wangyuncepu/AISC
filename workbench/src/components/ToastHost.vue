<script setup lang="ts">
/**
 * P2-1 (A2): the one global toast host — body-teleported so no pane's
 * zoom/scroll can clip it (the property that made cc-switch's local toast
 * correct; the scope is now global). Stacks top-center, TransitionGroup
 * motion, role="status" (polite live region) per item — errors use
 * role="alert" so SR users hear failures over chatter.
 */
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";
import { useToastStore } from "../stores/toast";

const { t } = useI18n();
const store = useToastStore();
const { toasts } = storeToRefs(store);

function runAction(id: number, run: () => void): void {
  run();
  store.dismiss(id);
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite">
      <TransitionGroup name="toast">
        <p
          v-for="item in toasts"
          :key="item.id"
          class="ui-toast"
          :class="item.kind"
          :role="item.kind === 'error' ? 'alert' : 'status'"
        >
          <span class="glyph" aria-hidden="true">{{
            item.kind === "success" ? "✓" : item.kind === "error" ? "✕" : "ℹ"
          }}</span>
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
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}
.ui-toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 12px;
  max-width: min(560px, 80vw);
  background: var(--surface-2);
  color: var(--text);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  font-size: var(--font-sm);
}
.ui-toast .glyph { flex: none; }
.ui-toast.success .glyph { color: var(--success); }
.ui-toast.error .glyph { color: var(--error-fg); }
.ui-toast .msg { word-break: break-word; }
.ui-toast.error { border-color: var(--error-fg); }
.toast-action {
  flex: none;
  border: none;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: var(--radius-sm);
  padding: 2px 10px;
  cursor: pointer;
  font-size: var(--font-xs);
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
.toast-enter-from { opacity: 0; transform: translateY(-8px); }
.toast-leave-to { opacity: 0; }
.toast-move { transition: transform var(--duration-normal) var(--ease); }
</style>
