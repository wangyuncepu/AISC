<script setup lang="ts">
/** Build progress (02 §四, 05 §4.1): opaque build.output log + Cancel.
 *  In-memory only, not parsed for percentage (05 §4.1.3/§4.1.5). */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRuntimeStore } from "../../stores/runtime";

const store = useRuntimeStore();
const logEl = ref<HTMLPreElement | null>(null);
const elapsedMs = ref(0);
let timer: number | null = null;

const statusText = computed(
  () => ({ building: "构建中…", complete: "构建完成", failed: "构建失败", cancelled: "已取消", idle: "" }[store.buildStatus] ?? "")
);
const elapsedSec = computed(() => (elapsedMs.value / 1000).toFixed(1));

onMounted(() => {
  const begun = Date.now();
  timer = window.setInterval(() => {
    elapsedMs.value = Date.now() - begun;
  }, 200);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});

// Auto-scroll the log to the bottom on new output.
watch(
  () => store.buildLog,
  () => {
    nextTick(() => {
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight;
    });
  }
);
</script>

<template>
  <div class="build">
    <div class="head">
      <span class="title">构建镜像 {{ store.buildTag }}</span>
      <span class="state" :data-state="store.buildStatus">{{ statusText }}</span>
      <span v-if="store.buildStatus === 'building'" class="elapsed">{{ elapsedSec }}s</span>
    </div>
    <pre ref="logEl" class="log">{{ store.buildLog || "(等待 Docker 输出… 初始化可能需数十秒)" }}</pre>
    <p v-if="store.buildError" class="err">{{ store.buildError.message }}</p>
    <div class="actions">
      <button v-if="store.buildStatus === 'building'" class="danger" @click="store.cancelBuild()">Cancel</button>
      <button v-else class="primary" @click="store.backToSummaryFromBuild()">返回摘要</button>
    </div>
  </div>
</template>

<style scoped>
.build {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px;
  gap: 8px;
  color: #ccc;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.title { font-weight: 600; }
.state { font-size: 12px; color: #888; }
.elapsed { font-size: 12px; color: #888; margin-left: auto; }
.state[data-state="complete"] { color: #4caf50; }
.state[data-state="failed"], .state[data-state="cancelled"] { color: #e57373; }
.log {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  padding: 8px;
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #ddd;
}
.err { font-size: 12px; color: #e57373; margin: 0; }
.actions { display: flex; gap: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button.primary { background: #0e639c; border-color: #0e639c; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
</style>
