<script setup lang="ts">
/**
 * runtime-lifecycle-ux Stage 4 (01 §3.1): the old conflict manager became
 * the minimal BLOCK page. Stale runtimes never land here — reconcile
 * auto-recycled them before preflight — so only two real blockers remain:
 * another ACTIVE Workbench instance holding the lease, and ownership that
 * cannot be verified. Exactly three actions (重新检测 / 返回 / 打开诊断);
 * the destructive stop/remove/force-remove list is gone — advanced
 * cleanup lives in the Runtime sidebar / Doctor (task 7).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { useDoctorStore } from "../../stores/doctor";

const { t } = useI18n();
const store = useRuntimeStore();
const doctor = useDoctorStore();

const classification = computed(() => store.reconcile?.classification ?? "");

const titleKey = computed(() => {
  if (classification.value === "active_other_instance") return "conflict.title.otherInstance";
  if (classification.value === "unknown_owner") return "conflict.title.unknownOwner";
  return "conflict.title.blocked";
});

const descKey = computed(() => {
  if (classification.value === "active_other_instance") return "conflict.desc.otherInstance";
  if (classification.value === "unknown_owner") return "conflict.desc.unknownOwner";
  return "conflict.desc.blocked";
});

/** unknown_owner: how many unverifiable resources sit in this workspace
 * (reported only — nothing is deleted without proof of ownership). */
const unverifiedCount = computed(() =>
  classification.value === "unknown_owner" ? store.conflicts.length : 0
);

/** S8a (VM retest feedback #1): the generic blocked page shows the backend's
 * own reason line inline instead of hiding it behind 诊断. A fact the
 * reconcile already reported is free to display; only UNREPORTED blockers
 * stay generic. */
const detailText = computed(
  () => store.reconcile?.technical_detail ?? store.conflictError?.technical_detail ?? ""
);
</script>

<template>
  <div class="conflict">
    <h2>{{ t(titleKey) }}</h2>
    <p class="hint">{{ t(descKey) }}</p>
    <p v-if="unverifiedCount > 0" class="hint sub" data-testid="unverified-count">
      {{ t("conflict.unverifiedCount", { count: unverifiedCount }) }}
    </p>
    <p v-if="detailText" class="hint sub detail" data-testid="blocked-detail">{{ detailText }}</p>

    <div class="actions">
      <button class="primary" @click="store.retryFromConflict()">{{ t("conflict.recheck") }}</button>
      <button @click="store.backToPicker()">{{ t("conflict.back") }}</button>
      <button @click="doctor.openDialog()">{{ t("conflict.diagnostics") }}</button>
    </div>
  </div>
</template>

<style scoped>
.conflict {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  color: var(--text-2);
}
.conflict h2 { color: var(--text-2); margin: 0; }
.hint { font-size: var(--font-sm); color: var(--text-muted); max-width: 480px; text-align: center; margin: 0; }
.hint.sub { font-size: var(--font-xs); }
.detail { max-width: 560px; overflow-wrap: anywhere; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); color: var(--text-2); border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  padding: 0 var(--space-3); font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
button:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
button.primary { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
</style>
