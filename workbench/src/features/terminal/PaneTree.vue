<script setup lang="ts">
/**
 * PaneTree (G-17, Step 16; 03 §六): recursive split-tree renderer for a tab.
 *
 * - split node -> CSS grid row (axis horizontal) / column (vertical) with a
 *   keyboard+pointer divider (ratio clamp 0.10..0.90, 0.05 step, A-G17-4).
 * - pane leaf -> its session content: Terminal (per-pane xterm), GuidePane
 *   (unconfigured claude/codex), or a dormant 启动 view. The pane's runtime
 *   state comes from tab.panes[paneId]; the leaf's session type from the tree.
 * - Clicking a pane makes it active (A-G17-5: active pane drives the
 *   projection / title / sidebar).
 */
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRuntimeStore } from "../../stores/runtime";
import { RATIO_STEP, leafCount, splitKey } from "../../stores/paneTree";
import Terminal from "./Terminal.vue";
import GuidePane from "./GuidePane.vue";
import type { PaneNode, PaneSplitNode } from "../../types";

const { t } = useI18n();
const props = defineProps<{ tabId: string; tree: PaneNode }>();
const store = useRuntimeStore();

const tab = computed(() => store.tabs.find((t) => t.tabId === props.tabId));
const split = computed(() => (props.tree.kind === "split" ? props.tree : null));
const pane = computed(() => (props.tree.kind === "pane" ? props.tree : null));

const paneRuntime = computed(() =>
  pane.value ? (tab.value?.panes[pane.value.paneId] ?? null) : null
);
/** Only panes of a multi-leaf tree get a close button (single pane: none). */
const canClosePane = computed(() => (tab.value ? leafCount(tab.value.tree) > 1 : false));
const showTerminal = computed(
  () =>
    paneRuntime.value &&
    paneRuntime.value.sessionState !== "idle" &&
    paneRuntime.value.sessionState !== "guide"
);
const isDormant = computed(
  () => pane.value && (!paneRuntime.value || paneRuntime.value.sessionState === "idle")
);

/** Grid track sizes (fr) so the divider keeps its exact width. */
function tracks(s: PaneSplitNode): { r1: string; r2: string } {
  return { r1: `${s.ratio}fr`, r2: `${1 - s.ratio}fr` };
}

function activatePane() {
  if (pane.value) store.setActivePane(props.tabId, pane.value.paneId);
}

function startPane() {
  if (!pane.value) return;
  store.setActivePane(props.tabId, pane.value.paneId);
  store.openTab(props.tabId);
}

function onDividerKey(e: KeyboardEvent, s: PaneSplitNode) {
  const key = splitKey(s);
  if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
    store.setSplitRatio(props.tabId, key, s.ratio - RATIO_STEP);
    e.preventDefault();
  } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
    store.setSplitRatio(props.tabId, key, s.ratio + RATIO_STEP);
    e.preventDefault();
  }
}

function startDividerDrag(e: PointerEvent, s: PaneSplitNode) {
  e.preventDefault();
  // preventDefault suppresses the default focus; focus explicitly so the
  // divider keeps keyboard control (arrows) after the drag ends.
  (e.currentTarget as HTMLElement).focus();
  const host = (e.currentTarget as HTMLElement).parentElement as HTMLElement;
  const rect = host.getBoundingClientRect();
  const key = splitKey(s);
  const axis = s.axis;
  const move = (ev: PointerEvent) => {
    const p =
      axis === "horizontal"
        ? (ev.clientX - rect.left) / rect.width
        : (ev.clientY - rect.top) / rect.height;
    store.setSplitRatio(props.tabId, key, p);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

// --- focus: the tab's active pane Terminal (used by App after tab switching) ---
const termRefs = ref(new Map<string, InstanceType<typeof Terminal>>());
function setTerm(paneId: string) {
  return (el: unknown) => {
    if (el) termRefs.value.set(paneId, el as InstanceType<typeof Terminal>);
    else termRefs.value.delete(paneId);
  };
}
function focusActivePane(): void {
  const active = tab.value?.activePaneId;
  void nextTick(() => termRefs.value.get(active ?? "")?.focus());
}
defineExpose({ focusActivePane });
</script>

<template>
  <!-- split: grid row/column + divider -->
  <div
    v-if="split"
    class="split"
    :data-axis="split.axis"
    :style="
      split.axis === 'horizontal'
        ? { gridTemplateColumns: `${tracks(split).r1} 6px ${tracks(split).r2}` }
        : { gridTemplateRows: `${tracks(split).r1} 6px ${tracks(split).r2}` }
    "
  >
    <div class="child">
      <PaneTree :tab-id="tabId" :tree="split.first" />
    </div>
    <div
      class="divider"
      role="separator"
      :aria-orientation="split.axis === 'horizontal' ? 'vertical' : 'horizontal'"
      tabindex="0"
      :title="split.axis === 'horizontal' ? '拖动调整左右；点击后按 ←/→ 微调' : '拖动调整上下；点击后按 ↑/↓ 微调'"
      @pointerdown="startDividerDrag($event, split)"
      @keydown="onDividerKey($event, split)"
    >
      <span class="grip" />
    </div>
    <div class="child">
      <PaneTree :tab-id="tabId" :tree="split.second" />
    </div>
  </div>

  <!-- pane leaf: Terminal / guide / dormant -->
  <div
    v-else-if="pane"
    class="pane"
    :data-active="tab?.activePaneId === pane.paneId"
    @pointerdown="activatePane"
  >
    <button
      v-if="canClosePane"
      class="pane-close"
      :title="t('pane.close')"
      :aria-label="t('pane.close')"
      @pointerdown.stop
      @click.stop="store.closePane(tabId, pane.paneId)"
    >×</button>
    <Terminal v-if="showTerminal" :ref="setTerm(pane.paneId)" :tab-id="tabId" :pane-id="pane.paneId" />
    <GuidePane
      v-else-if="paneRuntime?.sessionState === 'guide'"
      :tab-id="tabId"
      :pane-id="pane.paneId"
    />
    <div v-else-if="isDormant" class="dormant">
      <span class="type">{{ pane.sessionType }}</span>
      <button class="primary" @click="startPane">{{ t("tabs.newTab") }}</button>
    </div>
  </div>
</template>

<style scoped>
.split {
  display: grid;
  height: 100%;
  width: 100%;
  min-height: 0;
  min-width: 0;
}
.child {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.divider {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
  cursor: col-resize;
  outline: none;
  position: relative;
  z-index: 1;
}
.divider[aria-orientation="horizontal"] {
  cursor: row-resize;
}
.divider:hover, .divider:focus-visible {
  background: var(--accent);
}
.grip {
  width: 2px;
  height: 24px;
  background: var(--border-strong);
  border-radius: 1px;
}
.divider[aria-orientation="horizontal"] .grip {
  width: 24px;
  height: 2px;
}
.pane {
  height: 100%;
  width: 100%;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}
.pane[data-active="true"] { background: var(--bg); }
.pane-close {
  position: absolute; top: 4px; right: 4px; z-index: 2;
  background: rgba(30, 30, 30, 0.8); border: 1px solid var(--border-2); color: var(--text-muted);
  width: 20px; height: 20px; line-height: 1; border-radius: 4px;
  font-size: 14px; cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.pane-close:hover { background: var(--error-bg); border-color: var(--error-border); color: var(--error-fg); }
.dormant {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  background: var(--bg);
}
.dormant .type { font-family: monospace; font-size: 13px; color: var(--text-2); }
button.primary {
  background: var(--accent); color: var(--accent-fg); border: 1px solid var(--accent);
  border-radius: 4px; padding: 5px 14px; font-size: 12px; cursor: pointer;
}
</style>
