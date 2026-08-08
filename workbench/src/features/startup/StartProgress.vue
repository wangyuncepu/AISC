<script setup lang="ts">
/** Start progress (02 §八): elapsed + Cancel; after cancel, inspect -> keep/stop. */
import { computed } from "vue";
import { useRuntimeStore } from "../../stores/runtime";

const store = useRuntimeStore();

const elapsedSec = computed(() => (store.startElapsedMs / 1000).toFixed(1));
const cancelledSnap = computed(() => store.cancelInspect);
</script>

<template>
  <div class="progress">
    <template v-if="!cancelledSnap">
      <p class="msg">正在启动 Runtime… {{ elapsedSec }}s</p>
      <p class="hint">CLI 未提供子阶段事件，仅显示经过时间。</p>
      <button class="danger" @click="store.cancelStart()">Cancel</button>
    </template>
    <template v-else>
      <p class="msg">启动已取消。Runtime 状态：{{ cancelledSnap.state }}</p>
      <p v-if="cancelledSnap.state === 'not_found'" class="hint">无残留资源。</p>
      <p v-else class="hint">Runtime 已创建（container {{ cancelledSnap.container_name }}）。</p>
      <div class="actions">
        <button v-if="cancelledSnap.state === 'not_found'" class="primary" @click="store.keepCancelledRuntime()">返回摘要</button>
        <template v-else>
          <button class="primary" @click="store.keepCancelledRuntime()">保留</button>
          <button class="danger" @click="store.stopCancelledRuntime()">停止 Runtime</button>
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
  color: #ccc;
}
.msg { font-size: 14px; margin: 0; }
.hint { font-size: 12px; color: #888; margin: 0; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
button {
  background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
button.primary { background: #0e639c; border-color: #0e639c; }
button.danger { background: #5a2d2d; border-color: #6b3636; }
</style>
