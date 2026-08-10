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
/** Genuinely missing image (error_code IMAGE_NOT_FOUND, not Docker-unreachable).
 * G-14 (2026-08-10 bugfix): unlike imageMissing this ignores recommended_action,
 * so a matching existing runtime (action=reuse) does NOT hide the build button -
 * the gate would show 镜像失败 with no recovery path. */
const imageNotFound = computed(() => {
  const c = store.preflight?.checks.find((c) => c.id === "image");
  return c?.status === "fail" && c?.error_code === "AISC_ERR_IMAGE_NOT_FOUND";
});
/** Missing image on a non-reuse path - disables Start (reuse keeps the existing
 * container, so a missing tag does not block it). */
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

    <p v-if="imageNotFound" class="gate-msg config">{{ t("summary.imageMissing") }}</p>
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
      <button v-if="imageNotFound" class="danger" @click="store.startBuild(store.launch.image)">{{ t("summary.buildImage") }}</button>
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
  color: var(--text-2);
  overflow: auto;
}
h2 { margin: 0 0 4px; font-size: 15px; }
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.k { width: 90px; color: var(--text-muted); }
.v { color: var(--text-2); word-break: break-all; }
input, select {
  background: var(--surface);
  color: var(--text-2);
  border: 1px solid var(--border-2);
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 13px;
  flex: 1;
  min-width: 0;
}
.advanced {
  padding: 8px;
  background: var(--surface);
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gate-msg { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin: 0; }
.gate-msg.config { background: var(--warn-bg); color: var(--warn-fg); }
.gate-msg.hard { background: var(--error-bg); color: var(--error-fg); }
.gate-msg.resume { background: var(--info-bg); color: var(--info); }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button:hover:not(:disabled) { background: var(--surface-hover); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); }
button.primary:hover:not(:disabled) { background: var(--accent-hover); }
button.danger { background: var(--error-bg); border-color: var(--error-border); }
</style>
