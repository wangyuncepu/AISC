<script setup lang="ts">
/**
 * ProviderCard (PP, D-12): the desktop-parity card row — icon + name +
 * endpoint + "current" badge, with the hover action group. PP r2: activation
 * lives on a dedicated 启用 button (cc-switch style), never the card body.
 * PP r3 (user rulings): official-direct entries (no base_url) render as a
 * pinned pseudo-card whose 启用 IS the cancel-proxy path; the current
 * provider gets NO 停用 button (to stop it, enable another/official).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { CcSwitchProvider } from "../../types";

const { t } = useI18n();
const props = defineProps<{
  provider: CcSwitchProvider;
  busy: boolean;
}>();
const emit = defineEmits<{
  (e: "activate"): void;
  (e: "edit"): void;
  (e: "remove"): void;
}>();

/** Official-direct entry: cc-switch keeps these always visible (placeholder
 * rows carry no base_url); activating one restores the official config. */
const official = computed(() => !props.provider.base_url);
/** Icon resolution: the db icon is a BRAND ID for the official rows
 * ('anthropic' / 'openai' — rendered as inline SVG marks, 手测 r6#2: the
 * raw id leaking through the r5 boundary fix rendered as literal text) or a
 * free-form glyph; anything else falls to the first character of the name. */
const brand = computed(() =>
  props.provider.icon === "anthropic" || props.provider.icon === "openai"
    ? props.provider.icon : "");
const displayName = computed(() =>
  official.value ? t("ccswitch.officialDirect") : (props.provider.name || props.provider.id));
const glyph = computed(() => props.provider.icon && !brand.value
  ? props.provider.icon
  : displayName.value.trim().charAt(0).toUpperCase());
const glyphColor = computed(() => props.provider.icon_color || "");
/** PP r3: the current provider has no 停用 button — switching happens by
 * enabling another entry (or the official one). */
const startable = computed(() => !props.provider.is_current);
/** 手测 r5#3 (2026-09-12): hot-swap makes the effective model invisible in
 * the CLI (it displays its startup name forever) — the CURRENT card states
 * what requests actually run on: the primary slot (claude role env) or the
 * row's model (codex). */
const actualModel = computed(() => {
  if (!props.provider.is_current || official.value) return "";
  const env = props.provider.role_env ?? {};
  return env.ANTHROPIC_MODEL || env.ANTHROPIC_DEFAULT_OPUS_MODEL
    || props.provider.model || "";
});
</script>

<template>
  <div class="card" :class="{ current: provider.is_current }">
    <span class="glyph" :style="glyphColor ? { color: glyphColor } : {}" aria-hidden="true">
      <!-- Claude's 8-spoke starburst mark (claude-official rows). -->
      <svg v-if="brand === 'anthropic'" width="18" height="18" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
        <path d="M15.2 12H22M14.26 14.26l4.81 4.81M12 15.2V22M9.74 14.26l-4.81 4.81M8.8 12H2M9.74 9.74L4.93 4.93M12 8.8V2M14.26 9.74l4.81-4.81" />
      </svg>
      <!-- OpenAI's six-petal knot (codex-official rows). -->
      <svg v-else-if="brand === 'openai'" width="18" height="18" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="1.6">
        <ellipse cx="12" cy="12" rx="3.6" ry="10" />
        <ellipse cx="12" cy="12" rx="3.6" ry="10" transform="rotate(30 12 12)" />
        <ellipse cx="12" cy="12" rx="3.6" ry="10" transform="rotate(60 12 12)" />
        <ellipse cx="12" cy="12" rx="3.6" ry="10" transform="rotate(90 12 12)" />
        <ellipse cx="12" cy="12" rx="3.6" ry="10" transform="rotate(120 12 12)" />
        <ellipse cx="12" cy="12" rx="3.6" ry="10" transform="rotate(150 12 12)" />
      </svg>
      <template v-else>{{ glyph }}</template>
    </span>
    <span class="meta">
      <span class="name">
        {{ displayName }}
        <span v-if="provider.notes" class="note" :title="provider.notes">✎</span>
      </span>
      <span v-if="official" class="url">{{ t("ccswitch.officialDesc") }}</span>
      <span v-else class="url" :title="provider.base_url">{{ provider.base_url }}</span>
      <span v-if="actualModel" class="actual">{{ t("ccswitch.actualModel") }}：{{ actualModel }}</span>
    </span>
    <span v-if="provider.is_current" class="badge">{{ t("ccswitch.currentChip") }}</span>
    <span class="actions" @click.stop @keydown.stop>
      <button v-if="startable" class="start" :disabled="busy"
              :title="official ? t('ccswitch.cancelProxyHint') : t('ccswitch.activateHint')"
              @click="emit('activate')">
        <span class="tri" aria-hidden="true">▶</span>
        {{ t("ccswitch.enableBtn") }}
      </button>
      <template v-if="!official">
        <button class="edit" :disabled="busy" :title="t('ccswitch.edit')" @click="emit('edit')">✎</button>
        <button class="danger" :disabled="busy" :title="t('ccswitch.delete')" @click="emit('remove')">🗑</button>
      </template>
    </span>
  </div>
</template>

<style scoped>
.card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  background: var(--surface-2);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-normal) var(--ease),
              background-color var(--duration-normal) var(--ease);
}
/* PP r2 (user ruling): hover border matches the current-card highlight, and
 * the current card carries a subtle accent tint (cc-switch parity). */
.card:hover, .card:focus-within { border-color: var(--accent); }
.card.current { border-color: var(--accent); background: var(--accent-soft); }
.glyph {
  flex: none; width: 34px; height: 34px; border-radius: var(--radius-full);
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--surface-3); color: var(--text-2); font-size: var(--font-md);
}
.meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.name { font-size: var(--font-md); color: var(--text); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.note { color: var(--text-faint); margin-left: 4px; }
.url { font-size: var(--font-xs); color: var(--text-muted); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.actual { font-size: var(--font-xs); color: var(--accent); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
/* PP r3: rounded-rect tag, not a pill (the 50% radius read as an ellipse). */
.badge {
  flex: none; font-size: var(--font-xs); font-weight: 600;
  color: var(--accent-fg); background: var(--accent);
  border-radius: var(--radius-sm); padding: 1px 8px;
}
/* Desktop-parity hover group: actions sit on the card but only surface on
   hover/focus (touch devices get them permanently via media query). The
   启用 button leads, styled like the cc-switch desktop's primary action. */
.actions { display: none; gap: 4px; }
.card:hover .actions, .card:focus-within .actions { display: inline-flex; }
@media (hover: none) { .actions { display: inline-flex; } }
.actions button {
  min-width: 28px; min-height: 28px; padding: 0;
  background: var(--surface-3); color: var(--text-muted);
  border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; font-size: var(--font-sm);
}
.actions button:hover:not(:disabled) { color: var(--text); background: var(--surface-hover); }
.actions .start {
  background: var(--accent); color: var(--accent-fg);
  border-color: var(--accent); font-weight: 600; padding: 0 10px;
}
.actions .start .tri { font-size: var(--font-xs); margin-right: 4px; }
.actions .start:hover:not(:disabled) { filter: brightness(1.15); color: var(--accent-fg); }
.actions button.danger:hover:not(:disabled) { color: var(--error-fg); border-color: var(--error-border); }
.actions button:disabled { opacity: 0.45; cursor: default; }
</style>
