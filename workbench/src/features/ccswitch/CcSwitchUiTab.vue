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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
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
const addOpen = ref(false);
const addMode = ref<"simple" | "custom">("simple");
const addForm = reactive({
  provider: "deepseek" as string,
  id: "",
  name: "",
  baseUrl: "",
  model: "",
  apiKey: "",
});

function openAdd(): void {
  openAddPage();  // PP (D-12): dedicated page
  return;
  addMode.value = "simple";
  addForm.provider = "deepseek";
  addForm.id = "";
  addForm.name = "";
  addForm.baseUrl = "";
  addForm.model = "";
  addForm.apiKey = "";
  addOpen.value = true;
}

// --- activate (IDEA-4): click a row to make that provider current ---
const switchedTo = ref("");
let switchFlashTimer: number | null = null;
/** IDEA-5 (5d): the newly-current row pulses once (visual feedback trio);
 * cleared after the keyframe so re-renders don't replay it. */
const flashId = ref("");
let rowFlashTimer: number | null = null;

function canActivate(p: CcSwitchProvider): boolean {
  if (mutating.value) return false;
  // A current PROXY row offers "cancel proxy" (click → confirm → official
  // direct). Non-current rows need a usable configuration (no base_url =
  // cc-switch's official/direct placeholders — hidden, see visibleProviders).
  return p.is_current ? Boolean(p.base_url) : Boolean(p.base_url);
}

async function activate(p: CcSwitchProvider): Promise<void> {
  if (!canActivate(p)) return;
  let target = p.id;
  if (p.is_current) {
    // Clicking the active row = the cancel-proxy affordance (IDEA-4 round 3):
    // confirm, then switch to the direct-official row via the pseudo target.
    const ok = await confirm(t("ccswitch.cancelProxyConfirm", { name: p.name || p.id }));
    if (!ok) return;
    target = "official";
  }
  if (target !== "official" && !p.has_api_key) {
    const go = await confirm(t("ccswitch.noKeyConfirm", { name: p.name || p.id }));
    if (!go) return;
  }
  const ok = await ui.activate(store.workspace, store.runtimeId, target);
  if (ok) {
    switchedTo.value =
      target === "official" ? t("ccswitch.officialDirect") : (p.name || p.id);
    if (switchFlashTimer !== null) window.clearTimeout(switchFlashTimer);
    switchFlashTimer = window.setTimeout(() => (switchedTo.value = ""), 3000);
    flashId.value = target;
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
 * IDEA-4 (manual round 2): rows that cannot be activated (no base_url —
 * cc-switch's built-in `*-official` rows and the imported `default`
 * direct-official snapshot) are HIDDEN instead of shown unclickable; the
 * current row always stays visible.
 */
const visibleProviders = computed(() =>
  providers.value.filter((p) => p.is_current || Boolean(p.base_url)),
);

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
          @click="switchAgent(a)"
        >{{ t(`tabbar.menu.${a}`) }}</button>
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

    <div class="cards" v-if="visibleProviders.length">
      <!-- PP (D-12): the fully card-ified list (user ruling) — icon + name +
           endpoint + current badge; hover surfaces the action group; the card
           body activates (current = cancel-proxy, IDEA-4 r3 semantics). -->
      <ProviderCard
        v-for="p in visibleProviders"
        :key="p.id"
        :provider="p"
        :busy="mutating"
        :class="{ flash: p.id === flashId }"
        @activate="activate(p)"
        @edit="openEditPage(p)"
        @remove="remove(p)"
      />
    </div>
    <p v-else-if="!loading && hasRuntime" class="empty">{{ t("ccswitch.empty") }}</p>
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

/* --- IDEA-5 (5d): switch feedback trio --- */
/* Row pulse: the newly-current row flashes once after the list repaint. */
.row { transition: background-color var(--duration-normal) var(--ease); }
.row.flash { animation: row-pulse 1.2s ease-out; }
@keyframes row-pulse {
  0% { background: var(--accent-soft); }
  100% { background: var(--surface-2); }
}
/* The「使用中」chip eases in instead of popping. */
.cur { transition: opacity var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease); }
.cur.on { animation: chip-in var(--duration-slow) var(--ease); }
@keyframes chip-in {
  from { opacity: 0; transform: scale(0.85); }
  to { opacity: 1; transform: scale(1); }
}
/* Floating toast: teleported to body (outside the zoomed/scrolling pane). */
.switch-toast {
  position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
  z-index: 1000; margin: 0; padding: var(--space-2) var(--space-5);
  background: var(--success-bg); color: var(--success);
  border: var(--border-w) solid var(--success); border-radius: var(--radius-full);
  font-size: var(--font-md); box-shadow: var(--shadow-menu);
}
.toast-enter-active { transition: opacity var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease); }
.toast-leave-active { transition: opacity var(--duration-normal) var(--ease); }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
.toast-leave-to { opacity: 0; }

/* S3.6: users who ask the OS for less motion get instant state changes. */
@media (prefers-reduced-motion: reduce) {
  .row, .cur { transition: none; }
  .row.flash, .cur.on { animation: none; }
  .toast-enter-active, .toast-leave-active { transition: none; }
}
</style>
