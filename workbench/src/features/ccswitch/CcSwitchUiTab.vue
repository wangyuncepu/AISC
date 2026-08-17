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
import { computed, onMounted, reactive, ref } from "vue";
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

// --- delete ---
async function remove(p: CcSwitchProvider): Promise<void> {
  const ok = await confirm(t("ccswitch.deleteConfirm", { id: p.id }));
  if (!ok) return;
  await ui.remove(store.workspace, store.runtimeId, p.id);
}

const hasRuntime = computed(() => Boolean(store.runtimeId && store.workspace));

onMounted(() => {
  if (hasRuntime.value) void refresh();
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

    <div class="list" v-if="providers.length">
      <div v-for="p in providers" :key="p.id" class="row" :class="{ current: p.is_current }">
        <span class="cur">{{ p.is_current ? "→" : "" }}</span>
        <span class="pid" :title="p.id">{{ p.id }}</span>
        <span class="name">{{ p.name }}</span>
        <span class="url" :title="p.base_url">{{ p.base_url }}</span>
        <span class="model">{{ p.model }}</span>
        <span class="key" :class="{ none: !p.has_api_key }">
          {{ p.has_api_key ? p.api_key_mask : t("ccswitch.noKey") }}
        </span>
        <span class="actions">
          <button :disabled="busy !== ''" @click="openEdit(p)">{{ t("ccswitch.edit") }}</button>
          <button class="danger" :disabled="busy !== ''" @click="remove(p)">
            {{ t("ccswitch.delete") }}
          </button>
        </span>
      </div>
    </div>
    <p v-else-if="!loading && hasRuntime" class="empty">{{ t("ccswitch.empty") }}</p>

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
  display: grid; grid-template-columns: 18px 130px 120px 1fr 160px 110px auto;
  gap: 8px; align-items: center; padding: 6px 8px; border-radius: var(--radius-md);
  font-size: var(--font-sm); color: var(--text-2);
}
.row.current { background: var(--surface-2); }
.row.current .cur { color: var(--accent); }
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
