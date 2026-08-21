<script setup lang="ts">
/**
 * IDEA-2 (D3/D4): the shared subscription import form — mounted by the
 *「网络与用量」panel AND the onboarding wizard's container_tun branch.
 * Two modes: subscription URL (stdin channel on the Rust side — the URL is
 * a credential) or pasted config content (the fallback for sources that
 * reject automated downloads, TLS fingerprint filtering). All ipc goes
 * through the usage store (F-A01).
 */
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useUsageStore } from "../../stores/usage";

const { t } = useI18n();
const usage = useUsageStore();

const mode = ref<"url" | "content">("url");
const url = ref("");
const content = ref("");
/** Transient success line (2d round 2: the user gets explicit feedback the
 * moment the import lands — the panel also switches to the status view). */
const succeeded = ref(false);

async function submit(): Promise<void> {
  if (usage.subBusy) return;
  if (mode.value === "url" && !url.value.trim()) return;
  if (mode.value === "content" && !content.value.trim()) return;
  succeeded.value = false;
  const ok = mode.value === "url"
    ? await usage.importUrl(url.value.trim())
    : await usage.importContent(content.value);
  if (ok) {
    url.value = "";
    content.value = "";
    succeeded.value = true;
  }
}

function switchMode(next: "url" | "content"): void {
  mode.value = next;
  succeeded.value = false;
}
</script>

<template>
  <form class="sub-form" @submit.prevent="submit()">
    <div class="mode-row" role="tablist" :aria-label="t('usage.form.modeLabel')">
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'url'"
        :class="{ on: mode === 'url' }"
        @click="switchMode('url')"
      >{{ t("usage.form.modeUrl") }}</button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'content'"
        :class="{ on: mode === 'content' }"
        @click="switchMode('content')"
      >{{ t("usage.form.modeContent") }}</button>
    </div>

    <template v-if="mode === 'url'">
      <label class="ui-field">
        <span>{{ t("usage.form.urlLabel") }}</span>
        <input
          v-model="url"
          type="url"
          :placeholder="t('usage.form.urlPlaceholder')"
          :disabled="usage.subBusy"
          autocomplete="off"
          spellcheck="false"
        />
      </label>
      <p class="hint">{{ t("usage.form.urlHint") }}</p>
    </template>
    <template v-else>
      <label class="ui-field mono">
        <span>{{ t("usage.form.contentLabel") }}</span>
        <textarea
          v-model="content"
          rows="8"
          :placeholder="t('usage.form.contentPlaceholder')"
          :disabled="usage.subBusy"
          spellcheck="false"
        />
      </label>
      <p class="hint">{{ t("usage.form.contentHint") }}</p>
    </template>

    <p v-if="usage.subError" class="ui-feedback error" role="alert">
      {{ usage.subError.code === "AISC_ERR_NETWORK_SUBSCRIPTION_TLS_REJECTED"
        ? t("usage.sub.tlsRejected") : usage.subError.message }}
    </p>
    <p v-else-if="succeeded" class="ui-feedback success" role="status">✓ {{ t("usage.form.success") }}</p>

    <button type="submit" class="ui-button primary" :disabled="usage.subBusy">
      {{ usage.subBusy ? t("usage.form.importing") : t("usage.form.submit") }}
    </button>
  </form>
</template>

<style scoped>
/* 10b pilot: field/button/feedback surfaces come from the native primitives
 * (styles.css .ui-*); only the segmented mode switch and layout stay local. */
.sub-form { display: flex; flex-direction: column; gap: var(--space-3); max-width: 640px; }
.mode-row {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  align-self: flex-start;
  border-radius: var(--radius-sm);
  background: var(--surface-3);
}
.mode-row button {
  min-height: 22px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: calc(var(--radius-sm) - 2px);
  background: transparent;
  color: var(--text-2);
  font-size: var(--font-sm);
  cursor: pointer;
  transition: background-color var(--duration-fast), color var(--duration-fast);
}
.mode-row button:hover { background: var(--surface-hover); color: var(--text); }
.mode-row button.on { background: var(--accent-soft); color: var(--text); font-weight: 600; }
.mode-row button:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus);
  outline-offset: var(--focus-ring-offset);
}
.hint { font-size: var(--font-sm); color: var(--text-muted); margin: 0; }
.sub-form > .ui-button { align-self: flex-start; }
</style>
