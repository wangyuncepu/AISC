<script setup lang="ts">
/**
 * Settings dialog skeleton (Step 3; field wiring lands in Step 7 / G-01).
 *
 * Load/save/reset against the typed settings backend, per-field errors and
 * effective-scope markers (02 §三.4 table), keyboard-accessible modal
 * (A-G01-1). Defaults and bounds live in Rust - this view renders whatever
 * `load_settings` returns.
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useSettingsStore } from "../../stores/settings";
import type { TerminalSettings, UiSettings, WindowSettings } from "../../types";

const store = useSettingsStore();
const emit = defineEmits<{ close: [] }>();

type EffectKind = "immediate" | "rebuild" | "restart";
interface FieldDef {
  key: string;
  label: string;
  control: "select" | "number" | "text" | "checkbox";
  options?: { value: string; label: string }[];
  effect: { kind: EffectKind; text: string };
  help?: string;
}

const EFFECT_LABEL: Record<EffectKind, string> = {
  immediate: "即时生效",
  rebuild: "重建 Terminal 视图生效（会话不重开）",
  restart: "下次启动生效",
};

const FIELDS: FieldDef[] = [
  { key: "ui.language", label: "语言", control: "select", options: [
    { value: "auto", label: "自动（安装器/系统）" },
    { value: "zh-CN", label: "中文（zh-CN）" },
    { value: "en-US", label: "English (en-US)" },
  ], effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "ui.font_scale", label: "UI 字号缩放", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "ui.theme", label: "主题", control: "select", options: [
    { value: "system", label: "跟随系统" },
    { value: "dark", label: "深色" },
    { value: "light", label: "浅色" },
  ], effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "terminal.font_family", label: "终端字体", control: "text",
    effect: { kind: "rebuild", text: EFFECT_LABEL.rebuild }, help: "非空，≤256 字符" },
  { key: "terminal.font_size", label: "终端字号", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "terminal.line_height", label: "行高", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "terminal.letter_spacing", label: "字距", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "terminal.scrollback", label: "回滚行数", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "terminal.renderer", label: "渲染器", control: "select", options: [
    { value: "auto", label: "自动" },
    { value: "default", label: "默认 (canvas)" },
    { value: "webgl", label: "WebGL" },
  ], effect: { kind: "rebuild", text: EFFECT_LABEL.rebuild } },
  { key: "terminal.smooth_scroll_duration", label: "平滑滚动 (ms)", control: "number",
    effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
  { key: "window.remember_geometry", label: "记住窗口位置与大小", control: "checkbox",
    effect: { kind: "restart", text: EFFECT_LABEL.restart } },
  { key: "window.close_behavior", label: "关闭窗口行为", control: "select", options: [
    { value: "quit", label: "退出 Workbench" },
    { value: "minimize-to-tray", label: "最小化到托盘（托盘不可用时回退退出）" },
  ], effect: { kind: "immediate", text: EFFECT_LABEL.immediate } },
];

const GROUP: Record<string, string> = {
  ui: "界面",
  terminal: "终端",
  window: "窗口",
};

// Explicit non-null section models (rendered only under `v-if="store.doc"`);
// the `?? {}` casts never render - defaults come from the backend.
const ui = computed<UiSettings>(() => store.doc?.ui ?? ({} as UiSettings));
const terminal = computed<TerminalSettings>(() => store.doc?.terminal ?? ({} as TerminalSettings));
const windowS = computed<WindowSettings>(() => store.doc?.window ?? ({} as WindowSettings));

const issuesByField = computed(() => {
  const m: Record<string, string> = {};
  for (const i of store.doc?.issues ?? []) m[i.field] = i.reason;
  return m;
});

const saving = computed(() => store.saveState === "saving");
const savedFlash = ref(false);
const panel = ref<HTMLElement | null>(null);

onMounted(async () => {
  if (!store.loaded) await store.load();
  await nextTick();
  // Initial focus into the dialog (keyboard reachable, A-G01-1); Tab then
  // walks the controls.
  panel.value?.focus();
  window.addEventListener("keydown", onKeydown);
});

onUnmounted(() => window.removeEventListener("keydown", onKeydown));

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}

function onOverlayDown(e: MouseEvent) {
  if (e.target === e.currentTarget) emit("close");
}

async function onSave() {
  const outcome = await store.save();
  if (!outcome) return; // error banner shows the reason
  savedFlash.value = true;
  window.setTimeout(() => (savedFlash.value = false), 2000);
}

async function onReset() {
  const ok = await confirm(
    "重置所有 GUI 设置为默认值？aisc_cli_path（CLI 固定）、历史记录、工作区与 Runtime 不受影响。"
  );
  if (!ok) return;
  await store.reset();
}

function onCancel() {
  store.cancel();
  emit("close");
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayDown">
    <section ref="panel" class="panel" role="dialog" aria-modal="true" aria-label="设置" tabindex="-1">
      <header class="head">
        <h2>设置</h2>
        <span v-if="store.dirty" class="chip dirty">未保存更改</span>
        <span v-if="savedFlash" class="chip saved">已保存</span>
      </header>

      <p v-if="store.corrupted" class="banner warn">
        设置文件已损坏并已隔离备份（settings.json.corrupt），当前显示默认值。保存或重置后将写入新文件。
      </p>
      <p v-if="store.readOnly" class="banner warn">
        设置文件来自更新的 Workbench 版本，当前为只读：保存与重置已禁用。
      </p>
      <p v-if="store.error" class="banner err">
        {{ store.error }}
        <button class="link" :disabled="saving" @click="store.save()">重试</button>
      </p>

      <div v-if="store.doc" class="body">
        <template v-for="group in ['ui', 'terminal', 'window']" :key="group">
          <h3 class="group">{{ GROUP[group] }}</h3>

          <!-- ui section -->
          <template v-if="group === 'ui'">
            <div v-for="f in FIELDS.filter((x) => x.key.startsWith('ui.'))" :key="f.key" class="field">
              <label :for="f.key" class="label">{{ f.label }}</label>
              <select v-if="f.key === 'ui.language'" :id="f.key" v-model="ui.language" :disabled="store.readOnly">
                <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <input v-else-if="f.key === 'ui.font_scale'" :id="f.key" v-model="ui.font_scale"
                type="number" min="0.8" max="1.5" step="0.05" :disabled="store.readOnly" />
              <select v-else-if="f.key === 'ui.theme'" :id="f.key" v-model="ui.theme" :disabled="store.readOnly">
                <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <span class="effect">{{ f.effect.text }}</span>
              <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
            </div>
          </template>

          <!-- terminal section -->
          <template v-else-if="group === 'terminal'">
            <div v-for="f in FIELDS.filter((x) => x.key.startsWith('terminal.'))" :key="f.key" class="field">
              <label :for="f.key" class="label">{{ f.label }}</label>
              <input v-if="f.control === 'text'" :id="f.key" v-model="terminal.font_family" type="text" :disabled="store.readOnly" />
              <input v-else-if="f.key === 'terminal.font_size'" :id="f.key" v-model="terminal.font_size" type="number" min="10" max="24" step="1" :disabled="store.readOnly" />
              <input v-else-if="f.key === 'terminal.line_height'" :id="f.key" v-model="terminal.line_height" type="number" min="1.0" max="1.6" step="0.05" :disabled="store.readOnly" />
              <input v-else-if="f.key === 'terminal.letter_spacing'" :id="f.key" v-model="terminal.letter_spacing" type="number" min="-1" max="3" step="1" :disabled="store.readOnly" />
              <input v-else-if="f.key === 'terminal.scrollback'" :id="f.key" v-model="terminal.scrollback" type="number" min="1000" max="50000" step="1000" :disabled="store.readOnly" />
              <select v-else-if="f.key === 'terminal.renderer'" :id="f.key" v-model="terminal.renderer" :disabled="store.readOnly">
                <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <input v-else-if="f.key === 'terminal.smooth_scroll_duration'" :id="f.key" v-model="terminal.smooth_scroll_duration" type="number" min="0" max="500" step="10" :disabled="store.readOnly" />
              <span class="effect">{{ f.effect.text }}</span>
              <span v-if="f.help" class="help">{{ f.help }}</span>
              <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
            </div>
          </template>

          <!-- window section -->
          <template v-else>
            <div v-for="f in FIELDS.filter((x) => x.key.startsWith('window.'))" :key="f.key" class="field">
              <label :for="f.key" class="label">{{ f.label }}</label>
              <input v-if="f.key === 'window.remember_geometry'" :id="f.key" v-model="windowS.remember_geometry" type="checkbox" :disabled="store.readOnly" />
              <select v-else-if="f.key === 'window.close_behavior'" :id="f.key" v-model="windowS.close_behavior" :disabled="store.readOnly">
                <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <span class="effect">{{ f.effect.text }}</span>
              <span v-if="issuesByField[f.key]" class="err-text">{{ issuesByField[f.key] }}</span>
            </div>
            <p v-if="store.doc.window.geometry" class="note">
              已记录窗口位置 {{ store.doc.window.geometry.x }},{{ store.doc.window.geometry.y }}
              {{ store.doc.window.geometry.width }}×{{ store.doc.window.geometry.height }}
              {{ store.doc.window.geometry.maximized ? "（最大化）" : "" }}
            </p>
          </template>
        </template>
      </div>
      <div v-else class="body">
        <p class="loading">正在加载设置…</p>
      </div>

      <footer class="foot">
        <button class="primary" :disabled="saving || store.readOnly || !store.loaded" @click="onSave">
          {{ saving ? "保存中…" : "保存" }}
        </button>
        <button :disabled="saving || store.readOnly || !store.loaded" @click="onReset">重置为默认</button>
        <button :disabled="saving" @click="onCancel">关闭</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.panel {
  width: 560px; max-width: 92vw; max-height: 84vh; overflow: auto;
  background: #252526; color: #ccc; border: 1px solid #444; border-radius: 6px;
  outline: none; display: flex; flex-direction: column;
}
.head {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border-bottom: 1px solid #333;
}
.head h2 { margin: 0; font-size: 15px; color: #ddd; }
.chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.chip.dirty { background: #3a3220; color: #e0c97a; }
.chip.saved { background: #1e3a2a; color: #9ce0b0; }
.banner { margin: 8px 14px 0; padding: 6px 10px; border-radius: 4px; font-size: 12px; }
.banner.warn { background: #3a3220; color: #e0c97a; }
.banner.err { background: #4a2626; color: #e0b0b0; }
.link { background: none; border: none; color: #9cc4e0; padding: 0; margin-left: 8px; cursor: pointer; text-decoration: underline; }
.body { padding: 6px 14px 12px; flex: 1; }
.group { margin: 12px 0 4px; font-size: 12px; color: #6a6a6a; text-transform: uppercase; letter-spacing: 0.5px; }
.field { display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
.label { width: 150px; font-size: 13px; color: #ddd; }
input[type="text"], input[type="number"], select {
  background: #1e1e1e; color: #ddd; border: 1px solid #444; border-radius: 4px;
  padding: 4px 6px; font-size: 13px; flex: 1; min-width: 120px;
}
input:disabled, select:disabled { opacity: 0.5; }
.effect { font-size: 11px; color: #888; white-space: nowrap; }
.help { font-size: 11px; color: #6a6a6a; width: 100%; }
.err-text { font-size: 11px; color: #e57373; width: 100%; }
.note { font-size: 11px; color: #6a6a6a; margin-top: 8px; }
.loading { color: #888; font-size: 13px; }
.foot {
  display: flex; gap: 8px; padding: 10px 14px; border-top: 1px solid #333;
}
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover:not(:disabled) { background: #1177bb; }
</style>
