<script setup lang="ts">
/**
 * v2.1.7 S2 (⑧): a history entry whose path no longer exists on disk.
 * Offers the NON-destructive "clear the record" action only — it drops the
 * history entry and touches nothing else (the forget transaction stays a
 * separate, explicitly heavier flow). Default focus: cancel (A-2172B).
 */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useDialogA11y } from "../../composables/useDialogA11y";

defineProps<{ path: string }>();
const emit = defineEmits<{ (e: "close"): void; (e: "clear"): void }>();

const { t } = useI18n();
const panel = ref<HTMLElement | null>(null);
const cancelBtn = ref<HTMLButtonElement | null>(null);
useDialogA11y(panel, () => emit("close"));
onMounted(() => cancelBtn.value?.focus());
</script>

<template>
  <div class="overlay" @mousedown.self="emit('close')">
    <section
      ref="panel"
      class="panel"
      role="dialog"
      aria-modal="true"
      :aria-label="t('picker.invalidTitle')"
      tabindex="-1"
    >
      <header class="head">
        <h2>{{ t("picker.invalidTitle") }}</h2>
      </header>
      <div class="body">
        <p>{{ t("picker.invalidBody") }}</p>
        <p class="path" :title="path">{{ path }}</p>
      </div>
      <footer class="foot">
        <button ref="cancelBtn" class="ui-button" @click="emit('close')">
          {{ t("picker.cancel") }}
        </button>
        <button class="ui-button" @click="emit('clear')">
          {{ t("picker.invalidClear") }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 90;
  background: var(--scrim);
  display: flex; align-items: center; justify-content: center;
}
.panel {
  width: 440px; max-width: 90vw;
  background: var(--surface); color: var(--text);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  display: flex; flex-direction: column;
}
.head { padding: var(--space-3) var(--space-4) 0; }
.head h2 { margin: 0; font-size: var(--font-lg); font-weight: 600; }
.body { padding: var(--space-2) var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); }
.foot { padding: var(--space-3) var(--space-4); display: flex; justify-content: flex-end; gap: var(--space-2); }
.path {
  margin: 0; font-family: var(--font-mono); font-size: var(--font-xs);
  color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.panel:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
</style>
