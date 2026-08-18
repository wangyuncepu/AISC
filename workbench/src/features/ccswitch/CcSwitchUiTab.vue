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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useRuntimeStore } from "../../stores/runtime";
import { useCcSwitchUiStore } from "../../stores/ccSwitchUi";
import type { CcSwitchProvider } from "../../types";

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

function openEdit(p: CcSwitchProvider): void {
  editId.value = p.id;
  editForm.name = p.name;
  editForm.baseUrl = p.base_url;
  editForm.model = p.model;
  editForm.apiKey = "";
}

async function submitEdit(): Promise<void> {
  if (!editId.value) return;
  const id = editId.value;
  const ok = await ui.edit(store.workspace, store.runtimeId, id, {
    patch: {
      name: editForm.name.trim(),
      base_url: editForm.baseUrl.trim(),
      model: editForm.model.trim(),
    },
    api_key: editForm.apiKey || undefined,
  });
  editForm.apiKey = "";
  if (ok) editId.value = null;
}

// --- activate (IDEA-4): click a row to make that provider current ---
const switchedTo = ref("");
let switchFlashTimer: number | null = null;

function canActivate(p: CcSwitchProvider): boolean {
  // Rows without a usable configuration (e.g. cc-switch's built-in
  // claude-official with an empty env) cannot be activated — the adapter
  // would fail closed; the UI simply does not offer the click.
  return !p.is_current && busy.value === "" && Boolean(p.base_url);
}

async function activate(p: CcSwitchProvider): Promise<void> {
  if (!canActivate(p)) return;
  const ok = await ui.activate(store.workspace, store.runtimeId, p.id);
  if (ok) {
    switchedTo.value = p.name || p.id;
    if (switchFlashTimer !== null) window.clearTimeout(switchFlashTimer);
    switchFlashTimer = window.setTimeout(() => (switchedTo.value = ""), 3000);
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
    <p v-if="switchedTo" class="banner ok" role="status">
      ✓ {{ t("ccswitch.switchedTo", { name: switchedTo }) }}
    </p>

    <div class="list" v-if="visibleProviders.length">
      <div
        v-for="p in visibleProviders"
        :key="p.id"
        class="row"
        :class="{ current: p.is_current, activatable: canActivate(p) }"
        :title="p.is_current
          ? t('ccswitch.currentHint')
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
      <label class="field"><span>{{ t("ccswitch.model") }}</span><input v-model="editForm.model" /></label>
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
  background: var(--surface-3); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 4px 14px; cursor: pointer; color: var(--text-2);
}
.agent-toggle button.active, .mode-toggle button.active {
  border-color: var(--accent); color: var(--accent);
}
.banner { padding: 6px 10px; border-radius: var(--radius-md); font-size: var(--font-sm); }
.banner.warn { background: var(--warn-bg); color: var(--warn-fg); }
.banner.err { background: var(--error-bg); color: var(--error-fg); }
.list { display: flex; flex-direction: column; gap: 2px; margin-top: 10px; }
.row {
  display: grid; grid-template-columns: 64px 130px 120px 1fr 160px 110px auto;
  gap: 8px; align-items: center; padding: 6px 8px; border-radius: var(--radius-md);
  font-size: var(--font-sm); color: var(--text-2);
}
.row.current { background: var(--surface-2); }
.row.activatable { cursor: pointer; }
.row.activatable:hover { background: var(--surface-hover); }
.cur { color: var(--text-faint); font-size: var(--font-xs); }
.cur.on { color: var(--accent); font-weight: 600; }
.banner.ok { background: var(--success-bg); color: var(--success); }
.hidden-note { font-size: var(--font-xs); color: var(--text-faint); }
.pid { font-family: monospace; }
.url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); }
.model { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.key { color: var(--success); font-family: monospace; }
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
  margin-top: 12px; padding: 12px; max-width: 560px;
  background: var(--bg); border: 1px solid var(--border-2); border-radius: var(--radius-lg);
  display: flex; flex-direction: column; gap: 8px;
}
.form-card h3 { margin: 0; font-size: var(--font-md); color: var(--text-2); }
.mode-toggle { display: flex; gap: 6px; }
.field { display: flex; align-items: center; gap: 8px; font-size: var(--font-sm); }
.field span { width: 90px; color: var(--text-muted); }
.field input, .field select {
  flex: 1; background: var(--surface); color: var(--text-2);
  border: 1px solid var(--border-2); border-radius: var(--radius-md); padding: 4px 6px;
}
.hint { font-size: var(--font-xs); color: var(--text-faint); margin: 0; }
.form-actions { display: flex; gap: 8px; }
</style>
