<script setup lang="ts">
/**
 * Shared settings form (Step 3 / G-01; IDEA-1 S2 extracted from
 * SettingsDialog so the same fields render in the modal dialog AND the
 * Settings tab).
 *
 * Load/save/reset against the typed settings backend, per-field errors and
 * effective-scope markers (02 §三.4 table). Defaults and bounds live in Rust -
 * this view renders whatever `load_settings` returns. Chrome (overlay + focus
 * trap vs tab pane) belongs to the parent; `mode` only toggles the footer
 * Close button and the tab-mode status strip.
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useSettingsStore } from "../../stores/settings";
import type { TerminalSettings, UiSettings, WindowSettings } from "../../types";

const props = withDefaults(defineProps<{ mode?: "dialog" | "tab" }>(), { mode: "dialog" });
const { t } = useI18n();
const store = useSettingsStore();
const emit = defineEmits<{ close: [] }>();

type EffectKind = "immediate" | "rebuild" | "restart";
interface FieldDef {
  key: string;
  labelKey: string;
  control: "select" | "number" | "text" | "checkbox" | "range";
  options?: { value: string; labelKey: string }[];
  /** Range slider bounds (control: "range"). Values match the Rust schema. */
  min?: number;
  max?: number;
  step?: number;
  effect: EffectKind;
  helpKey?: string;
}

const FIELDS: FieldDef[] = [
  { key: "ui.language", labelKey: "settings.ui.language", control: "select", options: [
    { value: "auto", labelKey: "settings.ui.language.auto" },
    { value: "zh-CN", labelKey: "settings.ui.language.zh" },
    { value: "en-US", labelKey: "settings.ui.language.en" },
  ], effect: "immediate" },
  { key: "ui.font_scale", labelKey: "settings.ui.fontScale", control: "range", min: 0.8, max: 1.5, step: 0.05, effect: "immediate" },
  { key: "ui.theme", labelKey: "settings.ui.theme", control: "select", options: [
    { value: "system", labelKey: "settings.ui.theme.system" },
    { value: "dark", labelKey: "settings.ui.theme.dark" },
    { value: "light", labelKey: "settings.ui.theme.light" },
  ], effect: "immediate" },
  { key: "ui.default_tab_agent", labelKey: "settings.ui.defaultTab", control: "select", options: [
    { value: "claude", labelKey: "tabbar.menu.claude" },
    { value: "codex", labelKey: "tabbar.menu.codex" },
    { value: "bash", labelKey: "tabbar.menu.bash" },
    { value: "cc-switch", labelKey: "tabbar.menu.cc-switch" },
  ], effect: "immediate", helpKey: "settings.ui.defaultTab.help" },
  { key: "ui.explorer_ignore", labelKey: "settings.ui.explorerIgnore", control: "text",
    effect: "immediate", helpKey: "settings.ui.explorerIgnore.help" },
  { key: "terminal.font_family", labelKey: "settings.term.fontFamily", control: "text",
    effect: "rebuild", helpKey: "settings.term.fontFamily.help" },
  { key: "terminal.font_size", labelKey: "settings.term.fontSize", control: "range", min: 10, max: 24, step: 1, effect: "immediate" },
  { key: "terminal.line_height", labelKey: "settings.term.lineHeight", control: "range", min: 1.0, max: 1.6, step: 0.05, effect: "immediate" },
  { key: "terminal.letter_spacing", labelKey: "settings.term.letterSpacing", control: "range", min: -1, max: 3, step: 1, effect: "immediate" },
  { key: "terminal.scrollback", labelKey: "settings.term.scrollback", control: "range", min: 1000, max: 50000, step: 1000, effect: "immediate" },
  { key: "terminal.renderer", labelKey: "settings.term.renderer", control: "select", options: [
    { value: "auto", labelKey: "settings.term.renderer.auto" },
    { value: "default", labelKey: "settings.term.renderer.default" },
    { value: "webgl", labelKey: "settings.term.renderer.webgl" },
  ], effect: "rebuild" },
  { key: "terminal.smooth_scroll_duration", labelKey: "settings.term.smoothScroll", control: "range", min: 0, max: 500, step: 10, effect: "immediate" },
  { key: "window.remember_geometry", labelKey: "settings.window.rememberGeometry", control: "checkbox", effect: "restart" },
  { key: "window.close_behavior", labelKey: "settings.window.closeBehavior", control: "select", options: [
    { value: "quit", labelKey: "settings.window.closeBehavior.quit" },
    { value: "minimize-to-tray", labelKey: "settings.window.closeBehavior.tray" },
  ], effect: "immediate" },
];

const EFFECT_KEY: Record<EffectKind, string> = {
  immediate: "settings.effect.immediate",
  rebuild: "settings.effect.rebuild",
  restart: "settings.effect.restart",
};

const GROUP_KEY: Record<string, string> = {
  ui: "settings.group.ui",
  terminal: "settings.group.terminal",
  window: "settings.group.window",
};

// Explicit non-null section models (rendered only under `v-if="store.doc"`);
// the `?? {}` casts never render - defaults come from the backend.
const ui = computed<UiSettings>(() => store.doc?.ui ?? ({} as UiSettings));
const terminal = computed<TerminalSettings>(() => store.doc?.terminal ?? ({} as TerminalSettings));
const windowS = computed<WindowSettings>(() => store.doc?.window ?? ({} as WindowSettings));

/** Explorer ignore names as a comma-separated string for the text input. */
const explorerIgnoreText = computed<string>({
  get: () => (ui.value.explorer_ignore ?? []).join(", "),
  set: (v: string) => {
    ui.value.explorer_ignore = v
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  },
});

const issuesByField = computed(() => {
  const m: Record<string, string> = {};
  for (const i of store.doc?.issues ?? []) m[i.field] = i.reason;
  return m;
});

const saving = computed(() => store.saveState === "saving");
const savedFlash = ref(false);

onMounted(async () => {
  if (!store.loaded) await store.load();
});

async function onSave() {
  const outcome = await store.save();
  if (!outcome) return; // error banner shows the reason
  savedFlash.value = true;
  window.setTimeout(() => (savedFlash.value = false), 2000);
}

async function onReset() {
  const ok = await confirm(t("settings.resetConfirm"));
  if (!ok) return;
  await store.reset();
}

/** Stage 5 (A-ONB07): reopen the setup wizard. Marks onboarding in_progress
 *  at the environment step; the App.vue gate re-shows the overlay. */
async function reopenOnboarding() {
  const { useOnboardingStore } = await import("../../stores/onboarding");
  const onboarding = useOnboardingStore();
  await onboarding.patch({ status: "in_progress", currentStep: "environment" });
  emit("close");
}

function onCancel() {
  store.cancel();
  emit("close");
}
</script>

<template>
  <div class="settings-form">
    <!-- Tab mode has no dialog header, so the dirty/saved state lives here. -->
    <div v-if="props.mode === 'tab'" class="tab-strip">
      <span class="spacer" />
      <span v-if="store.dirty" class="chip dirty">{{ t("settings.dirty") }}</span>
      <span v-if="savedFlash" class="chip saved">{{ t("settings.saved") }}</span>
    </div>

    <p v-if="store.corrupted" class="banner warn">
      {{ t("settings.corrupted") }}
    </p>
    <p v-if="store.readOnly" class="banner warn">
      {{ t("settings.readOnly") }}
    </p>
    <p v-if="store.error" class="banner err">
      {{ store.error }}
      <button class="link" :disabled="saving" @click="store.save()">{{ t("settings.retry") }}</button>
    </p>

    <div v-if="store.doc" class="body">
      <template v-for="group in ['ui', 'terminal', 'window']" :key="group">
        <h3 class="group">{{ t(GROUP_KEY[group]) }}</h3>

        <!-- ui section -->
        <template v-if="group === 'ui'">
          <div v-for="f in FIELDS.filter((x) => x.key.startsWith('ui.'))" :key="f.key" class="field">
            <label :for="f.key" class="label">{{ t(f.labelKey) }}</label>
            <select v-if="f.key === 'ui.language'" :id="f.key" v-model="ui.language" :disabled="store.readOnly">
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ t(o.labelKey) }}</option>
            </select>
            <input v-else-if="f.key === 'ui.font_scale'" :id="f.key" v-model.number="ui.font_scale"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <span v-if="f.control === 'range'" class="val">{{ f.key === 'ui.font_scale' ? ui.font_scale.toFixed(2) : '' }}</span>
            <select v-else-if="f.key === 'ui.theme'" :id="f.key" v-model="ui.theme" :disabled="store.readOnly">
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ t(o.labelKey) }}</option>
            </select>
            <select v-else-if="f.key === 'ui.default_tab_agent'" :id="f.key" v-model="ui.default_tab_agent" :disabled="store.readOnly">
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ t(o.labelKey) }}</option>
            </select>
            <input v-else-if="f.key === 'ui.explorer_ignore'" :id="f.key" v-model="explorerIgnoreText"
              type="text" :disabled="store.readOnly" />
            <span class="effect">{{ t(EFFECT_KEY[f.effect]) }}</span>
            <span v-if="f.helpKey" class="help">{{ t(f.helpKey) }}</span>
            <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
          </div>
        </template>

        <!-- terminal section -->
        <template v-else-if="group === 'terminal'">
          <div v-for="f in FIELDS.filter((x) => x.key.startsWith('terminal.'))" :key="f.key" class="field">
            <label :for="f.key" class="label">{{ t(f.labelKey) }}</label>
            <input v-if="f.control === 'text'" :id="f.key" v-model="terminal.font_family" type="text" :disabled="store.readOnly" />
            <input v-else-if="f.key === 'terminal.font_size'" :id="f.key" v-model.number="terminal.font_size"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <input v-else-if="f.key === 'terminal.line_height'" :id="f.key" v-model.number="terminal.line_height"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <input v-else-if="f.key === 'terminal.letter_spacing'" :id="f.key" v-model.number="terminal.letter_spacing"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <input v-else-if="f.key === 'terminal.scrollback'" :id="f.key" v-model.number="terminal.scrollback"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <select v-else-if="f.key === 'terminal.renderer'" :id="f.key" v-model="terminal.renderer" :disabled="store.readOnly">
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ t(o.labelKey) }}</option>
            </select>
            <input v-else-if="f.key === 'terminal.smooth_scroll_duration'" :id="f.key" v-model.number="terminal.smooth_scroll_duration"
              type="range" :min="f.min" :max="f.max" :step="f.step" :disabled="store.readOnly" />
            <span v-if="f.control === 'range'" class="val">{{
              f.key === 'terminal.font_size' ? terminal.font_size + 'px'
              : f.key === 'terminal.line_height' ? terminal.line_height.toFixed(2)
              : f.key === 'terminal.letter_spacing' ? terminal.letter_spacing
              : f.key === 'terminal.scrollback' ? terminal.scrollback
              : f.key === 'terminal.smooth_scroll_duration' ? terminal.smooth_scroll_duration + 'ms'
              : ''
            }}</span>
            <span class="effect">{{ t(EFFECT_KEY[f.effect]) }}</span>
            <span v-if="f.helpKey" class="help">{{ t(f.helpKey) }}</span>
            <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
          </div>
        </template>

        <!-- window section -->
        <template v-else>
          <div v-for="f in FIELDS.filter((x) => x.key.startsWith('window.'))" :key="f.key" class="field">
            <label :for="f.key" class="label">{{ t(f.labelKey) }}</label>
            <input v-if="f.key === 'window.remember_geometry'" :id="f.key" v-model="windowS.remember_geometry" type="checkbox" :disabled="store.readOnly" />
            <select v-else-if="f.key === 'window.close_behavior'" :id="f.key" v-model="windowS.close_behavior" :disabled="store.readOnly">
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ t(o.labelKey) }}</option>
            </select>
            <span class="effect">{{ t(EFFECT_KEY[f.effect]) }}</span>
            <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
          </div>
          <p v-if="store.doc.window.geometry" class="note">
            {{ t("settings.window.geometryNote", { x: store.doc.window.geometry.x, y: store.doc.window.geometry.y, w: store.doc.window.geometry.width, h: store.doc.window.geometry.height, max: store.doc.window.geometry.maximized ? t("settings.window.geometryMaximized") : "" }) }}
            {{ store.doc.window.geometry.width }}×{{ store.doc.window.geometry.height }}
            {{ store.doc.window.geometry.maximized ? "" : "" }}
          </p>
        </template>
      </template>
    </div>
    <div v-else class="body">
      <p class="loading">{{ t("settings.loading") }}</p>
    </div>

    <footer class="foot">
      <button class="primary" :disabled="saving || store.readOnly || !store.loaded" @click="onSave">
        {{ saving ? t("settings.saving") : t("settings.save") }}
      </button>
      <button :disabled="saving || store.readOnly || !store.loaded" @click="onReset">{{ t("settings.reset") }}</button>
      <button :disabled="saving" @click="reopenOnboarding">{{ t("settings.reopenOnboarding") }}</button>
      <!-- Dialog mode keeps the explicit Close (Escape/overlay also close);
           tab mode closes via the tab × only. -->
      <button v-if="props.mode === 'dialog'" :disabled="saving" @click="onCancel">{{ t("settings.close") }}</button>
    </footer>
  </div>
</template>

<style scoped>
/* Fill the host (dialog panel / settings tab pane); the body grows and the
   sticky footer pins to the bottom when the content is short. */
.settings-form { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tab-strip { display: flex; align-items: center; gap: 8px; padding: 8px 14px 0; }
.tab-strip .spacer { flex: 1; }
.chip { font-size: var(--font-xs); padding: 2px 8px; border-radius: 10px; }
.chip.dirty { background: var(--warn-bg); color: var(--warn-fg); }
.chip.saved { background: var(--success-bg); color: var(--success); }
.banner { margin: 8px 14px 0; padding: 6px 10px; border-radius: var(--radius-md); font-size: var(--font-sm); }
.banner.warn { background: var(--warn-bg); color: var(--warn-fg); }
.banner.err { background: var(--error-bg); color: var(--error-fg); }
.link { background: none; border: none; color: var(--info); padding: 0; margin-left: 8px; cursor: pointer; text-decoration: underline; }
.body { padding: 6px 14px 12px; flex: 1; }
.group { margin: 12px 0 4px; font-size: var(--font-sm); color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.5px; }
.field { display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
.label { width: 150px; font-size: var(--font-md); color: var(--text-2); }
input[type="text"], input[type="number"], select {
  background: var(--bg); color: var(--text-2); border: 1px solid var(--border-2); border-radius: var(--radius-md);
  padding: 4px 6px; font-size: var(--font-md); flex: 1; min-width: 120px;
}
input[type="range"] {
  flex: 1; min-width: 120px; accent-color: var(--accent); cursor: pointer;
}
input:disabled, select:disabled { opacity: 0.5; }
.val {
  font-size: var(--font-sm); color: var(--info); min-width: 46px; text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.effect { font-size: var(--font-xs); color: var(--text-muted); white-space: nowrap; }
.help { font-size: var(--font-xs); color: var(--text-faint); width: 100%; }
.err-text { font-size: var(--font-xs); color: var(--error); width: 100%; }
.note { font-size: var(--font-xs); color: var(--text-faint); margin-top: 8px; }
.loading { color: var(--text-muted); font-size: var(--font-md); }
.foot {
  display: flex; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--border);
  /* Sticky bottom so Save stays reachable when the parent scrolls (dialog
     panel and settings tab both scroll their content). */
  position: sticky; bottom: 0; z-index: 2; background: var(--surface);
}
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: var(--radius-md);
  padding: 6px 14px; font-size: var(--font-md); cursor: pointer;
}
button:hover:not(:disabled) { background: var(--surface-hover); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
</style>
