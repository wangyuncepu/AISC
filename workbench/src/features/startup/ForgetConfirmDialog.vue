<script setup lang="ts">
/**
 * v2.1.7 S2 (⑦): the "forget this workspace" confirm dialog.
 *
 * Shows the backend preview's structured facts — categories that WILL be
 * removed, named volumes that will be KEPT (D12), the red line that the
 * user's on-disk workspace files are never touched — and blocks the
 * destructive button while the backend reports the workspace as active.
 * A11y (A-2172B): focus trap + Escape via useDialogA11y, default focus on
 * the CANCEL button (never the destructive one).
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useDialogA11y } from "../../composables/useDialogA11y";
import type { ForgetPreview } from "../../types";

const props = defineProps<{
  preview: ForgetPreview;
  busy: boolean;
  error: string | null;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "confirm"): void }>();

const { t } = useI18n();
const panel = ref<HTMLElement | null>(null);
const cancelBtn = ref<HTMLButtonElement | null>(null);
useDialogA11y(panel, () => emit("close"));
onMounted(() => cancelBtn.value?.focus());

const blocked = computed(() => props.preview.blockedReason !== null);

function catLabel(c: string): string {
  if (c.startsWith("other:")) {
    return t("picker.catOther", { n: c.slice("other:".length) });
  }
  return t(`picker.cat.${c}`);
}

/** Preview warnings are stable backend codes — humanize the known ones. */
function warnText(w: string): string {
  return w === "stale-lease-file-removed-with-state"
    ? t("picker.warnStaleLease")
    : w;
}
</script>

<template>
  <div class="overlay" @mousedown.self="emit('close')">
    <section
      ref="panel"
      class="panel"
      role="dialog"
      aria-modal="true"
      :aria-label="t('picker.forgetTitle')"
      tabindex="-1"
    >
      <header class="head">
        <h2>{{ t("picker.forgetTitle") }}</h2>
      </header>
      <div class="body">
        <p class="path" :title="preview.workspacePath">{{ preview.workspacePath }}</p>

        <template v-if="blocked">
          <p class="blocked" role="alert">
            {{ t(`picker.forgetBlocked.${preview.blockedReason}`) }}
          </p>
        </template>

        <template v-else>
          <p v-if="preview.dataPresent">{{ t("picker.forgetWillRemove") }}</p>
          <ul v-if="preview.categories.length" class="cats">
            <li v-for="c in preview.categories" :key="c">{{ catLabel(c) }}</li>
          </ul>
          <p v-if="!preview.dataPresent" class="dim">{{ t("picker.forgetNoData") }}</p>
          <template v-if="preview.namedVolumes.length">
            <p class="warn">{{ t("picker.forgetVolumesKept") }}</p>
            <ul class="cats dim">
              <li v-for="v in preview.namedVolumes" :key="v" :title="v">{{ v }}</li>
            </ul>
          </template>
          <p class="safe">{{ t("picker.forgetSafeLine") }}</p>
        </template>

        <p v-for="w in preview.warnings" :key="w" class="dim">{{ warnText(w) }}</p>
        <p v-if="error" class="err" role="alert">{{ error }}</p>
      </div>
      <footer class="foot">
        <button ref="cancelBtn" class="ui-button" @click="emit('close')">
          {{ t("picker.cancel") }}
        </button>
        <button class="ui-button danger" :disabled="blocked || busy" @click="emit('confirm')">
          {{ busy ? t("picker.forgetBusy") : t("picker.forgetConfirmBtn") }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 90;
  background: var(--scrim);
  display: flex; align-items: center; justify-content: center;
}
.panel {
  width: 480px; max-width: 90vw;
  background: var(--surface); color: var(--text);
  border: var(--border-w) solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-menu);
  display: flex; flex-direction: column;
}
.head { padding: var(--space-3) var(--space-4) 0; }
.head h2 { margin: 0; font-size: var(--font-lg); font-weight: 600; }
.body { padding: var(--space-2) var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); }
.foot {
  padding: var(--space-3) var(--space-4);
  display: flex; justify-content: flex-end; gap: var(--space-2);
}
.path {
  margin: 0; font-family: var(--font-mono); font-size: var(--font-xs);
  color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cats { margin: 0; padding-left: var(--space-5); font-size: var(--font-sm); color: var(--text-2); }
.cats.dim { color: var(--text-faint); }
.dim { color: var(--text-faint); font-size: var(--font-sm); margin: 0; }
.safe { margin: 0; font-size: var(--font-sm); color: var(--success); }
.warn { margin: 0; font-size: var(--font-sm); color: var(--warn-fg); }
.blocked { margin: 0; font-size: var(--font-sm); color: var(--warn-fg); font-weight: 600; }
.err { margin: 0; font-size: var(--font-sm); color: var(--error-fg); }
.panel:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
.ui-button.danger {
  background: var(--error-bg); color: var(--error-fg);
  border: var(--border-w) solid var(--error-border);
}
</style>
