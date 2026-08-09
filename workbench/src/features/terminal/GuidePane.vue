<script setup lang="ts">
/**
 * GuidePane (G-08, Step 5c / A-G08-2): shown for a claude/codex tab whose
 * provider is not configured. No open_session is called for guide tabs;
 * the pane offers a retry (re-query the provider) and a shortcut to open
 * cc-switch (activate an existing tab or create one). Full G-12 copy and
 * presentation land in Step 8.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();
const props = defineProps<{ tabId: string }>();

const tab = computed(() => store.tabs.find((x) => x.tabId === props.tabId));
const agent = computed(() => tab.value?.agent as "claude" | "codex" | undefined);

async function retry() {
  if (!agent.value) return;
  await store.loadProviderStatus(agent.value);
  const st = store.providerStatuses[agent.value];
  if (st && st.auth_status !== "not_configured") {
    store.openTab(props.tabId); // configured now - open the session
  }
}

function openCcSwitch() {
  const existing = store.tabs.find((x) => x.agent === "cc-switch");
  if (existing) store.activateTab(existing.tabId);
  else store.createTab("cc-switch");
}
</script>

<template>
  <div class="guide">
    <h3>{{ t("guide.title", { agent: agent ?? "" }) }}</h3>
    <p class="desc">{{ t("guide.desc") }}</p>
    <div class="actions">
      <button class="primary" @click="retry">{{ t("guide.retry") }}</button>
      <button @click="openCcSwitch">{{ t("guide.openCcSwitch") }}</button>
    </div>
  </div>
</template>

<style scoped>
.guide {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #ccc;
}
h3 { margin: 0; font-size: 15px; color: #ddd; }
.desc { font-size: 13px; color: #888; margin: 0; }
.actions { display: flex; gap: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button.primary { background: #0e639c; border-color: #0e639c; }
</style>
