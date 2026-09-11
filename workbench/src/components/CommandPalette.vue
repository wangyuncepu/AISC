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

const props = defineProps<{ makeCtx: () => CommandCtx }>();
const emit = defineEmits<{ (e: "close"): void }>();

const { t } = useI18n();
const all = buildCommands();
const query = ref("");
const cursor = ref(0);
const inputEl = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);

const ctx = computed(() => props.makeCtx());
const available = computed(() => all.filter((c) => !c.when || c.when(ctx.value)));

const filtered = computed(() => {
  const matcher = buildSearchMatcher(query.value);
  if (matcher === null) return available.value;
  return available.value.filter((c) => matcher(t(c.labelKey).toLowerCase()) > 0);
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
  const n = filtered.value.length;
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
  reset();
  emit("close");
  cmd.run(props.makeCtx());
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (e.key === "Enter") { e.preventDefault(); runAt(cursor.value); }
  else if (e.key === "Escape") { e.preventDefault(); emit("close"); }
}

// Typing re-filters → clamp the cursor back into range.
watch(filtered, (f) => { if (cursor.value >= f.length) cursor.value = Math.max(0, f.length - 1); });

onMounted(() => inputEl.value?.focus());
</script>

<template>
  <Teleport to="body">
    <div class="palette-backdrop" @mousedown.self="emit('close')">
      <div
        class="palette"
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
          v-if="filtered.length"
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
