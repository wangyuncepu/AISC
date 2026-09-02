<script setup lang="ts">
/**
 * ProviderCard (PP, D-12): the desktop-parity card row — icon + name +
 * endpoint + "current" badge, with the hover action group (activate / edit /
 * delete) the cc-switch desktop shows on non-current entries. The whole card
 * body activates (current card = the cancel-proxy affordance, IDEA-4 r3).
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

/** Icon resolution: the db icon glyph (with its color) or the first
 * character of the name as a neutral round badge. */
const glyph = computed(() => props.provider.icon || (props.provider.name || "?").trim().charAt(0).toUpperCase());
const glyphColor = computed(() => props.provider.icon_color || "");
const canCancel = computed(() => props.provider.is_current && Boolean(props.provider.base_url));
</script>

<template>
  <div
    class="card"
    :class="{ current: provider.is_current, cancelable: canCancel }"
    :title="provider.is_current
      ? t('ccswitch.cancelProxyHint')
      : provider.base_url ? t('ccswitch.activateHint') : ''"
    role="button"
    tabindex="0"
    @click="emit('activate')"
    @keydown.enter.prevent="emit('activate')"
  >
    <span class="glyph" :style="glyphColor ? { color: glyphColor } : {}"
          aria-hidden="true">{{ glyph }}</span>
    <span class="meta">
      <span class="name">
        {{ provider.name || provider.id }}
        <span v-if="provider.notes" class="note" :title="provider.notes">✎</span>
      </span>
      <span class="url" :title="provider.base_url">{{ provider.base_url || t("ccswitch.officialDirect") }}</span>
    </span>
    <span v-if="provider.is_current" class="badge">{{ t("ccswitch.currentChip") }}</span>
    <span class="actions" @click.stop @keydown.stop>
      <button :disabled="busy" :title="t('ccswitch.edit')" @click="emit('edit')">✎</button>
      <button class="danger" :disabled="busy" :title="t('ccswitch.delete')" @click="emit('remove')">🗑</button>
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
  cursor: pointer;
  transition: border-color var(--duration-normal) var(--ease),
              background-color var(--duration-normal) var(--ease);
}
.card:hover, .card:focus-visible { background: var(--surface-hover); }
.card:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
.card.current { border-color: var(--success); }
.card.cancelable:hover { border-color: var(--warn); }
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
.badge {
  flex: none; font-size: var(--font-xs); color: var(--success);
  background: var(--success-bg); border-radius: var(--radius-full);
  padding: 1px 8px;
}
/* Desktop-parity hover group: actions sit on the card but only surface on
   hover/focus (touch devices get them permanently via media query). */
.actions { display: none; gap: 4px; }
.card:hover .actions, .card:focus-visible .actions, .card:focus-within .actions { display: inline-flex; }
@media (hover: none) { .actions { display: inline-flex; } }
.actions button {
  min-width: 28px; min-height: 28px; padding: 0;
  background: var(--surface-3); color: var(--text-muted);
  border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; font-size: var(--font-sm);
}
.actions button:hover:not(:disabled) { color: var(--text); background: var(--surface-hover); }
.actions button.danger:hover:not(:disabled) { color: var(--error-fg); border-color: var(--error-border); }
.actions button:disabled { opacity: 0.45; cursor: default; }
</style>
