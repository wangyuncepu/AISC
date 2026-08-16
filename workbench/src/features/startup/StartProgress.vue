<script setup lang="ts">
/** Start progress (02 §八): elapsed + Cancel; after cancel, inspect -> keep/stop. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";

const { t } = useI18n();
const store = useRuntimeStore();

const elapsedSec = computed(() => (store.startElapsedMs / 1000).toFixed(1));
const cancelledSnap = computed(() => store.cancelInspect);
</script>

<template>
  <div class="progress">
    <template v-if="!cancelledSnap">
      <p class="msg">{{ t("start.msg", { sec: elapsedSec }) }}</p>
      <p class="hint">{{ t("start.hint") }}</p>
      <button class="danger" @click="store.cancelStart()">Cancel</button>
    </template>
    <template v-else>
      <p class="msg">{{ t("start.cancelled", { state: cancelledSnap.state }) }}</p>
      <p v-if="cancelledSnap.state === 'not_found'" class="hint">{{ t("start.cancelledNotFound") }}</p>
      <p v-else class="hint">{{ t("start.cancelledExists", { name: cancelledSnap.container_name }) }}</p>
      <div class="actions">
        <button v-if="cancelledSnap.state === 'not_found'" class="primary" @click="store.keepCancelledRuntime()">{{ t("start.backToSummary") }}</button>
        <template v-else>
          <button class="primary" @click="store.keepCancelledRuntime()">{{ t("start.keep") }}</button>
          <button class="danger" @click="store.stopCancelledRuntime()">{{ t("start.stopRuntime") }}</button>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  color: var(--text-2);
}
.msg { font-size: var(--font-base); margin: 0; }
.hint { font-size: var(--font-sm); color: var(--text-muted); margin: 0; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: var(--radius-md);
  padding: 6px 14px; font-size: var(--font-md); cursor: pointer;
}
button.primary { background: var(--accent); border-color: var(--accent); }
button.danger { background: var(--error-bg); border-color: var(--error-border); }
</style>
