<script setup lang="ts">
/**
 * Stage 8e (CS-05/06): the cc-switch Provider UI tab.
 *
 * Renders the secret-free `aisc.cc-switch-provider/v1` snapshot for the
 * running runtime (claude|codex toggle), with the minimal management loop:
 * simple add (preset + key), custom add, edit (fields + optional key
 * rotation), delete (confirm). Secrets live ONLY in transient form refs —
 * submitted once via the stdin channel and cleared; nothing is persisted,
 * logged, or stored in browser storage (04 §Security, adapted to the Tauri
 * IPC channel per D8-13).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useRuntimeStore } from "../../stores/runtime";
import { useCcSwitchUiStore } from "../../stores/ccSwitchUi";
import type { CcSwitchProvider, CcSwitchRequest } from "../../types";

const props = withDefaults(defineProps<{ visible?: boolean }>(), { visible: true });

const { t } = useI18n();
const store = useRuntimeStore();
// Layer contract (F-A01): all ipc fact commands live in the store.
const ui = useCcSwitchUiStore();
// storeToRefs keeps the reactive link (plain destructuring would break it).
import ProviderEditPage from "./ProviderEditPage.vue";
import ProviderCard from "./ProviderCard.vue";
const { agent, providers, loading, busyOp, error } = storeToRefs(ui);

// PP (D-12): the dedicated editor view replaces the popover workflow.
// `undefined` = list view; `null` = add; a provider = edit.
const editTarget = ref<CcSwitchProvider | null | undefined>(undefined);
function openEditPage(p: CcSwitchProvider): void {
  editTarget.value = p;
}
function openAddPage(): void {
  editTarget.value = null;
}
function closeEditPage(): void {
  editTarget.value = undefined;
}
async function saveFromEditPage(
  request: CcSwitchRequest, editingId: string | null,
): Promise<void> {
  const ok = editingId
    ? await ui.edit(store.workspace, store.runtimeId, editingId, request)
    : await ui.add(store.workspace, store.runtimeId, request);
  if (ok) closeEditPage();
}
// O4 (D-11): scoping — mutating ops (add/edit/switch/delete) stay mutually
// exclusive; `fetch` is a read-only query and no longer freezes the panel.
const mutating = computed(() => busyOp.value !== "" && busyOp.value !== "fetch");
// O4: an honest switch progress read-out — the op is one docker exec with no
// step events, so show a live elapsed counter instead of a fake stepper.
const switchElapsed = ref(0);
let switchTimer: number | null = null;
watch(busyOp, (op) => {
  if (op === "switch" && switchTimer === null) {
    switchElapsed.value = 0;
    switchTimer = window.setInterval(() => (switchElapsed.value += 1), 1000);
  } else if (op !== "switch" && switchTimer !== null) {
    window.clearInterval(switchTimer);
    switchTimer = null;
  }
}, { immediate: true });
onBeforeUnmount(() => {
  if (switchTimer !== null) window.clearInterval(switchTimer);
});

async function refresh(): Promise<void> {
  if (!store.runtimeId || !store.workspace) return;
  await ui.list(store.workspace, store.runtimeId);
}

// KI-7②: the pane is kept alive (v-show) so mounts never re-run; refetch
// whenever it becomes visible again (e.g. returning from a bash tab where
// the user edited providers in the cc-switch TUI). Non-immediate: the
// initial load is owned by onMounted.
watch(
  () => props.visible,
  (now, was) => {
    if (now && was === false && !loading.value) void refresh();
  },
);

function switchAgent(a: "claude" | "codex"): void {
  if (!store.runtimeId || !store.workspace) return;
  void ui.switchAgent(a, store.workspace, store.runtimeId);
}

const PRESETS = ["deepseek", "volcengine-ark", "zhipu", "kimi"] as const;

function openAdd(): void {
  openAddPage();  // PP (D-12): dedicated page
}

// --- activate (IDEA-4 / PP r3): the dedicated 启用 button makes that
// provider current; the official-direct card's 启用 IS the cancel-proxy
// path (pseudo target). The current provider has no deactivate button —
// to stop it, enable another entry (user ruling).
const switchedTo = ref("");
let switchFlashTimer: number | null = null;
/** IDEA-5 (5d): the newly-current row pulses once (visual feedback trio);
 * cleared after the keyframe so re-renders don't replay it. */
const flashId = ref("");
let rowFlashTimer: number | null = null;

async function activate(p: CcSwitchProvider): Promise<void> {
  if (mutating.value || p.is_current) return;
  let target = p.id;
  if (!p.base_url) {
    // Official-direct card: enabling it cancels the active proxy
    // (IDEA-4 round 3 semantics, relocated from the old current-row click).
    const current = providers.value.find((x) => x.is_current);
    if (current) {
      const ok = await confirm(
        t("ccswitch.cancelProxyConfirm", { name: current.name || current.id }));
      if (!ok) return;
    }
    target = "official";
  } else if (!p.has_api_key) {
    const go = await confirm(t("ccswitch.noKeyConfirm", { name: p.name || p.id }));
    if (!go) return;
  }
  const ok = await ui.activate(store.workspace, store.runtimeId, target);
  if (ok) {
    switchedTo.value =
      target === "official" ? t("ccswitch.officialDirect") : (p.name || p.id);
    if (switchFlashTimer !== null) window.clearTimeout(switchFlashTimer);
    switchFlashTimer = window.setTimeout(() => (switchedTo.value = ""), 3000);
    flashId.value = p.id;
    if (rowFlashTimer !== null) window.clearTimeout(rowFlashTimer);
    rowFlashTimer = window.setTimeout(() => (flashId.value = ""), 1300);
    // Sidebar G-12 cache follows the live switch (both agents are valid).
    void store.loadProviderStatus(agent.value);
  }
}

// --- delete ---
async function remove(p: CcSwitchProvider): Promise<void> {
  const ok = await confirm(t("ccswitch.deleteConfirm", { id: p.id }));
  if (!ok) return;
  await ui.remove(store.workspace, store.runtimeId, p.id);
}

const hasRuntime = computed(() => Boolean(store.runtimeId && store.workspace));

/**
 * PP r3 (user ruling): official-direct entries (no base_url) are ALWAYS
 * visible and pinned first (cc-switch parity — supersedes the S8g-2 hiding
 * rule); everything else keeps the store's stable first-seen order.
 */
const displayProviders = computed(() => [
  ...providers.value.filter((p) => !p.base_url),
  ...providers.value.filter((p) => Boolean(p.base_url)),
]);

onMounted(() => {
  if (hasRuntime.value) void refresh();
});
onBeforeUnmount(() => {
  if (switchFlashTimer !== null) window.clearTimeout(switchFlashTimer);
  if (rowFlashTimer !== null) window.clearTimeout(rowFlashTimer);
});
</script>

<template>
  <section class="ccswitch-tab">
    <!-- PP (D-12): the dedicated editor replaces the whole pane while open. -->
    <ProviderEditPage
      v-if="editTarget !== undefined"
      :agent="agent"
      :provider="editTarget"
      :presets="[...PRESETS]"
      :busy="busyOp === 'add' || busyOp === 'edit'"
      :busy-op="busyOp"
      @save="saveFromEditPage"
      @back="closeEditPage"
    />
    <template v-else>
    <header class="head">
      <div class="agent-toggle" role="tablist">
        <button
          v-for="a in (['claude', 'codex'] as const)"
          :key="a"
          role="tab"
          :aria-selected="agent === a"
          :class="{ active: agent === a }"
          :title="t(`tabbar.menu.${a}`)"
          :aria-label="t(`tabbar.menu.${a}`)"
          @click="switchAgent(a)"
        >
          <!-- PP r2 (user ruling): brand icons instead of text pills,
               mirroring the cc-switch desktop toggle. -->
          <svg v-if="a === 'claude'" viewBox="0 0 24 24" width="16" height="16"
               aria-hidden="true" role="img">
            <g stroke="#D97757" stroke-width="2.4" stroke-linecap="round">
              <line x1="12" y1="2.5" x2="12" y2="21.5" />
              <line x1="7.25" y1="3.77" x2="16.75" y2="20.23" />
              <line x1="3.77" y1="7.25" x2="20.23" y2="16.75" />
              <line x1="2.5" y1="12" x2="21.5" y2="12" />
              <line x1="3.77" y1="16.75" x2="20.23" y2="7.25" />
              <line x1="7.25" y1="20.23" x2="16.75" y2="3.77" />
            </g>
          </svg>
          <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="currentColor"
               aria-hidden="true" role="img">
            <path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.8956zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997z" />
          </svg>
        </button>
      </div>
      <span class="spacer" />
      <button class="primary" :disabled="!hasRuntime || mutating" @click="openAdd">
        {{ t("ccswitch.add") }}
      </button>
      <button :disabled="!hasRuntime || loading" @click="refresh">
        {{ loading ? t("ccswitch.loading") : t("ccswitch.refresh") }}
      </button>
    </header>

    <p v-if="!hasRuntime" class="banner warn">{{ t("ccswitch.noRuntime") }}</p>
    <p v-if="error" class="banner err" role="alert">{{ error }}</p>
    <!-- O4 (D-11): live switch progress — honest elapsed counter (the op is
         a single docker exec; no step events exist to render a stepper). -->
    <p v-if="busyOp === 'switch'" class="banner" role="status">
      {{ t("ccswitch.switching", { sec: switchElapsed }) }}
    </p>

    <!-- IDEA-5 (5d): switch feedback — a floating top toast (teleported to
         body so the pane's zoom/scroll never clips it), alongside the row
         pulse + chip transition below. role=status keeps the SR path. -->
    <Teleport to="body">
      <Transition name="toast">
        <p v-if="switchedTo" class="switch-toast" role="status">
          ✓ {{ t("ccswitch.switchedTo", { name: switchedTo }) }}
        </p>
      </Transition>
    </Teleport>

    <!-- PP r3: the agent toggle crossfades (out-in). PP r4: NO stale dim —
         the dimmed-list flash read as a broken middle state (user ruling);
         the swap is a soft 200ms fade. -->
    <Transition name="swap" mode="out-in">
      <div class="cards" v-if="displayProviders.length" :key="agent">
        <!-- PP (D-12): the fully card-ified list — icon + name + endpoint +
             current badge; hover surfaces the action group; the 启用 button
             activates (official card = cancel-proxy, IDEA-4 r3 semantics). -->
        <ProviderCard
          v-for="p in displayProviders"
          :key="p.id"
          :provider="p"
          :busy="mutating"
          :class="{ flash: p.id === flashId }"
          @activate="activate(p)"
          @edit="openEditPage(p)"
          @remove="remove(p)"
        />
      </div>
      <p v-else-if="!loading && hasRuntime" class="empty" :key="`empty-${agent}`">
        {{ t("ccswitch.empty") }}
      </p>
    </Transition>
    <!-- S8g-2 (user ruling 2026-08-29): the hidden-placeholder count note is
         GONE; the footer is now a constant usage hint. -->
    <p class="hidden-note">{{ t("ccswitch.usageHint") }}</p>

    <!-- add form -->
    </template>
  </section>
</template>

<style scoped>
.ccswitch-tab {
  flex: 1; min-height: 0; min-width: 0;
  display: flex; flex-direction: column;
  background: var(--surface);
  overflow: auto; padding: 12px 16px;
  outline: none;
}
.head { display: flex; align-items: center; gap: 8px; }
.spacer { flex: 1; }
/* PP r2 (user ruling): cc-switch-style icon chip toggle (was text pills). */
.agent-toggle {
  display: inline-flex; align-items: center; gap: 2px;
  padding: 3px; background: var(--surface-2);
  border: var(--border-w) solid var(--border); border-radius: var(--radius-md);
}
.agent-toggle button {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 26px; padding: 0;
  background: none; border: none; border-radius: var(--radius-sm);
  color: var(--text-faint);
}
.agent-toggle button:hover { color: var(--text-2); background: var(--surface-hover); }
.agent-toggle button.active { background: var(--accent-soft); color: var(--accent); }
.agent-toggle button svg { display: block; }

.banner { padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm); font-size: var(--font-sm); }
.banner.warn { background: var(--warn-bg); color: var(--warn-fg); }
.banner.err { background: var(--error-bg); color: var(--error-fg); }
/* S1 (⑤/A-21715): ONE grid template shared by header and rows. The last
 * track is FIXED, not auto — an auto track sizes to its own content
 * (buttons in rows vs "操作" text in the header), which desynced the 1fr
 * column and shifted everything after it (user evidence @zoom 1.5). */
.cards {
  display: flex; flex-direction: column; gap: 8px;
}
.cards .flash { animation: row-flash 1.3s var(--ease); }
@keyframes row-flash {
  0% { background: var(--accent-soft); }
  100% { background: var(--surface-2); }
}
/* PP (D-12): the old table styles (.row/.head-row/.cur…) went with the
 * card-ification; row-flash still animates the newly-current CARD. */
.banner.ok { background: var(--success-bg); color: var(--success); }
.empty { color: var(--text-muted); font-size: var(--font-md); }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong);
  border-radius: var(--radius-md); padding: 4px 12px; cursor: pointer;
}
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
button.danger { background: var(--error-bg); color: var(--error-fg); }

/* [1m] toggle rides inline at the end of the three applicable slots. */

/* --- IDEA-5 (5d): the mapping section --- */

.roles-title { font-size: var(--font-sm); color: var(--text-2); font-weight: 600; }
button.ghost { background: transparent; }

/* --- IDEA-5 (5d): switch feedback --- */
/* Floating toast: teleported to body (outside the zoomed/scrolling pane). */
/* PP r3: rounded rect — the 50% radius read as an ugly ellipse. */
.switch-toast {
  position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
  z-index: 1000; margin: 0; padding: var(--space-2) var(--space-5);
  background: var(--success-bg); color: var(--success);
  border: var(--border-w) solid var(--success); border-radius: var(--radius-md);
  font-size: var(--font-md); box-shadow: var(--shadow-menu);
}
/* PP r3/r4: agent-toggle crossfade — soft 200ms fade, no stale dim (the
 * dimmed flash read as a broken middle state). */
.swap-enter-active, .swap-leave-active {
  transition: opacity var(--duration-normal) var(--ease),
              transform var(--duration-normal) var(--ease);
}
.swap-enter-from { opacity: 0; transform: translateY(4px); }
.swap-leave-to { opacity: 0; transform: translateY(-4px); }
.toast-enter-active { transition: opacity var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease); }
.toast-leave-active { transition: opacity var(--duration-normal) var(--ease); }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
.toast-leave-to { opacity: 0; }

/* S3.6: users who ask the OS for less motion get instant state changes. */
@media (prefers-reduced-motion: reduce) {
  .cards .flash { animation: none; }
  .swap-enter-active, .swap-leave-active { transition: none; }
  .toast-enter-active, .toast-leave-active { transition: none; }
}
</style>
