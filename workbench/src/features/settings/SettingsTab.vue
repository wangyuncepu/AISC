<script setup lang="ts">
/**
 * IDEA-1 S2 → IDEA-3 (3d): the Settings pane, now a WORKSPACE-layer tab (the
 * strip's sentinel) instead of a session tab. The shared SettingsForm fills
 * the content area; closing happens via the chip × / Ctrl+,, which also
 * reverts unsaved edits. `close` from the form (e.g. 重新打开设置向导)
 * closes the tab the same way.
 */
import { useI18n } from "vue-i18n";
import { useWorkspacesStore } from "../../stores/workspaces";
import { useSettingsStore } from "../../stores/settings";
import SettingsForm from "./SettingsForm.vue";

const { t } = useI18n();
const workspaces = useWorkspacesStore();
const settings = useSettingsStore();

function closeTab() {
  // Same contract as the retired dialog's Cancel: unsaved edits revert.
  settings.cancel();
  workspaces.closeSettingsTab();
}
</script>

<template>
  <section class="settings-tab" :aria-label="t('settings.title')">
    <SettingsForm @close="closeTab" />
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
