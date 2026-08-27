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
const { agent, providers, loading, busy, error } = storeToRefs(ui);

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

// --- add ---
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
  addMode.value = "simple";
  addForm.provider = "deepseek";
  addForm.id = "";
  addForm.name = "";
  addForm.baseUrl = "";
  addForm.model = "";
  addForm.apiKey = "";
  addOpen.value = true;
}

async function submitAdd(): Promise<void> {
  let ok = false;
  if (addMode.value === "simple") {
    const id = (addForm.id || addForm.provider).trim();
    ok = await ui.add(store.workspace, store.runtimeId, {
      mode: "simple", id, provider: addForm.provider, api_key: addForm.apiKey,
    });
  } else {
    if (!addForm.baseUrl.trim() || !addForm.name.trim()) return;
    ok = await ui.add(store.workspace, store.runtimeId, {
      mode: "custom",
      id: addForm.id.trim(),
      name: addForm.name.trim(),
      base_url: addForm.baseUrl.trim(),
      model: addForm.model.trim(),
      api_key: addForm.apiKey,
    });
  }
  addForm.apiKey = ""; // transient: cleared the moment it leaves the channel
  if (ok) addOpen.value = false;
}

// --- edit ---
const editId = ref<string | null>(null);
const editForm = reactive({ name: "", baseUrl: "", model: "", apiKey: "" });

/** IDEA-5 (5d): the five claude role slots the mapping section edits.
 * Upstream fans ANTHROPIC_MODEL out to the DEFAULT_* slots when they are
 * unset — every save writes ALL FIVE explicitly (empty ⇒ null ⇒ the key is
 * deleted and the server-side alias fallback applies). */
const ROLE_SLOTS = [
  { key: "ANTHROPIC_MODEL", labelKey: "ccswitch.role.model", titleKey: "ccswitch.role.modelEnv", oneM: true },
  { key: "ANTHROPIC_DEFAULT_OPUS_MODEL", labelKey: "ccswitch.role.opus", titleKey: "ccswitch.role.opusEnv", oneM: true },
  { key: "ANTHROPIC_DEFAULT_SONNET_MODEL", labelKey: "ccswitch.role.sonnet", titleKey: "ccswitch.role.sonnetEnv", oneM: true },
  { key: "ANTHROPIC_DEFAULT_HAIKU_MODEL", labelKey: "ccswitch.role.haiku", titleKey: "ccswitch.role.haikuEnv", oneM: false },
  { key: "CLAUDE_CODE_SUBAGENT_MODEL", labelKey: "ccswitch.role.subagent", titleKey: "ccswitch.role.subagentEnv", oneM: false },
] as const;
const editRoles = reactive<Record<string, string>>({});
const ONE_M_SUFFIX = "[1m]";

/** The fixture rule: the 1M-context suffix is legal on MODEL/OPUS/SONNET
 * only. The toggle appends/strips it on the slot's current value — the
 * stored string is exactly what cc-switch's mapping keeps. */
function hasOneM(key: string): boolean {
  return editRoles[key]?.endsWith(ONE_M_SUFFIX) ?? false;
}
function toggleOneM(key: string): void {
  const value = editRoles[key] ?? "";
  editRoles[key] = hasOneM(key)
    ? value.slice(0, -ONE_M_SUFFIX.length)
    : (value ? value + ONE_M_SUFFIX : value);
}

/** The dropdown's option pool (three tiers): fetched remote models ∪ the
 * preset's known list ∪ the provider's current slot values — with the [1m]
 * variant offered for every id (the suffix is a plain string part, exactly
 * like cc-switch's mapping stores it). */
const modelOptions = computed<string[]>(() => {
  const p = providers.value.find((x) => x.id === editId.value);
  if (!p) return [];
  const pool = [
    ...(ui.fetchedModels[p.id]?.models ?? []),
    ...(p.known_models ?? []),
    ...ROLE_SLOTS.map((s) => editRoles[s.key]).filter(Boolean),
  ];
  const withVariants = pool.flatMap((m) =>
    m.endsWith(ONE_M_SUFFIX) ? [m] : [m, m + ONE_M_SUFFIX]);
  return [...new Set(withVariants)];
});
const fetchHint = computed<string | null>(() => {
  if (!editId.value) return null;
  const r = ui.fetchedModels[editId.value];
  if (!r || r.available) return null;
  return r.message || t("ccswitch.fetchUnavailable");
});

function openEdit(p: CcSwitchProvider): void {
  editId.value = p.id;
  editForm.name = p.name;
  editForm.baseUrl = p.base_url;
  editForm.model = p.model;
  editForm.apiKey = "";
  const env = p.role_env ?? {};
  for (const slot of ROLE_SLOTS) {
    editRoles[slot.key] = env[slot.key] ?? "";
  }
}

async function fetchModelList(): Promise<void> {
  if (!editId.value || busy.value) return;
  await ui.fetchModels(store.workspace, store.runtimeId, editId.value);
}

async function submitEdit(): Promise<void> {
  if (!editId.value) return;
  const id = editId.value;
  const isClaude = agent.value === "claude";
  const patch: NonNullable<CcSwitchRequest["patch"]> = {
    name: editForm.name.trim(),
    base_url: editForm.baseUrl.trim(),
    // Claude's model rides the five-slot env block (all five explicit);
    // codex keeps the single TOML model field.
    model: isClaude ? undefined : editForm.model.trim(),
  };
  if (isClaude) {
    patch.env = {};
    for (const slot of ROLE_SLOTS) {
      const value = (editRoles[slot.key] ?? "").trim();
      patch.env[slot.key] = value === "" ? null : value;
    }
  }
  const ok = await ui.edit(store.workspace, store.runtimeId, id, {
    patch,
    api_key: editForm.apiKey || undefined,
  });
  editForm.apiKey = "";
  if (ok) editId.value = null;
}

// --- activate (IDEA-4): click a row to make that provider current ---
const switchedTo = ref("");
let switchFlashTimer: number | null = null;
/** IDEA-5 (5d): the newly-current row pulses once (visual feedback trio);
 * cleared after the keyframe so re-renders don't replay it. */
const flashId = ref("");
let rowFlashTimer: number | null = null;

function canActivate(p: CcSwitchProvider): boolean {
  if (busy.value !== "") return false;
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
      <button class="primary" :disabled="!hasRuntime || busy !== ''" @click="openAdd">
        {{ t("ccswitch.add") }}
      </button>
      <button :disabled="!hasRuntime || loading" @click="refresh">
        {{ loading ? t("ccswitch.loading") : t("ccswitch.refresh") }}
      </button>
    </header>

    <p v-if="!hasRuntime" class="banner warn">{{ t("ccswitch.noRuntime") }}</p>
    <p v-if="error" class="banner err" role="alert">{{ error }}</p>

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

    <div class="list" v-if="visibleProviders.length">
      <!-- v2.1.7 S1 (⑤/A-21715): frozen column header — same grid template
           as .row so header and cells stay aligned at every width; the
           pid/url cells carry the same truncation classes as data rows. -->
      <div class="head-row">
        <span>{{ t("ccswitch.colStatus") }}</span>
        <span class="pid">{{ t("ccswitch.colId") }}</span>
        <span>{{ t("ccswitch.colName") }}</span>
        <span class="url">{{ t("ccswitch.colEndpoint") }}</span>
        <span>{{ t("ccswitch.colModel") }}</span>
        <span>{{ t("ccswitch.colKey") }}</span>
        <span>{{ t("ccswitch.colActions") }}</span>
      </div>
      <div
        v-for="p in visibleProviders"
        :key="p.id"
        class="row"
        :class="{ current: p.is_current, flash: p.id === flashId, activatable: canActivate(p), cancelable: p.is_current && p.base_url }"
        :title="p.is_current
          ? t('ccswitch.cancelProxyHint')
          : p.base_url ? t('ccswitch.activateHint') : t('ccswitch.notConfiguredHint')"
        @click="activate(p)"
      >
        <span class="cur" :class="{ on: p.is_current }">
          {{ p.is_current ? t("ccswitch.currentChip") : "" }}
        </span>
        <span class="pid" :title="p.id">{{ p.id }}</span>
        <span class="name">{{ p.name }}</span>
        <span class="url" :title="p.base_url">{{ p.base_url }}</span>
        <span class="model">{{ p.model }}</span>
        <span class="key" :class="{ none: !p.has_api_key }">
          {{ p.has_api_key ? p.api_key_mask : t("ccswitch.noKey") }}
        </span>
        <span class="actions" @click.stop>
          <button :disabled="busy !== ''" @click="openEdit(p)">{{ t("ccswitch.edit") }}</button>
          <button class="danger" :disabled="busy !== ''" @click="remove(p)">
            {{ t("ccswitch.delete") }}
          </button>
        </span>
      </div>
    </div>
    <p v-else-if="!loading && hasRuntime" class="empty">{{ t("ccswitch.empty") }}</p>
    <p v-if="providers.length > visibleProviders.length" class="hidden-note">
      {{ t("ccswitch.hiddenRows") }}
    </p>

    <!-- add form -->
    <div v-if="addOpen" class="form-card" role="dialog" :aria-label="t('ccswitch.add')">
      <div class="mode-toggle">
        <button :class="{ active: addMode === 'simple' }" @click="addMode = 'simple'">
          {{ t("ccswitch.mode.simple") }}
        </button>
        <button :class="{ active: addMode === 'custom' }" @click="addMode = 'custom'">
          {{ t("ccswitch.mode.custom") }}
        </button>
      </div>
      <template v-if="addMode === 'simple'">
        <label class="field">
          <span>{{ t("ccswitch.preset") }}</span>
          <select v-model="addForm.provider">
            <option v-for="preset in PRESETS" :key="preset" :value="preset">{{ preset }}</option>
          </select>
        </label>
        <label class="field">
          <span>{{ t("ccswitch.id") }}</span>
          <input v-model="addForm.id" :placeholder="addForm.provider" />
        </label>
      </template>
      <template v-else>
        <label class="field"><span>{{ t("ccswitch.id") }}</span><input v-model="addForm.id" /></label>
        <label class="field"><span>{{ t("ccswitch.name") }}</span><input v-model="addForm.name" /></label>
        <label class="field"><span>{{ t("ccswitch.baseUrl") }}</span><input v-model="addForm.baseUrl" /></label>
        <label class="field"><span>{{ t("ccswitch.model") }}</span><input v-model="addForm.model" /></label>
      </template>
      <label class="field">
        <span>{{ t("ccswitch.apiKey") }}</span>
        <input v-model="addForm.apiKey" type="password" autocomplete="off" />
      </label>
      <p class="hint">{{ t("ccswitch.secretHint") }}</p>
      <div class="form-actions">
        <button class="primary" :disabled="busy !== ''" @click="submitAdd">
          {{ busy.startsWith("add:") ? t("ccswitch.working") : t("ccswitch.add") }}
        </button>
        <button :disabled="busy !== ''" @click="addOpen = false">{{ t("ccswitch.cancel") }}</button>
      </div>
    </div>

    <!-- edit form -->
    <div v-if="editId" class="form-card" role="dialog" :aria-label="t('ccswitch.edit')">
      <h3>{{ t("ccswitch.edit") }}: {{ editId }}</h3>
      <label class="field"><span>{{ t("ccswitch.name") }}</span><input v-model="editForm.name" /></label>
      <label class="field"><span>{{ t("ccswitch.baseUrl") }}</span><input v-model="editForm.baseUrl" /></label>
      <!-- IDEA-5 (5d): the claude mapping section — five role slots with the
           three-tier dropdown (fetched ∪ known ∪ current); codex keeps its
           single TOML model field. -->
      <template v-if="agent === 'claude'">
        <div class="roles-head">
          <span class="roles-title">{{ t("ccswitch.rolesTitle") }}</span>
          <button
            class="ghost"
            :disabled="busy !== ''"
            :title="t('ccswitch.fetchHint')"
            @click="fetchModelList"
          >{{ busy.startsWith("fetch:") ? t("ccswitch.fetching") : t("ccswitch.fetchModels") }}</button>
        </div>
        <datalist id="cc-model-options">
          <option v-for="m in modelOptions" :key="m" :value="m" />
        </datalist>
        <label v-for="slot in ROLE_SLOTS" :key="slot.key" class="field">
          <span :title="t(slot.titleKey)">{{ t(slot.labelKey) }}</span>
          <input v-model="editRoles[slot.key]" list="cc-model-options" spellcheck="false" />
          <input
            v-if="slot.oneM"
            class="one-m"
            type="checkbox"
            :checked="hasOneM(slot.key)"
            :title="t('ccswitch.oneMHint')"
            :aria-label="t('ccswitch.oneMLabel')"
            @change="toggleOneM(slot.key)"
          />
        </label>
        <p v-if="fetchHint" class="hint warn">{{ t("ccswitch.fetchFailed", { message: fetchHint }) }}</p>
        <p class="hint">{{ t("ccswitch.rolesHint") }}</p>
      </template>
      <label v-else class="field"><span>{{ t("ccswitch.model") }}</span><input v-model="editForm.model" /></label>
      <label class="field">
        <span>{{ t("ccswitch.newKey") }}</span>
        <input v-model="editForm.apiKey" type="password" autocomplete="off" />
      </label>
      <p class="hint">{{ t("ccswitch.editKeyHint") }}</p>
      <div class="form-actions">
        <button class="primary" :disabled="busy !== ''" @click="submitEdit">
          {{ busy === `edit:${editId}` ? t("ccswitch.working") : t("ccswitch.save") }}
        </button>
        <button :disabled="busy !== ''" @click="editId = null">{{ t("ccswitch.cancel") }}</button>
      </div>
    </div>
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
.agent-toggle button, .mode-toggle button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); border: var(--border-w) solid transparent; border-radius: var(--radius-sm);
  padding: 0 var(--space-3); cursor: pointer; color: var(--text-2); font-size: var(--font-sm);
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
.agent-toggle button.active, .mode-toggle button.active {
  background: var(--accent-soft); color: var(--text); font-weight: 600;
}
.banner { padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm); font-size: var(--font-sm); }
.banner.warn { background: var(--warn-bg); color: var(--warn-fg); }
.banner.err { background: var(--error-bg); color: var(--error-fg); }
/* S1 (⑤/A-21715): ONE grid template shared by header and rows. The last
 * track is FIXED, not auto — an auto track sizes to its own content
 * (buttons in rows vs "操作" text in the header), which desynced the 1fr
 * column and shifted everything after it (user evidence @zoom 1.5). */
.list {
  --ccs-grid: 64px 130px 120px 1fr 160px 110px 150px;
  display: flex; flex-direction: column; gap: 2px; margin-top: 10px;
}
.row {
  display: grid; grid-template-columns: var(--ccs-grid);
  gap: var(--space-2); align-items: center; padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm);
  font-size: var(--font-sm); color: var(--text-2);
}
.head-row {
  display: grid; grid-template-columns: var(--ccs-grid);
  gap: var(--space-2); align-items: center; padding: var(--space-1) var(--space-2);
  font-size: var(--font-xs); color: var(--text-faint); font-weight: 600;
}
.head-row > span { min-width: 0; }
.head-row .pid, .head-row .url {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row.current { background: var(--accent-soft); }
/* B-03: every text cell truncates inside its grid track — a long provider
 * name must never overlap the neighbouring column (user evidence C-08.png). */
.row > span { min-width: 0; }
.row .name, .row .pid, .row .key {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row.activatable { cursor: pointer; }
.row.activatable:hover { background: var(--surface-hover); }
.row.cancelable .cur.on { cursor: pointer; }
.cur { color: var(--text-faint); font-size: var(--font-xs); }
.cur.on { color: var(--accent); font-weight: 600; }
.banner.ok { background: var(--success-bg); color: var(--success); }
.hidden-note { font-size: var(--font-xs); color: var(--text-faint); }
.pid { font-family: var(--font-mono); }
.url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); }
.model { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.key { color: var(--success); font-family: var(--font-mono); }
.key.none { color: var(--text-faint); }
.actions { display: flex; gap: 6px; }
.empty { color: var(--text-muted); font-size: var(--font-md); }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong);
  border-radius: var(--radius-md); padding: 4px 12px; cursor: pointer;
}
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
button.danger { background: var(--error-bg); color: var(--error-fg); }
.form-card {
  margin-top: var(--space-3); padding: var(--space-3); max-width: 560px;
  background: var(--surface-2); border: var(--border-w) solid var(--border-2); border-radius: var(--radius-lg);
  display: flex; flex-direction: column; gap: var(--space-2);
  box-shadow: var(--shadow-soft);
}
.form-card h3 { margin: 0; font-size: var(--font-md); color: var(--text-2); }
.mode-toggle { display: flex; gap: 6px; }
.field { display: flex; align-items: center; gap: 8px; font-size: var(--font-sm); }
.field span { width: 90px; color: var(--text-muted); }
.field input, .field select {
  flex: 1; min-height: var(--control-h-sm); box-sizing: border-box;
  background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-2);
}
.hint { font-size: var(--font-xs); color: var(--text-faint); margin: 0; }
.hint.warn { color: var(--warn); }
.form-actions { display: flex; gap: 8px; }
/* [1m] toggle rides inline at the end of the three applicable slots. */
.field input.one-m { width: auto; flex: 0 0 auto; margin-left: 0; }

/* --- IDEA-5 (5d): the mapping section --- */
.roles-head { display: flex; align-items: center; gap: 10px; margin-top: 4px; }
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
