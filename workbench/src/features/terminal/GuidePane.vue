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
import { findLeaf } from "../../stores/paneTree";

const { t } = useI18n();
const store = useRuntimeStore();
const props = defineProps<{ tabId: string; paneId: string }>();

const tab = computed(() => store.tabs.find((x) => x.tabId === props.tabId));
const agent = computed(() => {
  const t2 = tab.value;
  if (!t2) return undefined;
  return findLeaf(t2.tree, props.paneId)?.sessionType as "claude" | "codex" | undefined;
});
const auth = computed(() => {
  if (!agent.value) return "unknown";
  return store.providerStatuses[agent.value]?.auth_status ?? "unknown";
});

const TITLE_KEY: Record<string, string> = {
  not_configured: "guide.title.notConfigured",
  login_required: "guide.title.loginRequired",
  unknown: "guide.title.unknown",
};
const configured = computed(() => auth.value === "configured");
const title = computed(() => {
  if (configured.value) return t("guide.titleConfigured", { agent: agent.value ?? "" });
  return t(TITLE_KEY[auth.value] ?? "guide.title.unknown", { agent: agent.value ?? "" });
});
const desc = computed(() => {
  if (configured.value) return t("guide.descConfigured");
  return auth.value === "unknown" ? t("guide.descUnknown") : t("guide.desc");
});

async function retry() {
  if (!agent.value) return;
  await store.loadProviderStatus(agent.value);
  const st = store.providerStatuses[agent.value];
  if (st && st.auth_status === "configured") {
    // Configured now - make this pane active and start its session.
    store.setActivePane(props.tabId, props.paneId);
    store.openTab(props.tabId);
  }
}

function openCcSwitch() {
  store.openCcSwitch();
}

/** G-12 (user request 2026-08-10): official-account login goes straight into
 * the codex TUI - the session opens and the TUI runs its own login flow. */
function loginOfficial() {
  store.openTab(props.tabId);
}
</script>

<template>
  <div class="guide">
    <div class="banner" :data-auth="auth">
      <span class="icon" aria-hidden="true">⚠</span>
      <span class="text">{{ title }}</span>
      <div class="actions">
        <template v-if="configured">
          <!-- Provider configured while the tab is in guide state: offer the
               explicit start (observed 2026-08-10: the stale guide copy kept
               showing 未配置 with no way forward). -->
          <button class="primary" @click="store.openTab(props.tabId)">{{ t("guide.startSession") }}</button>
        </template>
        <template v-else>
          <button @click="retry">{{ t("guide.retry") }}</button>
          <!-- Official TUI login is available for both login_required and
               not_configured (codex can log in directly regardless of proxy). -->
          <button v-if="auth === 'login_required' || auth === 'not_configured'" @click="loginOfficial">{{ t("guide.loginOfficial") }}</button>
          <button class="primary" @click="openCcSwitch">{{ t("guide.openCcSwitch") }}</button>
        </template>
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
