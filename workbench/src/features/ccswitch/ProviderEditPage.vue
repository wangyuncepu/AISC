<script setup lang="ts">
/**
 * ProviderEditPage (PP, D-12): the desktop-parity dedicated editor — a full
 * view (not a popover) with 简易/高级 two tiers, mirroring the cc-switch
 * desktop workflow:
 *
 *   简易: name + base URL + API key (preset dropdown autofills on add)
 *   高级: + upstream format (BOTH agents; claude=anthropic / codex=
 *         openai_responses defaults) and the mapping editor (the former
 *         notes/website/icon「其它信息」block is retired — 2026-09-06)
 *
 * Save goes through the ccSwitchUi store (layer contract); the secret rides
 * the request only. Back with unsaved edits asks for confirmation.
 */
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useRuntimeStore } from "../../stores/runtime";
import { useCcSwitchUiStore } from "../../stores/ccSwitchUi";
import type { CcSwitchCatalogEntry, CcSwitchProvider } from "../../types";
import ModelMappingEditor from "./ModelMappingEditor.vue";

const { t } = useI18n();
const props = defineProps<{
  agent: "claude" | "codex";
  /** null = add mode. */
  provider: CcSwitchProvider | null;
  presets: string[];
  busy: boolean;
  busyOp?: string;
}>();
const busyOp = computed(() => props.busyOp ?? "");
const emit = defineEmits<{
  (e: "save", request: import("../../types").CcSwitchRequest, editingId: string | null): void;
  (e: "back"): void;
}>();

const tier = ref<"simple" | "advanced">("simple");
/** Add mode only: preset quick-add (server-side full autofill — base,
 * catalog, apiFormat all ride the simple path = the "按 preset 预填"
 * ruling) vs custom. */
const addMode = ref<"preset" | "custom">("preset");
const form = reactive({
  id: "", // add mode only
  preset: props.presets[0] ?? "deepseek",
  name: props.provider?.name ?? "",
  baseUrl: props.provider?.base_url ?? "",
  apiKey: "",
  apiFormat: (props.provider?.api_format
    ?? (props.agent === "codex" ? "openai_responses" : "anthropic")) as
    "anthropic" | "openai_chat" | "openai_responses",
  notes: props.provider?.notes ?? "",
  website: props.provider?.website_url ?? "",
  icon: props.provider?.icon ?? "",
  iconColor: props.provider?.icon_color ?? "",
});
const roles = reactive<Record<string, string>>({ ...(props.provider?.role_env ?? {}) });
const catalog = ref<CcSwitchCatalogEntry[]>(
  (props.provider?.model_catalog ?? []).map((m) => ({ ...m })));

const ROLE_SLOTS = [
  { key: "ANTHROPIC_MODEL", labelKey: "ccswitch.role.model", oneM: true },
  { key: "ANTHROPIC_DEFAULT_OPUS_MODEL", labelKey: "ccswitch.role.opus", oneM: true },
  { key: "ANTHROPIC_DEFAULT_SONNET_MODEL", labelKey: "ccswitch.role.sonnet", oneM: true },
  { key: "ANTHROPIC_DEFAULT_HAIKU_MODEL", labelKey: "ccswitch.role.haiku", oneM: false },
  { key: "CLAUDE_CODE_SUBAGENT_MODEL", labelKey: "ccswitch.role.subagent", oneM: false },
];
const roleSlots = ROLE_SLOTS.map((s) => ({ key: s.key, label: t(s.labelKey), oneM: s.oneM }));

const modelField = ref(props.provider?.model ?? "");
/** Last fetch outcome shown inline (ok=n models / warn=message). */
const fetched = ref<{ ok: boolean; n: number; message: string } | null>(null);
const runtime = useRuntimeStore();
const uiStore = useCcSwitchUiStore();
/** PP (D-12): the fetch-models button rides the editor's mapping section
 * (same store op the old popover had; read-only, never blocks the form).
 * PP r3 (user report): the form's unsaved key rides along — fetch must
 * work BEFORE the first save, not only against the stored key. */
async function fetchNow(): Promise<void> {
  if (!props.provider || !runtime.runtimeId || !runtime.workspace) return;
  fetched.value = null;
  await uiStore.fetchModels(runtime.workspace, runtime.runtimeId, props.provider.id,
    form.apiKey || undefined);
  const r = uiStore.fetchedModels[props.provider.id];
  fetched.value = r
    ? { ok: Boolean(r.available), n: r.models.length,
        message: r.available ? "" : (r.message || t("ccswitch.fetchUnavailable")) }
    : null;
}
const candidates = computed<string[]>(() => {
  if (!props.provider) return [];
  return [
    ...(uiStore.fetchedModels[props.provider.id]?.models ?? []),
    ...(props.provider.known_models ?? []),
  ];
});

const adding = computed(() => props.provider === null);

/** Anything typed vs the entry snapshot? Drives the back-confirmation. */
const dirty = ref(false);
function touch(): void { dirty.value = true; }

async function onBack(): Promise<void> {
  if (dirty.value) {
    const ok = await confirm(t("ccswitch.edit.unsavedConfirm"));
    if (!ok) return;
  }
  emit("back");
}

function buildRequest(): import("../../types").CcSwitchRequest {
  const extras = {
    api_format: form.apiFormat,
    notes: form.notes.trim(),
    website_url: form.website.trim(),
    icon: form.icon,
    icon_color: form.iconColor,
  };
  if (adding.value) {
    if (addMode.value === "preset") {
      return { mode: "simple", id: form.preset, provider: form.preset,
               api_key: form.apiKey || undefined };
    }
    return {
      mode: "custom",
      id: form.id.trim(),
      name: form.name.trim(),
      base_url: form.baseUrl.trim(),
      api_key: form.apiKey || undefined,
      ...extras,
      ...(props.agent === "codex"
        ? { model_catalog: { models: catalog.value.map((m) => ({
            model: m.model, contextWindow: m.context_window,
            display_name: m.display_name || undefined })) } }
        : {}),
    };
  }
  return {
    api_key: form.apiKey || undefined,
    patch: {
      name: form.name.trim(),
      base_url: form.baseUrl.trim(),
      ...(props.agent === "codex" ? { model: modelField.value.trim() } : {}),
      ...(props.agent === "claude"
        ? { env: Object.fromEntries(ROLE_SLOTS.map((s) => [s.key, roles[s.key] || null])) }
        : {}),
      ...extras,
      ...(props.agent === "codex"
        ? { model_catalog: { models: catalog.value.map((m) => ({
            model: m.model, contextWindow: m.context_window,
            display_name: m.display_name || undefined })) } }
        : {}),
    },
  };
}

function onSave(): void {
  if (adding.value && addMode.value === "custom" && !form.id.trim()) return;
  if (adding.value && addMode.value === "custom" && !form.baseUrl.trim()) return;
  if (!adding.value && !form.baseUrl.trim()) return;
  emit("save", buildRequest(), adding.value ? null : props.provider!.id);
}
</script>

<template>
  <div class="edit-page">
    <header class="head">
      <button class="icon" :title="t('ccswitch.edit.back')" @click="onBack">←</button>
      <h2>{{ adding ? t("ccswitch.edit.addTitle") :
        t("ccswitch.edit.title", { name: form.name || provider?.id }) }}</h2>
      <span class="spacer" />
      <button class="primary" :disabled="busy" @click="onSave">
        {{ busy ? t("ccswitch.working") : t("ccswitch.edit.save") }}
      </button>
    </header>

    <!-- PP r4: op failures used to look like a dead button ("保存无反应")
         because the store error only rendered on the list view. -->
    <p v-if="uiStore.error" class="save-error" role="alert">{{ uiStore.error }}</p>

    <div class="tiers" role="tablist">
      <button role="tab" :aria-selected="tier === 'simple'"
              :class="{ on: tier === 'simple' }" @click="tier = 'simple'">
        {{ t("ccswitch.edit.tierSimple") }}
      </button>
      <button role="tab" :aria-selected="tier === 'advanced'"
              :class="{ on: tier === 'advanced' }" @click="tier = 'advanced'">
        {{ t("ccswitch.edit.tierAdvanced") }}
      </button>
    </div>

    <div class="body">
      <template v-if="adding">
        <div class="tiers" role="tablist" style="padding: 0 0 6px">
          <button role="tab" :aria-selected="addMode === 'preset'"
                  :class="{ on: addMode === 'preset' }" @click="addMode = 'preset'; touch()">
            {{ t("ccswitch.edit.fromPreset") }}
          </button>
          <button role="tab" :aria-selected="addMode === 'custom'"
                  :class="{ on: addMode === 'custom' }" @click="addMode = 'custom'; touch()">
            {{ t("ccswitch.edit.custom") }}
          </button>
        </div>
        <template v-if="addMode === 'preset'">
          <label class="field">
            <span>{{ t("ccswitch.preset") }}</span>
            <select v-model="form.preset" @change="touch">
              <option v-for="p in presets" :key="p" :value="p">{{ p }}</option>
            </select>
          </label>
          <p class="hint">{{ t("ccswitch.edit.presetHint") }}</p>
        </template>
      </template>
      <label v-if="adding && addMode === 'custom'" class="field">
        <span>{{ t("ccswitch.id") }}</span>
        <input v-model="form.id" :placeholder="form.preset" @input="touch" />
      </label>
      <template v-if="!adding || addMode === 'custom'">
      <label class="field"><span>{{ t("ccswitch.name") }}</span>
        <input v-model="form.name" @input="touch" /></label>
      <label class="field"><span>{{ t("ccswitch.baseUrl") }}</span>
        <input v-model="form.baseUrl" @input="touch" /></label>
      <label v-if="agent === 'codex'" class="field">
        <span>{{ t("ccswitch.model") }}</span>
        <input v-model="modelField" @input="touch" /></label>
      </template>
      <label class="field"><span>{{ t("ccswitch.apiKey") }}</span>
        <input v-model="form.apiKey" type="password" autocomplete="off" @input="touch" /></label>
      <p class="hint">{{ t("ccswitch.secretHint") }}</p>

      <template v-if="tier === 'advanced'">
        <label class="field">
          <span>{{ t("ccswitch.edit.apiFormat") }}</span>
          <select v-model="form.apiFormat" @change="touch">
            <option value="anthropic">{{ t("ccswitch.edit.fmtAnthropic") }}</option>
            <option value="openai_chat">{{ t("ccswitch.edit.fmtChat") }}</option>
            <option value="openai_responses">{{ t("ccswitch.edit.fmtResponses") }}</option>
          </select>
        </label>
        <p v-if="form.apiFormat !== 'anthropic'" class="hint">
          {{ t("ccswitch.edit.formatRouteHint") }}
        </p>

        <h3>{{ t("ccswitch.mapping.title") }}</h3>
        <div v-if="provider" class="field">
          <button :disabled="busyOp === 'fetch'" @click="fetchNow">
            {{ busyOp === "fetch" ? t("ccswitch.fetching") : t("ccswitch.fetchModels") }}
          </button>
          <p v-if="fetched" class="hint" :class="{ warn: !fetched.ok }">
            {{ fetched.ok ? t("ccswitch.fetchDone", { n: fetched.n })
              : t("ccswitch.fetchFailed", { message: fetched.message }) }}
          </p>
        </div>
        <ModelMappingEditor
          :agent="agent"
          :roles="roles"
          :role-slots="roleSlots"
          :catalog="catalog"
          :candidates="candidates"
        />

        <!-- Manual-test #2 (2026-09-06): the「其它信息」section (notes /
             website / icon / icon color) is retired from the form per user
             request. The form fields + save passthrough stay — editing an
             existing provider that already has extras keeps its values
             instead of silently wiping them; new providers save empty
             extras and the provider card falls back to its default badge. -->
      </template>
    </div>
  </div>
</template>

<style scoped>
.edit-page { display: flex; flex-direction: column; height: 100%; overflow: auto; }
.head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; }
.head h2 { font-size: var(--font-md); margin: 0; }
.spacer { flex: 1; }
.tiers { display: flex; gap: 6px; padding: 0 14px 8px; }
/* PP r2 (user ruling): rounded-rect segments, not pill ellipses. */
.tiers button {
  border: var(--border-w) solid var(--border); border-radius: var(--radius-md);
  background: none; color: var(--text-muted); padding: 4px 16px; cursor: pointer;
  font-size: var(--font-sm);
}
.tiers button.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.save-error {
  margin: 0 14px 8px; padding: var(--space-1) var(--space-2);
  background: var(--error-bg); color: var(--error-fg);
  border-radius: var(--radius-sm); font-size: var(--font-sm);
}
.body { padding: 4px 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.body h3 { font-size: var(--font-sm); color: var(--text-faint); margin: 12px 0 0;
  text-transform: uppercase; letter-spacing: 0.5px; }
.field { display: flex; align-items: center; gap: 8px; }
.field > span { width: 90px; font-size: var(--font-sm); color: var(--text-2); flex: none; }
input, select {
  flex: 1; background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-sm); padding: 0 var(--space-2); font-size: var(--font-sm);
}
.hint { font-size: var(--font-xs); color: var(--text-faint); margin: 0; }
button { cursor: pointer; }
button.primary { background: var(--accent); border: none; color: var(--accent-fg);
  min-height: var(--control-h-sm); padding: 0 var(--space-4); border-radius: var(--radius-sm);
  font-weight: 600; }
button.primary:disabled { opacity: 0.5; cursor: default; }
button.icon { background: none; border: none; color: var(--text-muted); font-size: var(--font-md); padding: 2px 6px; }
button.icon.on { background: var(--accent-soft); border-radius: var(--radius-sm); color: var(--accent); }
</style>
