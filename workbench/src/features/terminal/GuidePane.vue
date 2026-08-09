<script setup lang="ts">
/**
 * GuidePane (G-12, Step 8; 04-observability.md §三): the single guide banner
 * lives at the TOP of a claude/codex tab whose provider needs attention -
 * never in the sidebar (auth is Session-specific, not Runtime-global).
 *
 * Auth-state behavior (04 §三 rule table):
 * - not_configured / login_required: guide state, button opens cc-switch
 *   (activates an existing tab or creates one); retry starts the session
 *   once the provider reports configured.
 * - unknown / capability missing: "无法确认" copy, retry; never presented as
 *   "未配置", never reads any secret.
 * No open_session is called for guide tabs (A-G12-1).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();
const props = defineProps<{ tabId: string }>();

const tab = computed(() => store.tabs.find((x) => x.tabId === props.tabId));
const agent = computed(() => tab.value?.agent as "claude" | "codex" | undefined);
const auth = computed(() => {
  if (!agent.value) return "unknown";
  return store.providerStatuses[agent.value]?.auth_status ?? "unknown";
});

const TITLE_KEY: Record<string, string> = {
  not_configured: "guide.title.notConfigured",
  login_required: "guide.title.loginRequired",
  unknown: "guide.title.unknown",
};
const title = computed(() =>
  t(TITLE_KEY[auth.value] ?? "guide.title.unknown", { agent: agent.value ?? "" })
);
const desc = computed(() =>
  auth.value === "unknown" ? t("guide.descUnknown") : t("guide.desc")
);

async function retry() {
  if (!agent.value) return;
  await store.loadProviderStatus(agent.value);
  const st = store.providerStatuses[agent.value];
  if (st && st.auth_status === "configured") {
    store.openTab(props.tabId); // configured now - start the session
  }
}

function openCcSwitch() {
  store.openCcSwitch();
}
</script>

<template>
  <div class="guide">
    <div class="banner" :data-auth="auth">
      <span class="icon" aria-hidden="true">⚠</span>
      <span class="text">{{ title }}</span>
      <div class="actions">
        <button @click="retry">{{ t("guide.retry") }}</button>
        <button class="primary" @click="openCcSwitch">{{ t("guide.openCcSwitch") }}</button>
      </div>
    </div>
    <div class="hint">{{ desc }}</div>
  </div>
</template>

<style scoped>
.guide {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  color: #ccc;
}
.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 4px;
  background: #3a3220;
  color: #e0c97a;
  border: 1px solid #55482a;
}
.banner[data-auth="login_required"] { background: #3a3220; color: #e0c97a; }
.banner[data-auth="not_configured"] { background: #3a2a2a; color: #e0b0b0; }
.banner[data-auth="unknown"] { background: #2d2d3a; color: #b0b0e0; }
.icon { font-size: 14px; }
.text { font-size: 13px; font-weight: 500; }
.actions { margin-left: auto; display: flex; gap: 8px; }
.hint { font-size: 12px; color: #888; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 4px 12px; font-size: 12px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button.primary { background: #0e639c; border-color: #0e639c; }
</style>
