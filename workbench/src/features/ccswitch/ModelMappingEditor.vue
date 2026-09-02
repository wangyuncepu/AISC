<script setup lang="ts">
/**
 * ModelMappingEditor (PP, D-12): the desktop-parity mapping table.
 *
 * - claude: three ROLE rows (Sonnet/Opus/Haiku → upstream model) plus a
 *   collapsed "advanced" pair (default model / subagent). The data shape is
 *   the five role-env slots the adapter has always carried — this is a
 *   view-layer re-projection of the SAME storage, not a new contract.
 * - codex: the three-column catalog editor (model / display name / context
 *   window) writing `modelCatalog` — the /model list source. Rows are
 *   add/remove; the fetch-models candidates dropdown inserts rows.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { CcSwitchCatalogEntry } from "../../types";

const { t } = useI18n();
const props = defineProps<{
  agent: "claude" | "codex";
  /** claude: the five role-env slots (v-model style, mutated in place). */
  roles?: Record<string, string>;
  /** claude: role-slot metadata (key/label/[1m] eligibility). */
  roleSlots?: Array<{ key: string; label: string; oneM?: boolean }>;
  /** codex: catalog rows (v-model style, mutated in place). */
  catalog?: CcSwitchCatalogEntry[];
  /** candidate model ids from fetch-models + known_models (dropdown). */
  candidates?: string[];
}>();

const advancedOpen = ref(false);

const mainRoles = computed(() =>
  (props.roleSlots ?? []).filter((s) =>
    ["ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
     "ANTHROPIC_DEFAULT_HAIKU_MODEL"].includes(s.key)),
);
const advRoles = computed(() =>
  (props.roleSlots ?? []).filter((s) =>
    ["ANTHROPIC_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"].includes(s.key)),
);

function addCatalogRow(): void {
  (props.catalog ?? []).push({ model: "", display_name: "", context_window: 128000 });
}

function removeCatalogRow(i: number): void {
  (props.catalog ?? []).splice(i, 1);
}

const ONE_M = "[1m]";
/** IDEA-5 round 4 parity: the [1m] suffix is legal on MODEL/OPUS/SONNET
 * only; the toggle appends/strips it on the slot's current value. */
function hasOneM(key: string): boolean {
  return (props.roles?.[key] ?? "").endsWith(ONE_M);
}
function toggleOneM(key: string): void {
  if (!props.roles) return;
  const value = props.roles[key] ?? "";
  props.roles[key] = hasOneM(key)
    ? value.slice(0, -ONE_M.length)
    : (value ? value + ONE_M : value);
}
</script>

<template>
  <!-- claude: role mapping table -->
  <div v-if="agent === 'claude'" class="mapping" role="group"
       :aria-label="t('ccswitch.mapping.title')">
    <p class="hint">{{ t("ccswitch.mapping.claudeHint") }}</p>
    <div v-for="slot in mainRoles" :key="slot.key" class="row">
      <span class="role">{{ slot.label }}</span>
      <input
        list="pp-map-candidates"
        :value="roles?.[slot.key] ?? ''"
        :placeholder="t('ccswitch.mapping.placeholder')"
        @input="roles && (roles[slot.key] = ($event.target as HTMLInputElement).value)"
      />
      <button v-if="slot.oneM" class="icon one-m" :class="{ on: hasOneM(slot.key) }"
              :title="t('ccswitch.mapping.oneMTip')"
              @click="toggleOneM(slot.key)">[1m]</button>
    </div>
    <datalist id="pp-map-candidates">
      <option v-for="c in candidates" :key="c" :value="c" />
    </datalist>
    <button class="link" @click="advancedOpen = !advancedOpen">
      {{ advancedOpen ? t("ccswitch.mapping.advHide") : t("ccswitch.mapping.advShow") }}
    </button>
    <div v-if="advancedOpen">
      <div v-for="slot in advRoles" :key="slot.key" class="row">
        <span class="role">{{ slot.label }}</span>
        <input
          list="pp-map-candidates"
          :value="roles?.[slot.key] ?? ''"
          :placeholder="t('ccswitch.mapping.placeholder')"
          @input="roles && (roles[slot.key] = ($event.target as HTMLInputElement).value)"
        />
        <button v-if="slot.oneM" class="icon one-m" :class="{ on: hasOneM(slot.key) }"
                :title="t('ccswitch.mapping.oneMTip')"
                @click="toggleOneM(slot.key)">[1m]</button>
      </div>
    </div>
  </div>

  <!-- codex: three-column catalog editor -->
  <div v-else class="mapping" role="group" :aria-label="t('ccswitch.mapping.title')">
    <p class="hint">{{ t("ccswitch.mapping.codexHint") }}</p>
    <div class="cat-head">
      <span>{{ t("ccswitch.mapping.colModel") }}</span>
      <span>{{ t("ccswitch.mapping.colName") }}</span>
      <span>{{ t("ccswitch.mapping.colWindow") }}</span>
      <span></span>
    </div>
    <div v-for="(row, i) in catalog" :key="i" class="cat-row">
      <input
        list="pp-cat-candidates"
        v-model="row.model"
        :placeholder="t('ccswitch.mapping.placeholder')"
      />
      <input v-model="row.display_name" :placeholder="t('ccswitch.mapping.namePh')" />
      <input
        type="number" min="1000" step="1000"
        :value="row.context_window || 128000"
        @input="row.context_window = Number(($event.target as HTMLInputElement).value) || 128000"
      />
      <button class="icon danger" :title="t('ccswitch.mapping.remove')"
              @click="removeCatalogRow(i)">×</button>
    </div>
    <datalist id="pp-cat-candidates">
      <option v-for="c in candidates" :key="c" :value="c" />
    </datalist>
    <button class="link" @click="addCatalogRow">＋ {{ t("ccswitch.mapping.add") }}</button>
  </div>
</template>

<style scoped>
.mapping { display: flex; flex-direction: column; gap: 6px; }
.hint { font-size: var(--font-xs); color: var(--text-faint); margin: 0; }
.row { display: flex; align-items: center; gap: 8px; }
.role { width: 110px; font-size: var(--font-sm); color: var(--text-2); }
input {
  flex: 1; min-width: 120px;
  background: var(--surface-3); color: var(--text);
  border: var(--border-w) solid var(--border-strong); border-radius: var(--radius-sm);
  min-height: var(--control-h-sm); padding: 0 var(--space-2); font-size: var(--font-sm);
}
input[type="number"] { max-width: 110px; }
.cat-head, .cat-row { display: grid; grid-template-columns: 1fr 0.8fr 100px 24px; gap: 6px; align-items: center; }
.cat-head { font-size: var(--font-xs); color: var(--text-faint); }
button.icon { min-width: 24px; min-height: 24px; padding: 0; background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: var(--font-md); }
button.icon.danger:hover { color: var(--error); }
button.icon.one-m { font-size: var(--font-xs); border: 1px solid var(--border); border-radius: var(--radius-sm); }
button.icon.one-m.on { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
button.link { background: none; border: none; color: var(--accent); cursor: pointer; padding: 0; font-size: var(--font-sm); align-self: flex-start; }
</style>

