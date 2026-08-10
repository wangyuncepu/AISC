<script setup lang="ts">
/**
 * One-click diagnosis dialog (G-13, Step 12; 02 §五 F-4).
 *
 * Renders ONLY the structured `data.host.checks/summary` and per-check
 * `hint`/`detail` (redacted Rust-side) - raw stdout/stderr is never displayed
 * (A-G13-1). Non-zero doctor exits that still produced a report keep the
 * failed checks visible; transport/protocol failures show a structured
 * WorkbenchError with a retry (A-G13-1/A-G13-2). The run button is disabled
 * while a doctor is in flight (A-G13-3).
 */
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useDoctorStore } from "../../stores/doctor";
import type { DoctorStatus } from "../../types";

const { t } = useI18n();
const store = useDoctorStore();
const panel = ref<HTMLElement | null>(null);

const STATUS_LABEL_KEY: Record<DoctorStatus, string> = {
  pass: "doctor.status.pass",
  warn: "doctor.status.warn",
  fail: "doctor.status.fail",
  skip: "doctor.status.skip",
};

onMounted(() => {
  panel.value?.focus();
  window.addEventListener("keydown", onKeydown);
});

onUnmounted(() => window.removeEventListener("keydown", onKeydown));

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") store.closeDialog();
}

function onOverlayDown(e: MouseEvent) {
  if (e.target === e.currentTarget) store.closeDialog();
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayDown">
    <section ref="panel" class="panel" role="dialog" aria-modal="true" :aria-label="t('doctor.title')" tabindex="-1">
      <header class="head">
        <h2>{{ t("doctor.title") }}</h2>
      </header>

      <!-- running -->
      <div v-if="store.status === 'running'" class="body">
        <p class="running">{{ t("doctor.running") }}</p>
      </div>

      <!-- transport / protocol failure: structured WorkbenchError only -->
      <div v-else-if="store.status === 'error'" class="body">
        <p class="err-title">{{ t("doctor.failed") }}</p>
        <p class="err">{{ store.error?.message }}</p>
        <p class="code">[{{ store.error?.code }}]</p>
        <p v-if="store.error?.technical_detail" class="detail">{{ store.error.technical_detail }}</p>
        <p class="hint-text">{{ t("doctor.keepErrorPage") }}</p>
      </div>

      <!-- done: checks + summary -->
      <div v-else-if="store.status === 'done' && store.report" class="body">
        <div class="summary" :data-fail="store.hasFailures" :data-warn="store.hasWarnings && !store.hasFailures">
          <span class="sum-item fail">{{ store.report.summary.failures }} {{ t("doctor.sum.fail") }}</span>
          <span class="sum-item warn">{{ store.report.summary.warnings }} {{ t("doctor.sum.warn") }}</span>
          <span class="sum-item skip">{{ store.report.summary.skipped }} {{ t("doctor.sum.skip") }}</span>
          <span class="sum-item pass">{{ store.report.summary.passed }} {{ t("doctor.sum.pass") }}</span>
        </div>

        <ul class="checks">
          <li v-for="c in store.report.checks" :key="c.name" class="check" :data-status="c.status">
            <div class="c-row">
              <span class="c-status" :data-status="c.status">{{ t(STATUS_LABEL_KEY[c.status] ?? "doctor.status.skip") }}</span>
              <span class="c-name">{{ c.name }}</span>
            </div>
            <div class="c-message">{{ c.message }}</div>
            <div v-if="c.detail" class="c-detail">{{ c.detail }}</div>
            <div v-if="c.hint" class="c-hint">{{ c.hint }}</div>
          </li>
        </ul>
      </div>

      <!-- idle (fresh dialog before the auto-run settles) -->
      <div v-else class="body">
        <p class="muted">{{ t("doctor.idle") }}</p>
      </div>

      <footer class="foot">
        <button class="primary" :disabled="store.running" @click="store.run()">
          {{ store.status === "error" ? t("doctor.retry") : t("doctor.run") }}
        </button>
        <button :disabled="store.running" @click="store.closeDialog()">{{ t("doctor.close") }}</button>
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
  width: 620px; max-width: 92vw; max-height: 84vh; overflow: auto;
  background: #252526; color: #ccc; border: 1px solid #444; border-radius: 6px;
  outline: none; display: flex; flex-direction: column;
}
.head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #333;
}
.head h2 { margin: 0; font-size: 15px; color: #ddd; }
.body { padding: 12px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 16px; border-top: 1px solid #333;
}
.running { color: #cca84a; }
.muted { color: #888; }
.err-title { color: #e57373; font-weight: 600; }
.err { color: #ddd; }
.code { color: #888; font-family: monospace; font-size: 11px; }
.detail { color: #888; font-size: 12px; word-break: break-all; }
.hint-text { color: #777; font-size: 12px; }

.summary { display: flex; gap: 12px; font-size: 13px; flex-wrap: wrap; }
.summary[data-fail="true"] { padding: 8px 10px; background: #3a2020; border: 1px solid #6b3636; border-radius: 4px; }
.summary[data-fail="false"][data-warn="true"] { padding: 8px 10px; background: #3a3320; border: 1px solid #6b5d36; border-radius: 4px; }
.sum-item.fail { color: #e57373; }
.sum-item.warn { color: #e0c97a; }
.sum-item.skip { color: #888; }
.sum-item.pass { color: #4caf50; }

.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.check {
  border: 1px solid #3a3a3a; border-radius: 4px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px; font-size: 12px;
}
.check[data-status="fail"] { border-left: 3px solid #e57373; }
.check[data-status="warn"] { border-left: 3px solid #e0c97a; }
.check[data-status="pass"] { border-left: 3px solid #4caf50; }
.check[data-status="skip"] { border-left: 3px solid #555; }
.c-row { display: flex; align-items: center; gap: 8px; }
.c-status { font-size: 10px; text-transform: uppercase; padding: 1px 6px; border-radius: 3px; }
.c-status[data-status="pass"] { background: #1e3a24; color: #4caf50; }
.c-status[data-status="warn"] { background: #3a3320; color: #e0c97a; }
.c-status[data-status="fail"] { background: #3a2020; color: #e57373; }
.c-status[data-status="skip"] { background: #2a2a2a; color: #888; }
.c-name { color: #ddd; font-family: monospace; }
.c-message { color: #bbb; }
.c-detail { color: #888; word-break: break-all; }
.c-hint { color: #9cdcfe; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover:not(:disabled) { background: #1177bb; }
</style>
