<script setup lang="ts">
/**
 * v2.1.7 S7 (④): the shared change badge — 变更类型 × 来源.
 *
 * Two orthogonal facts, each rendered only when the backing data exists
 * (Gate-S7: never guess):
 *  - type: created | modified | deleted | renamed (icon + shape + hue + text;
 *    never color alone, A-21774);
 *  - source: agent (manifest-attributed, shows the agent name) |
 *    inferred (2.1.9 T3c: watcher-derived, attributed to the live provider
 *    session — dashed border like unattributed, but carries the agent name
 *    and an explicit "inferred" label) | unattributed (watcher-derived).
 * `detail` carries fact-qualified extras: for an attributed rename this is
 * the previous path (a real recorded fact); for an unattributed rename it is
 * the honest "original name unknown" note.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  type: "created" | "modified" | "deleted" | "renamed";
  source: "agent" | "inferred" | "unattributed";
  agent?: string;
  /** Recorded previous path (attributed rename) or the unknown marker. */
  detail?: string | null;
}>();

const { t } = useI18n();

const ICONS: Record<string, string> = {
  created: "＋",
  modified: "✎",
  deleted: "−",
  renamed: "⇄",
};
const icon = computed(() => ICONS[props.type] ?? "?");
const text = computed(() => t(`explorer.badge.${props.type}`));
const aria = computed(() => {
  const who =
    props.source === "agent"
      ? t("explorer.badge.sourceAgent", { agent: props.agent ?? "" })
      : props.source === "inferred"
      ? t("explorer.badge.sourceInferred", { agent: props.agent ?? "" })
      : t("explorer.badge.sourceUnattributed");
  return props.detail
    ? `${who} · ${text.value} · ${props.detail}`
    : `${who} · ${text.value}`;
});
const tooltip = computed(() => {
  if (
    props.type === "renamed" &&
    (props.source === "unattributed" || props.source === "inferred")
  ) {
    return t("explorer.badge.renameUnknownTip");
  }
  return aria.value;
});
</script>

<template>
  <span
    class="change-badge"
    :data-type="type"
    :data-source="source"
    role="img"
    :aria-label="aria"
    :title="tooltip"
  >
    <span class="badge-icon" aria-hidden="true">{{ icon }}</span>
    <span class="badge-text">{{ text }}</span>
    <span v-if="source === 'agent' || source === 'inferred'" class="badge-agent" aria-hidden="true">{{
      agent
    }}</span>
  </span>
</template>

<style scoped>
.change-badge {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: var(--font-xs);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  border: 1px solid transparent;
  flex: none;
}
.badge-icon { line-height: 1; }
.badge-agent {
  color: var(--text-faint);
  max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Type hues pair with icons+text so color is never the only signal. */
.change-badge[data-type="created"] { color: var(--success); border-color: var(--border); }
.change-badge[data-type="modified"] { color: var(--info); border-color: var(--border); }
.change-badge[data-type="deleted"] { color: var(--error); border-color: var(--error-border, var(--border)); }
.change-badge[data-type="renamed"] { color: var(--warn-fg); border-color: var(--warn-border, var(--border)); }
.change-badge[data-source="unattributed"] { border-style: dashed; }
.change-badge[data-source="agent"] { background: var(--accent-soft); }
/* 2.1.9 T3c: inferred = agent-colored (soft bg + name) but DASHED — system
 * detection during that agent's session, not a manifest fact. */
.change-badge[data-source="inferred"] {
  border-style: dashed;
  background: var(--accent-soft);
}
</style>
