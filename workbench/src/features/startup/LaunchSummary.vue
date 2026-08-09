<script setup lang="ts">
/** Launch summary (02 §七): preflight gate + inferred config + Start/Change/Cancel. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import PreflightGate from "./PreflightGate.vue";

const { t } = useI18n();
const store = useRuntimeStore();

const ACTION_KEY: Record<string, string> = {
  start: "summary.action.start",
  reuse: "summary.action.reuse",
  restart: "summary.action.restart",
  resolve_conflict: "summary.action.conflict",
};
const action = computed(() => store.preflight?.recommended_action ?? "start");
const actionText = computed(() => t(ACTION_KEY[action.value] ?? action.value));

function checkStatus(id: string): string {
  return store.preflight?.checks.find((c) => c.id === id)?.status ?? "pass";
}

const hardBlocking = computed(() => checkStatus("docker") === "fail" || checkStatus("workspace") === "fail");
const dockerDown = computed(() => checkStatus("docker") === "fail");
const imageMissing = computed(() => checkStatus("image") === "fail" && action.value !== "reuse");
const startEnabled = computed(
  () =>
    !!store.preflight &&
    ["start", "reuse", "restart"].includes(action.value) &&
    !hardBlocking.value &&
    !imageMissing.value
);

function changeSettings() {
  store.showAdvanced = !store.showAdvanced;
}

function onConfigChanged() {
  store.recomputePreflightNeeded();
}
</script>

<template>
  <div class="summary">
    <h2>{{ t("summary.title") }}</h2>
    <PreflightGate v-if="store.preflight" :report="store.preflight" />

    <div class="row"><span class="k">Workspace</span><span class="v">{{ store.workspace }}</span></div>
    <!-- G-08 (A-G08-1): no initial-agent picker; a fresh Start opens one Bash
         tab, more tabs are created dynamically via the + menu. -->
    <div class="row"><span class="k">Runtime</span><span class="v">{{ actionText }}</span></div>

    <div v-if="store.showAdvanced" class="advanced">
      <div class="row">
        <span class="k">Image</span>
        <input v-model="store.launch.image" @change="onConfigChanged" />
      </div>
      <div class="row">
        <span class="k">Network</span>
        <select v-model="store.launch.network" @change="onConfigChanged">
          <option value="direct">direct</option>
          <option value="proxy">proxy</option>
        </select>
      </div>
      <div class="row">
        <span class="k">Scope</span>
        <select v-model="store.launch.scope" @change="onConfigChanged">
          <option value="project">project</option>
          <option value="temporary">temporary</option>
        </select>
      </div>
    </div>

    <p v-if="imageMissing" class="gate-msg config">{{ t("summary.imageMissing") }}</p>
    <p v-if="dockerDown" class="gate-msg hard">
      {{ store.dockerStarting ? t("summary.dockerStarting") : t("summary.dockerDown") }}
    </p>
    <p v-else-if="hardBlocking" class="gate-msg hard">{{ t("summary.hardBlocked") }}</p>
    <p v-else-if="action === 'resolve_conflict'" class="gate-msg hard">{{ t("summary.conflictGate") }}</p>

    <p v-if="store.restorableLayout" class="gate-msg resume">{{ t("summary.restorable") }}</p>

    <div class="actions">
      <button class="primary" :disabled="!startEnabled" @click="store.startFromSummary()">{{ t("summary.start") }}</button>
      <button v-if="store.restorableLayout" class="primary" :disabled="!startEnabled" @click="store.resumeLayout()">{{ t("summary.restoreLayout") }}</button>
      <button v-if="dockerDown" class="primary" :disabled="store.dockerStarting" @click="store.startDockerAndRepreflight()">
        {{ store.dockerStarting ? t("summary.startingDocker") : t("summary.startDocker") }}
      </button>
      <button @click="changeSettings">{{ store.showAdvanced ? t("summary.toggleSettings") : t("summary.changeSettings") }}</button>
      <button v-if="imageMissing" class="danger" @click="store.startBuild(store.launch.image)">{{ t("summary.buildImage") }}</button>
      <button @click="store.backToPicker()">Cancel</button>
    </div>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  color: #ccc;
  overflow: auto;
}
h2 { margin: 0 0 4px; font-size: 15px; }
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.k { width: 90px; color: #888; }
.v { color: #ddd; word-break: break-all; }
input, select {
  background: #252526;
  color: #ddd;
  border: 1px solid #444;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 13px;
  flex: 1;
  min-width: 0;
}
.advanced {
  padding: 8px;
  background: #252526;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gate-msg { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin: 0; }
.gate-msg.config { background: #3a3220; color: #e0c97a; }
.gate-msg.hard { background: #4a2626; color: #e0b0b0; }
.gate-msg.resume { background: #1e2e3a; color: #9cc4e0; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: #3c3c3c; }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: #0e639c; border-color: #0e639c; }
button.primary:hover:not(:disabled) { background: #1177bb; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
</style>
