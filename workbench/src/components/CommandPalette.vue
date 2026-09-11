<script setup lang="ts">
/**
 * P2-4 (D-4 / ui-review A1): the command palette — VS Code's Ctrl+Shift+P.
 * Data source = the command registry (lib/commands.ts); search rides the
 * shared matcher (lib/search.ts — substring > subsequence > /regex/);
 * keyboard-first (↑/↓ move, Enter runs, Esc closes); groups render with
 * headers; shortcuts show right-aligned.
 *
 * A11y: role=dialog + a labelled input; the list is a listbox with options
 * (aria-selected on the cursor row). The palette closes after ONE run —
 * command invocations are single-shot by nature.
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { buildSearchMatcher } from "../lib/search";
import { buildCommands, type CommandCtx } from "../lib/commands";
import { useSettingsStore } from "../stores/settings";

const props = defineProps<{ makeCtx: () => CommandCtx }>();
const emit = defineEmits<{ (e: "close"): void }>();

const { t } = useI18n();
// 手测 r1#1: the palette rides the same ui.font_scale zoom as the chrome
// (the teleport escapes App's zoom scope — re-applied here, ToastHost-style).
const settings = useSettingsStore();
const uiScale = computed(() => settings.doc?.ui.font_scale ?? 1);
const all = buildCommands();
const query = ref("");
const cursor = ref(0);
const inputEl = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);

const ctx = computed(() => props.makeCtx());
/** 手测 r2#3: split commands open a session-type sub-step (the SAME flow
 * as the pane context menu) — chosen here, the split runs with the picked
 * agent. Esc in a sub-step returns to the command list (one level). */
const subMode = ref<"split:h" | "split:v" | null>(null);
const SPLIT_AGENTS = ["bash", "claude", "codex"] as const;
const available = computed(() => all.filter((c) => !c.when || c.when(ctx.value)));

const filtered = computed(() => {
  if (subMode.value) return []; // sub-step renders its own rows
  const matcher = buildSearchMatcher(query.value);
  if (matcher === null) return available.value;
  return available.value.filter((c) => matcher(t(c.labelKey).toLowerCase()) > 0);
});

const subRows = computed(() => {
  if (!subMode.value) return [];
  const matcher = buildSearchMatcher(query.value);
  return SPLIT_AGENTS.filter(
    (a) => matcher === null || matcher(t(`tabbar.menu.${a}`).toLowerCase()) > 0,
  );
});

/** Group headers render between group changes of the filtered list. */
const rows = computed(() => {
  let lastGroup = "";
  return filtered.value.flatMap((c, i) => {
    const header = c.groupKey !== lastGroup ? c.groupKey : null;
    lastGroup = c.groupKey;
    return header ? [{ header, i }, { cmd: c, i }] : [{ cmd: c, i }];
  });
});

function reset(): void {
  query.value = "";
  cursor.value = 0;
}

function move(delta: number): void {
  const n = subMode.value ? subRows.value.length : filtered.value.length;
  if (!n) return;
  cursor.value = (cursor.value + delta + n) % n;
  void nextTick(() =>
    listEl.value
      ?.querySelector<HTMLElement>(`[data-idx="${cursor.value}"]`)
      ?.scrollIntoView({ block: "nearest" }));
}

function runAt(i: number): void {
  const cmd = filtered.value[i];
  if (!cmd) return;
  if (cmd.sub) {
    subMode.value = cmd.sub;
    reset();
    return;
  }
  reset();
  emit("close");
  cmd.run(props.makeCtx());
}

function runSub(agent: (typeof SPLIT_AGENTS)[number]): void {
  const [_, dir] = (subMode.value ?? "split:h").split(":");
  subMode.value = null;
  reset();
  emit("close");
  props.makeCtx().active.splitPane(dir === "v" ? "v" : "h", agent);
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (e.key === "Enter") {
    e.preventDefault();
    if (subMode.value) runSub(subRows.value[cursor.value] ?? subRows.value[0]!);
    else runAt(cursor.value);
  }
  else if (e.key === "Escape") {
    e.preventDefault();
    if (subMode.value) { subMode.value = null; reset(); }
    else emit("close");
  }
}

// Typing re-filters → clamp the cursor back into range.
watch(filtered, (f) => { if (cursor.value >= f.length) cursor.value = Math.max(0, f.length - 1); });
watch(subRows, (r) => { cursor.value = Math.min(cursor.value, Math.max(0, r.length - 1)); });

onMounted(() => inputEl.value?.focus());
</script>

<template>
  <Teleport to="body">
    <div class="palette-backdrop" @mousedown.self="emit('close')">
      <div
        class="palette"
        :style="{ zoom: uiScale }"
        role="dialog"
        aria-modal="true"
        :aria-label="t('palette.title')"
      >
        <input
          ref="inputEl"
          v-model="query"
          class="palette-input"
          type="text"
          :placeholder="t('palette.placeholder')"
          aria-controls="palette-list"
          @keydown="onKeydown"
        />
        <ul
          v-if="subMode && subRows.length"
          id="palette-list"
          ref="listEl"
          class="palette-list"
          role="listbox"
        >
          <li class="palette-group" role="presentation">{{ t("palette.splitAs") }}</li>
          <li
            v-for="(a, i) in subRows"
            :key="a"
            class="palette-item"
            role="option"
            :aria-selected="i === cursor"
            :data-idx="i"
            :class="{ cursor: i === cursor }"
            @mousemove="cursor = i"
            @click="runSub(a)"
          >
            <span class="palette-label">{{ t(`tabbar.menu.${a}`) }}</span>
          </li>
        </ul>
        <ul
          v-if="!subMode && filtered.length"
          id="palette-list"
          ref="listEl"
          class="palette-list"
          role="listbox"
        >
          <template v-for="row in rows" :key="row.i">
            <li v-if="'header' in row && row.header" class="palette-group" role="presentation">
              {{ t(row.header) }}
            </li>
            <li
              v-else-if="'cmd' in row && row.cmd"
              class="palette-item"
              role="option"
              :aria-selected="row.i === cursor"
              :data-idx="row.i"
              :class="{ cursor: row.i === cursor }"
              @mousemove="cursor = row.i"
              @click="runAt(row.i)"
            >
              <span class="palette-label">{{ t(row.cmd.labelKey) }}</span>
              <kbd v-if="row.cmd.shortcut" class="palette-kbd">{{ row.cmd.shortcut }}</kbd>
            </li>
          </template>
        </ul>
        <p v-else class="palette-empty">{{ t("palette.noMatch") }}</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-toast); /* above dialogs: the palette is a top-level surface */
  background: var(--scrim);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 10vh;
}
.palette {
  width: min(560px, 86vw);
  background: var(--surface-2);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-2);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.palette-input {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-bottom: var(--border-w) solid var(--border);
  background: var(--surface-3);
  color: var(--text);
  font-size: var(--font-md);
  outline: none;
}
.palette-list {
  margin: 0;
  padding: 4px 0;
  list-style: none;
  max-height: 50vh;
  overflow-y: auto;
}
.palette-group {
  padding: 6px 12px 2px;
  font-size: var(--font-xs);
  color: var(--text-faint);
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.palette-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 12px;
  font-size: var(--font-sm);
  color: var(--text-2);
  cursor: pointer;
}
.palette-item.cursor { background: var(--accent-soft); color: var(--text); }
.palette-item.cursor:focus-visible,
.palette-item:focus-visible { outline: none; }
.palette-kbd {
  font-family: inherit;
  font-size: var(--font-xs);
  color: var(--text-muted);
  border: var(--border-w) solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 6px;
}
.palette-empty {
  margin: 0;
  padding: var(--space-3);
  color: var(--text-muted);
  font-size: var(--font-sm);
  text-align: center;
}
</style>
