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
  background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); border-radius: 6px;
  outline: none; display: flex; flex-direction: column;
}
.head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.head h2 { margin: 0; font-size: 15px; color: var(--text-2); }
.body { padding: 12px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 16px; border-top: 1px solid var(--border);
}
.running { color: var(--warn); }
.muted { color: var(--text-muted); }
.err-title { color: var(--error); font-weight: 600; }
.err { color: var(--text-2); }
.code { color: var(--text-muted); font-family: monospace; font-size: 11px; }
.detail { color: var(--text-muted); font-size: 12px; word-break: break-all; }
.hint-text { color: var(--text-muted); font-size: 12px; }

.summary { display: flex; gap: 12px; font-size: 13px; flex-wrap: wrap; }
.summary[data-fail="true"] { padding: 8px 10px; background: var(--error-bg); border: 1px solid var(--error-border); border-radius: 4px; }
.summary[data-fail="false"][data-warn="true"] { padding: 8px 10px; background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 4px; }
.sum-item.fail { color: var(--error); }
.sum-item.warn { color: var(--warn-fg); }
.sum-item.skip { color: var(--text-muted); }
.sum-item.pass { color: var(--success); }

.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.check {
  border: 1px solid var(--border-2); border-radius: 4px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px; font-size: 12px;
}
.check[data-status="fail"] { border-left: 3px solid var(--error); }
.check[data-status="warn"] { border-left: 3px solid var(--warn-fg); }
.check[data-status="pass"] { border-left: 3px solid var(--success); }
.check[data-status="skip"] { border-left: 3px solid var(--border-strong); }
.c-row { display: flex; align-items: center; gap: 8px; }
.c-status { font-size: 10px; text-transform: uppercase; padding: 1px 6px; border-radius: 3px; }
.c-status[data-status="pass"] { background: var(--success-bg); color: var(--success); }
.c-status[data-status="warn"] { background: var(--warn-bg); color: var(--warn-fg); }
.c-status[data-status="fail"] { background: var(--error-bg); color: var(--error); }
.c-status[data-status="skip"] { background: var(--surface-2); color: var(--text-muted); }
.c-name { color: var(--text-2); font-family: monospace; }
.c-message { color: var(--text-muted); }
.c-detail { color: var(--text-muted); word-break: break-all; }
.c-hint { color: var(--info); }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: var(--surface-hover); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
</style>
