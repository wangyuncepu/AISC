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
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { confirm, save } from "@tauri-apps/plugin-dialog";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { useDoctorStore } from "../../stores/doctor";
import { useDialogA11y } from "../../composables/useDialogA11y";
import type { DoctorStatus, LogEvent } from "../../types";

const { t } = useI18n();
const store = useDoctorStore();
const panel = ref<HTMLElement | null>(null);

const STATUS_LABEL_KEY: Record<DoctorStatus, string> = {
  pass: "doctor.status.pass",
  warn: "doctor.status.warn",
  fail: "doctor.status.fail",
  skip: "doctor.status.skip",
};

// Stage 6 (UX-03): focus trap + Escape + opener restore.
useDialogA11y(panel, () => store.closeDialog());

// --- Stage 6 (REL-01): recent op traces + redacted diagnostic bundle ---
// The IPC lives in the doctor store (F-A01: components never import fact
// commands directly); this view only builds the messages.
const traces = computed(() => store.traces);
const exporting = ref(false);
const exportMsg = ref<string | null>(null);
const exportOk = ref(true);

async function exportBundle() {
  // D6-06: manifest (allowlist) shown before writing.
  const ok = await confirm(t("doctor.exportConfirm"));
  if (!ok) return;
  const path = await save({
    defaultPath: `aisc-diagnostic-${Date.now()}.json`,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (!path) return;
  exporting.value = true;
  exportMsg.value = null;
  const result = await store.exportDiagnostic(path);
  exportOk.value = result !== null;
  exportMsg.value = result ? t("doctor.exported", { path: result }) : t("doctor.exportFailed");
  exporting.value = false;
}

onMounted(async () => {
  panel.value?.focus();
  await Promise.all([store.loadTraces(), store.loadLogs()]);
});

// --- lifecycle-logging (P3): recent log tail, collapsed by default ---
const logs = computed(() => store.logs);
const copied = ref(false);

/** One compact line per event (same shape as `aisc logs show --format text`). */
function logLine(e: LogEvent): string {
  const extras: string[] = [];
  if (e.run_id) extras.push(`run=${String(e.run_id).slice(0, 13)}`);
  for (const key of ["action", "command", "phase", "container", "outcome",
    "exit_code", "duration_ms", "error_code", "state", "detail"] as const) {
    const v = e[key];
    if (v !== undefined && v !== null) extras.push(`${key}=${String(v)}`);
  }
  return `${String(e.ts).slice(0, 19)} ${e.level.toUpperCase()} ${e.source} ${e.event}  ${extras.join(" ")}`.trimEnd();
}

async function copyLogs(): Promise<void> {
  try {
    await writeText(logs.value.map(logLine).join("\n"));
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    copied.value = false;
  }
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

      <!-- Stage 6 (REL-01): recent operation timings (dev layer) -->
      <details v-if="traces.length" class="traces">
        <summary>{{ t("doctor.traces") }}</summary>
        <ul>
          <li v-for="op in traces.slice(-12).reverse()" :key="op.operationId" class="trace-row">
            <span class="t-phase">{{ op.phase }}</span>
            <span class="t-dur">{{ op.durationMs }}ms</span>
            <span class="t-out" :data-out="op.outcome">{{ op.outcome }}</span>
            <span v-if="op.errorCode" class="t-code">{{ op.errorCode }}</span>
          </li>
        </ul>
      </details>

      <!-- lifecycle-logging (P3): recent timeline tail, collapsed by default -->
      <details v-if="logs.length" class="logs">
        <summary>{{ t("doctor.logs") }}</summary>
        <button class="copy-logs" @click="copyLogs">
          {{ copied ? t("doctor.logsCopied") : t("doctor.copyLogs") }}
        </button>
        <pre class="log-lines">{{ logs.map(logLine).join("\n") }}</pre>
      </details>

      <p v-if="exportMsg" class="export-msg" :data-err="!exportOk">{{ exportMsg }}</p>

      <footer class="foot">
        <button class="primary" :disabled="store.running" @click="store.run()">
          {{ store.status === "error" ? t("doctor.retry") : t("doctor.run") }}
        </button>
        <button :disabled="exporting" @click="exportBundle">{{ t("doctor.export") }}</button>
        <button :disabled="store.running" @click="store.closeDialog()">{{ t("doctor.close") }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: var(--scrim);
  display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog);
}
.panel {
  width: 620px; max-width: 92vw; max-height: 84vh; overflow: auto;
  background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); border-radius: var(--radius-lg);
  outline: none; display: flex; flex-direction: column;
}
.head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.head h2 { margin: 0; font-size: var(--font-lg); color: var(--text); }
.body { padding: 12px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 16px; border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
.traces { border-top: 1px solid var(--border); padding-top: 8px; }
.traces summary { cursor: pointer; color: var(--text-muted); font-size: var(--font-sm); user-select: none; }
.logs { border-top: 1px solid var(--border); padding-top: 8px; }
.logs summary { cursor: pointer; color: var(--text-muted); font-size: var(--font-sm); user-select: none; }
.copy-logs {
  margin-top: 6px; padding: 2px 10px; font-size: var(--font-xs);
}
.log-lines {
  margin: 6px 0 0; padding: 6px 8px; max-height: 200px; overflow: auto;
  background: var(--surface-2); border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  font-family: var(--font-mono); font-size: var(--font-xs); color: var(--text-muted);
  white-space: pre; user-select: text;
}
.traces ul { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 2px; font-size: var(--font-xs); }
.trace-row { display: flex; gap: 8px; align-items: center; color: var(--text-muted); }
.t-phase { color: var(--text-2); min-width: 120px; }
.t-dur { color: var(--info); min-width: 48px; text-align: right; }
.t-out[data-out="ok"] { color: var(--success); }
.t-out[data-out="error"] { color: var(--error); }
.t-code { color: var(--warn); font-family: var(--font-mono); }
.export-msg { font-size: var(--font-xs); color: var(--success); word-break: break-all; }
.export-msg[data-err="true"] { color: var(--error); }
.running { color: var(--warn); }
.muted { color: var(--text-muted); }
.err-title { color: var(--error); font-weight: 600; }
.err { color: var(--text-2); }
.code { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--font-xs); }
.detail { color: var(--text-muted); font-size: var(--font-sm); word-break: break-all; }
.hint-text { color: var(--text-muted); font-size: var(--font-sm); }

.summary { display: flex; gap: 12px; font-size: var(--font-md); flex-wrap: wrap; }
.summary[data-fail="true"] { padding: var(--space-2) var(--space-3); background: var(--error-bg); border: var(--border-w) solid var(--error-border); border-radius: var(--radius-sm); }
.summary[data-fail="false"][data-warn="true"] { padding: var(--space-2) var(--space-3); background: var(--warn-bg); border: var(--border-w) solid var(--warn-border); border-radius: var(--radius-sm); }
.sum-item.fail { color: var(--error); }
.sum-item.warn { color: var(--warn-fg); }
.sum-item.skip { color: var(--text-muted); }
.sum-item.pass { color: var(--success); }

.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.check {
  border: var(--border-w) solid var(--border-2); border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3);
  display: flex; flex-direction: column; gap: 2px; font-size: var(--font-sm);
}
.check[data-status="fail"] { border-left: 3px solid var(--error); }
.check[data-status="warn"] { border-left: 3px solid var(--warn-fg); }
.check[data-status="pass"] { border-left: 3px solid var(--success); }
.check[data-status="skip"] { border-left: 3px solid var(--border-strong); }
.c-row { display: flex; align-items: center; gap: 8px; }
.c-status { font-size: var(--font-xs); text-transform: uppercase; padding: 1px var(--space-2); border-radius: var(--radius-sm); }
.c-status[data-status="pass"] { background: var(--success-bg); color: var(--success); }
.c-status[data-status="warn"] { background: var(--warn-bg); color: var(--warn-fg); }
.c-status[data-status="fail"] { background: var(--error-bg); color: var(--error); }
.c-status[data-status="skip"] { background: var(--surface-2); color: var(--text-muted); }
.c-name { color: var(--text-2); font-family: var(--font-mono); }
.c-message { color: var(--text-muted); }
.c-detail { color: var(--text-muted); word-break: break-all; }
.c-hint { color: var(--info); }
button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--control-h-sm);
  background: var(--surface-3); color: var(--text-2);
  border: var(--border-w) solid var(--border); border-radius: var(--radius-sm);
  padding: 0 var(--space-3); font-size: var(--font-sm); cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
button:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
</style>
