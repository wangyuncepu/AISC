<script setup lang="ts">
/** Preflight gate (02 §四): per-check pass/warn/fail + hard/config classification. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { PreflightReport, PreflightCheck } from "../../types";

const { t } = useI18n();
const props = defineProps<{ report: PreflightReport }>();

const HARD_GATES = ["docker", "workspace"];
const CONFIG_GATES = ["image", "network", "runtime_conflict"];

const CHECK_LABEL_KEY: Record<string, string> = {
  docker: "gate.check.docker",
  workspace: "gate.check.workspace",
  image: "gate.check.image",
  network: "gate.check.network",
  runtime_conflict: "gate.check.runtimeConflict",
};

function classify(id: string): string {
  if (HARD_GATES.includes(id)) return "hard";
  if (CONFIG_GATES.includes(id)) return "config";
  return "info";
}

function label(id: string): string {
  return t(CHECK_LABEL_KEY[id] ?? id);
}

const ordered = computed<PreflightCheck[]>(() => {
  const order = ["docker", "workspace", "image", "network", "runtime_conflict"];
  return [...props.report.checks].sort(
    (a, b) => order.indexOf(a.id) - order.indexOf(b.id)
  );
});

function statusText(c: PreflightCheck): string {
  return { pass: t("gate.status.pass"), warn: t("gate.status.warn"), fail: t("gate.status.fail") }[c.status] ?? c.status;
}
</script>

<template>
  <div class="gate">
    <div v-for="c in ordered" :key="c.id" class="check" :data-status="c.status">
      <span class="dot" />
      <span class="name">{{ label(c.id) }}</span>
      <span class="cat">{{ classify(c.id) === "hard" ? "Hard gate" : classify(c.id) === "config" ? "Config gate" : "Info" }}</span>
      <span class="state">{{ statusText(c) }}</span>
      <span v-if="c.error_code" class="code">{{ c.error_code }}</span>
    </div>
  </div>
</template>

<style scoped>
.gate {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-lg);
}
.check {
  display: grid;
  grid-template-columns: 12px 110px 90px 60px 1fr;
  align-items: center;
  gap: 8px;
  font-size: var(--font-sm);
  color: var(--text-2);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--text-muted);
}
.check[data-status="pass"] .dot { background: var(--success); }
.check[data-status="warn"] .dot { background: var(--warn); }
.check[data-status="fail"] .dot { background: var(--error); }
.cat { color: var(--text-muted); font-size: var(--font-xs); }
.state { color: var(--text-2); }
.code { color: var(--error); font-size: var(--font-xs); }
</style>
