<script setup lang="ts">
/**
 * GuidePane (G-12, Step 8; 04-observability.md §三): the single guide banner
 * lives at the TOP of a claude/codex tab whose provider needs attention -
 * never in the sidebar (auth is Session-specific, not Runtime-global).
 *
 * Auth-state behavior (04 §三 rule table):
 * - not_configured / login_required: guide state, button opens the Provider
 *   management tab (IDEA-4 round 4: the TUI is no longer the entry point)
 *   (activates an existing tab or creates one); retry starts the session
 *   once the provider reports configured.
 * - unknown / capability missing: "无法确认" copy, retry; never presented as
 *   "未配置", never reads any secret.
 * No open_session is called for guide tabs (A-G12-1).
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { AGENTS } from "../../stores/tabLayout";
import { findLeaf } from "../../stores/paneTree";
import type { LaunchAgent } from "../../types";

const { t } = useI18n();
const store = useRuntimeStore();
const props = defineProps<{ tabId: string; paneId: string }>();

const tab = computed(() => store.tabs.find((x) => x.tabId === props.tabId));
/** This pane's live record (sessionState drives the auto-open watch). */
const pane = computed(() => tab.value?.panes?.[props.paneId] ?? null);
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

/** Manual-test fix (2026-09-06): the guide copy PROMISES「配置 Provider 后会
 * 自动打开会话」— honor it when the poller flips this pane's agent to
 * configured while the pane still sits in guide (the cold-boot transient
 * not_configured case; without this the user had to click 启动会话 by hand
 * after the wait). Same action as retry()'s success path. */
watch([auth, pane], ([a, p]) => {
  if (a !== "configured" || !p || p.sessionState !== "guide") return;
  store.setActivePane(props.tabId, props.paneId);
  store.openTab(props.tabId);
});

function openProviderTab() {
  store.openCcSwitchUiTab();
}

/** G-12 (user request 2026-08-10): official-account login goes straight into
 * the codex TUI - the session opens and the TUI runs its own login flow. */
function loginOfficial() {
  store.openTab(props.tabId);
}

// --- G-17: guide panes (claude/codex) offer split via right-click too ---
const menu = ref<{ x: number; y: number } | null>(null);
const splitPicker = ref<{ x: number; y: number; axis: "horizontal" | "vertical" } | null>(null);

function onContext(e: MouseEvent) {
  e.preventDefault();
  const x = Math.min(e.clientX, window.innerWidth - 180);
  const y = Math.min(e.clientY, window.innerHeight - 150);
  menu.value = { x, y };
}
function openSplit(axis: "horizontal" | "vertical") {
  if (!menu.value) return;
  splitPicker.value = { x: menu.value.x, y: menu.value.y, axis };
  menu.value = null;
}
function pickAgent(agent: LaunchAgent) {
  const axis = splitPicker.value?.axis ?? "horizontal";
  splitPicker.value = null;
  store.splitTabPane(props.tabId, axis, agent, true, props.paneId);
}
function closeMenus() {
  menu.value = null;
  splitPicker.value = null;
}
</script>

<template>
  <div class="guide" @contextmenu.prevent="onContext">
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
          <button class="primary" @click="openProviderTab">{{ t("guide.openProviderTab") }}</button>
        </template>
      </div>
    </div>
    <div class="hint">{{ desc }}</div>

    <!-- G-17: right-click split (guide panes have no xterm context menu) -->
    <div
      v-if="menu"
      class="ctx-menu"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      @contextmenu.prevent
      @click.stop
    >
      <button @click="openSplit('horizontal')">{{ t("tabbar.menu.splitH") }}</button>
      <button @click="openSplit('vertical')">{{ t("tabbar.menu.splitV") }}</button>
    </div>
    <div
      v-if="splitPicker"
      class="ctx-menu"
      :style="{ left: splitPicker.x + 'px', top: splitPicker.y + 'px' }"
      @contextmenu.prevent
      @click.stop
    >
      <button v-for="a in AGENTS" :key="a" @click="pickAgent(a)">{{ t(`tabbar.menu.${a}`) }}</button>
    </div>
    <div v-if="menu || splitPicker" class="ctx-backdrop" @click="closeMenus" @contextmenu.prevent="closeMenus" />
  </div>
</template>

<style scoped>
.guide {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  color: var(--text-2);
}
.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  background: var(--warn-bg);
  color: var(--warn-fg);
  border: 1px solid var(--warn-border);
}
.banner[data-auth="login_required"] { background: var(--warn-bg); color: var(--warn-fg); }
.banner[data-auth="not_configured"] { background: var(--error-bg); color: var(--error-fg); }
.banner[data-auth="unknown"] { background: var(--info-bg); color: var(--info); }
.icon { font-size: var(--font-base); }
.text { font-size: var(--font-md); font-weight: 500; }
.actions { margin-left: auto; display: flex; gap: 8px; }
.hint { font-size: var(--font-sm); color: var(--text-muted); }
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); color: var(--text-2);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-3); font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
button.primary { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
.ctx-backdrop {
  position: fixed; inset: 0; z-index: calc(var(--z-overlay) - 2);
}
.ctx-menu {
  position: fixed; z-index: var(--z-overlay);
  display: flex; flex-direction: column; min-width: 140px; padding: 4px;
  background: var(--surface-2); border: var(--border-w) solid var(--border-2); border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
}
.ctx-menu button {
  background: transparent; color: var(--text-2); border: none; border-radius: var(--radius-sm);
  text-align: left; padding: 6px 12px; cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease);
}
.ctx-menu button:hover { background: var(--surface-active); color: var(--text); }
</style>
