<script setup lang="ts">
/**
 * IDEA-1 S2: the Settings tab pane. Non-modal sibling of the terminal panes:
 * the shared SettingsForm fills the terminal area; closing happens via the
 * tab × (TabBar), which also reverts unsaved edits. `close` from the form
 * (e.g. 重新打开设置向导) closes the tab the same way.
 */
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { useSettingsStore } from "../../stores/settings";
import SettingsForm from "./SettingsForm.vue";

const { t } = useI18n();
const runtime = useRuntimeStore();
const settings = useSettingsStore();

function closeTab() {
  // Same contract as the dialog's Cancel: unsaved edits revert to disk state.
  settings.cancel();
  runtime.closeSettingsTab();
}
</script>

<template>
  <section class="settings-tab" :aria-label="t('settings.title')">
    <SettingsForm mode="tab" @close="closeTab" />
  </section>
</template>

<style scoped>
.settings-tab {
  flex: 1; min-height: 0; min-width: 0;
  display: flex; flex-direction: column;
  background: var(--surface);
  overflow: auto;
}
</style>
