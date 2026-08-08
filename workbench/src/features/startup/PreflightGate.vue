<script setup lang="ts">
/** Preflight gate (02 §四): per-check pass/warn/fail + hard/config classification. */
import { computed } from "vue";
import type { PreflightReport, PreflightCheck } from "../../types";

const props = defineProps<{ report: PreflightReport }>();

const HARD_GATES = ["docker", "workspace"];
const CONFIG_GATES = ["image", "network", "runtime_conflict"];

function classify(id: string): string {
  if (HARD_GATES.includes(id)) return "hard";
  if (CONFIG_GATES.includes(id)) return "config";
  return "info";
}

function label(id: string): string {
  return { docker: "Docker", workspace: "Workspace", image: "镜像", network: "网络", runtime_conflict: "Runtime 冲突" }[id] ?? id;
}

const ordered = computed<PreflightCheck[]>(() => {
  const order = ["docker", "workspace", "image", "network", "runtime_conflict"];
  return [...props.report.checks].sort(
    (a, b) => order.indexOf(a.id) - order.indexOf(b.id)
  );
});

function statusText(c: PreflightCheck): string {
  return { pass: "通过", warn: "警告", fail: "失败" }[c.status] ?? c.status;
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
  padding: 8px 10px;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 4px;
}
.check {
  display: grid;
  grid-template-columns: 12px 110px 90px 60px 1fr;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #ccc;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #888;
}
.check[data-status="pass"] .dot { background: #4caf50; }
.check[data-status="warn"] .dot { background: #ffb300; }
.check[data-status="fail"] .dot { background: #e57373; }
.cat { color: #888; font-size: 11px; }
.state { color: #ddd; }
.code { color: #e57373; font-size: 11px; }
</style>
