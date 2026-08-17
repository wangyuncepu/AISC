<script setup lang="ts">
/**
 * Settings modal (Step 3; IDEA-1 S2): dialog chrome (overlay, focus trap,
 * header) around the shared SettingsForm. In the ready workspace the Settings
 * TAB is the primary surface; this dialog remains for pre-ready states
 * (blocked/error/picker/...) where there is no tab bar yet.
 */
import { nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useSettingsStore } from "../../stores/settings";
import { useDialogA11y } from "../../composables/useDialogA11y";
import SettingsForm from "./SettingsForm.vue";

const { t } = useI18n();
const store = useSettingsStore();
const emit = defineEmits<{ close: [] }>();

const panel = ref<HTMLElement | null>(null);

// Stage 6 (UX-03): focus trap + Escape + opener restore.
useDialogA11y(panel, () => emit("close"));

onMounted(async () => {
  if (!store.loaded) await store.load();
  await nextTick();
  // Initial focus into the dialog (keyboard reachable, A-G01-1); Tab then
  // walks the controls.
  panel.value?.focus();
});

function onOverlayDown(e: MouseEvent) {
  if (e.target === e.currentTarget) emit("close");
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayDown">
    <section ref="panel" class="panel" role="dialog" aria-modal="true" :aria-label="t('settings.title')" tabindex="-1">
      <header class="head">
        <h2>{{ t("settings.title") }}</h2>
        <span v-if="store.dirty" class="chip dirty">{{ t("settings.dirty") }}</span>
        <span v-if="store.saveState === 'saved'" class="chip saved">{{ t("settings.saved") }}</span>
      </header>
      <SettingsForm mode="dialog" @close="emit('close')" />
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog);
}
.panel {
  width: 560px; max-width: 92vw; max-height: 84vh; overflow: auto;
  background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); border-radius: var(--radius-lg);
  outline: none; display: flex; flex-direction: column;
}
.head {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  /* Small windows scroll the panel body; keep the header (with the saved
     confirmation chip) and the footer (Save button) always in view. */
  position: sticky; top: 0; z-index: 2; background: var(--surface);
}
.head h2 { margin: 0; font-size: 15px; color: var(--text-2); }
.chip { font-size: var(--font-xs); padding: 2px 8px; border-radius: 10px; }
.chip.dirty { background: var(--warn-bg); color: var(--warn-fg); }
.chip.saved { background: var(--success-bg); color: var(--success); }
</style>
