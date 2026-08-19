<script setup lang="ts">
/**
 * IDEA-2 (2d): the「网络与用量」panel — a workspace-layer sentinel pane
 * (same slot as Settings). Two sections: the mihomo subscription (masked
 * URL, usage bar / remaining / expiry from `subscription-userinfo`, refresh
 * with the auto-recreate note) and per-provider token usage aggregated
 * across ALL data-root workspaces (live for running containers, cached
 * snapshots for stopped ones — D2). All ipc goes through the usage store
 * (F-A01).
 */
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { confirm } from "@tauri-apps/plugin-dialog";
import { useUsageStore } from "../../stores/usage";
import type { UsageWorkspaceEntry } from "../../types";
import SubscriptionForm from "./SubscriptionForm.vue";

const { t } = useI18n();
const usage = useUsageStore();

/** Locale short date (the i18n instance ships no datetimeFormats — G-09
 * kept it messages-only, so format dates locally). */
const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" });
function fmtDate(isoOrEpoch: string | number): string {
  const date = typeof isoOrEpoch === "number" ? new Date(isoOrEpoch * 1000) : new Date(isoOrEpoch);
  return Number.isNaN(date.getTime()) ? String(isoOrEpoch) : dateFmt.format(date);
}

// --- subscription section ----------------------------------------------------

/** Show the import form (not configured, or the user pressed 更换). */
const replacing = ref(false);

const usedBytes = computed(() => {
  const u = usage.subscription?.userinfo;
  return (u?.upload ?? 0) + (u?.download ?? 0);
});
const totalBytes = computed(() => usage.subscription?.userinfo?.total ?? 0);
const usedPct = computed(() =>
  totalBytes.value > 0 ? Math.min(100, (usedBytes.value * 100) / totalBytes.value) : null,
);

async function clearSubscription(): Promise<void> {
  if (!(await confirm(t("usage.sub.clearConfirm")))) return;
  const ok = await usage.clearSubscription();
  if (ok) replacing.value = true;
}

// --- usage section (D2: all workspaces) ---------------------------------------

const scopeOptions = computed(() => {
  const list = [{ value: "all", label: t("usage.scope.all") }];
  for (const w of usage.overview?.workspaces ?? []) {
    const name = w.workspace_path.split(/[\\/]/).filter(Boolean).pop() ?? w.workspace_hash;
    list.push({ value: w.workspace_path, label: name });
  }
  return list;
});

/** The rows the table shows: the filtered workspace's own rows when a single
 * workspace is selected, else the cross-workspace totals. */
const providerRows = computed(() => {
  const ov = usage.overview;
  if (!ov) return [];
  if (usage.scope === "all") return ov.totals.providers;
  const ws = ov.workspaces.find((w) => w.workspace_path === usage.scope);
  return ws?.providers ?? [];
});

const visibleWorkspaces = computed<UsageWorkspaceEntry[]>(() =>
  (usage.overview?.workspaces ?? []).filter(
    (w) => usage.scope === "all" || w.workspace_path === usage.scope,
  ),
);

function successRate(ok: number, total: number): string {
  return total > 0 ? `${Math.round((ok * 100) / total)}%` : "—";
}
function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}
function fmtTokens(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${n}`;
}

watch(
  () => [usage.range, usage.scope],
  () => void usage.fetchOverview(),
);
watch(
  () => usage.subscription?.configured,
  (configured) => {
    if (configured === false) replacing.value = true;
  },
  { immediate: true },
);
onMounted(() => void usage.fetchOverview());
</script>

<template>
  <section class="usage-tab" :aria-label="t('usage.title')">
    <div class="scroll">
      <!-- ============ subscription ============ -->
      <h2>{{ t("usage.sub.title") }}</h2>
      <template v-if="usage.subConfigured && !replacing">
        <dl class="sub-facts">
          <div><dt>{{ t("usage.sub.url") }}</dt>
            <dd>{{ usage.subscription?.url_masked ?? t("usage.sub.manualUrl") }}</dd></div>
          <div><dt>{{ t("usage.sub.source") }}</dt><dd>{{ usage.subscription?.source }}</dd></div>
          <div v-if="usage.subscription?.fetched_at"><dt>{{ t("usage.sub.updated") }}</dt>
            <dd>{{ fmtDate(usage.subscription.fetched_at) }}</dd></div>
        </dl>

        <template v-if="usage.subscription?.userinfo">
          <div v-if="usedPct !== null" class="bar"
               role="img" :aria-label="t('usage.sub.usage', { pct: usedPct.toFixed(1) })">
            <div class="bar-fill" :style="{ width: `${usedPct}%` }" />
          </div>
          <p class="sub-usage">
            {{ t("usage.sub.usageLine", {
              used: fmtBytes(usedBytes),
              total: totalBytes > 0 ? fmtBytes(totalBytes) : t("usage.sub.unlimited"),
              remaining: totalBytes > 0 ? fmtBytes(Math.max(0, totalBytes - usedBytes)) : "—",
            }) }}
            <span v-if="usage.subscription.userinfo.expire">
              · {{ t("usage.sub.expire") }}: {{ fmtDate(usage.subscription.userinfo.expire) }}
            </span>
          </p>
        </template>
        <p v-else class="sub-usage dim">{{ t("usage.sub.noUsageInfo") }}</p>

        <p v-if="usage.refreshedNote" class="note">{{ t("usage.sub.refreshNote") }}</p>
        <p v-if="usage.subError" class="error" role="alert">{{ usage.subError.message }}</p>

        <div class="actions">
          <button
            :disabled="usage.subBusy || usage.subscription?.source !== 'download'"
            @click="usage.refreshSubscription()"
          >{{ usage.subBusy ? t("usage.sub.refreshing") : t("usage.sub.refresh") }}</button>
          <button :disabled="usage.subBusy" @click="replacing = true">
            {{ t("usage.sub.replace") }}
          </button>
          <button class="danger" :disabled="usage.subBusy" @click="clearSubscription()">
            {{ t("usage.sub.clear") }}
          </button>
        </div>
      </template>
      <template v-else>
        <p class="dim">{{ t("usage.sub.none") }}</p>
        <SubscriptionForm />
      </template>

      <!-- ============ provider usage ============ -->
      <h2>{{ t("usage.providers.title") }}</h2>
      <div class="controls">
        <label>
          <span>{{ t("usage.rangeLabel") }}</span>
          <select v-model="usage.range">
            <option value="today">{{ t("usage.range.today") }}</option>
            <option value="7d">{{ t("usage.range.7d") }}</option>
            <option value="30d">{{ t("usage.range.30d") }}</option>
          </select>
        </label>
        <label>
          <span>{{ t("usage.scopeLabel") }}</span>
          <select v-model="usage.scope">
            <option v-for="o in scopeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </label>
        <button :disabled="usage.loading" @click="usage.fetchOverview()">
          {{ t("usage.reload") }}
        </button>
      </div>

      <p v-if="usage.loading" class="dim">{{ t("usage.loading") }}</p>
      <p v-else-if="usage.usageError" class="error" role="alert">{{ usage.usageError }}</p>

      <template v-else>
        <table v-if="providerRows.length" class="usage-table">
          <thead>
            <tr>
              <th>{{ t("usage.col.app") }}</th>
              <th>{{ t("usage.col.provider") }}</th>
              <th class="num">{{ t("usage.col.requests") }}</th>
              <th class="num">{{ t("usage.col.successRate") }}</th>
              <th class="num">{{ t("usage.col.tokens") }}</th>
              <th class="num">{{ t("usage.col.cost") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in providerRows" :key="`${row.app}:${row.provider_id}`">
              <td>{{ row.app }}</td>
              <td>{{ row.provider_name }}</td>
              <td class="num">{{ row.requests }}</td>
              <td class="num">{{ successRate(row.success, row.requests) }}</td>
              <td class="num">{{ fmtTokens(row.tokens_total) }}</td>
              <td class="num">${{ row.cost_estimate.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="dim">{{ t("usage.empty") }}</p>

        <ul v-if="usage.scope === 'all'" class="ws-states">
          <li v-for="w in visibleWorkspaces" :key="w.workspace_hash">
            {{ w.workspace_path.split(/[\\/]/).filter(Boolean).pop() ?? w.workspace_hash }}
            — {{ w.source === "live" ? t("usage.ws.live")
                : w.source === "cache" ? t("usage.ws.cache") : t("usage.ws.none") }}
          </li>
        </ul>
        <p class="hint">{{ t("usage.note") }}</p>
      </template>
    </div>
  </section>
</template>

<style scoped>
.usage-tab { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column;
  background: var(--surface); }
.scroll { flex: 1; overflow: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 12px; }
h2 { font-size: 15px; margin: 12px 0 2px; }
.dim { color: var(--text-dim, #888); font-size: 13px; }
.sub-facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0; }
.sub-facts div { display: contents; }
.sub-facts dt { color: var(--text-dim, #888); font-size: 12px; }
.sub-facts dd { margin: 0; font-size: 13px; word-break: break-all; }
.bar { height: 8px; border-radius: 4px; background: var(--surface-2, #ddd); overflow: hidden; max-width: 480px; }
.bar-fill { height: 100%; background: var(--accent, #3b7dd8); }
.sub-usage { margin: 0; font-size: 13px; }
.note { margin: 0; font-size: 12px; color: var(--warn, #b80); }
.error { color: var(--danger, #d33); font-size: 13px; margin: 0; }
.actions { display: flex; gap: 8px; }
.controls { display: flex; gap: 14px; align-items: end; flex-wrap: wrap; }
.controls label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-dim, #888); }
.usage-table { border-collapse: collapse; font-size: 13px; max-width: 860px; }
.usage-table th, .usage-table td { border: 1px solid var(--border); padding: 5px 10px; text-align: left; }
.usage-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.ws-states { margin: 0; padding-left: 18px; font-size: 12px; color: var(--text-dim, #888); }
.hint { font-size: 12px; color: var(--text-dim, #888); margin: 0; max-width: 760px; }
button.danger { color: var(--danger, #d33); }
</style>
