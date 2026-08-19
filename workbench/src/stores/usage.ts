/**
 * IDEA-2 (2d): the subscription + provider-usage data plane store.
 * Components never import these ipc commands directly (F-A01 layer
 * contract — same rule the cc-switch data plane follows); the wizard's
 * inline form, the LaunchSummary hint and the「网络与用量」panel all read
 * this store.
 */
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import {
  networkSubscriptionClear,
  networkSubscriptionImport,
  networkSubscriptionImportFile,
  networkSubscriptionRefresh,
  networkSubscriptionShow,
  usageOverview,
} from "../lib/ipc";
import type { SubscriptionStatus, UsageOverview, UsageRange, WorkbenchError } from "../types";

export const useUsageStore = defineStore("usage", () => {
  // --- subscription ---------------------------------------------------------

  const subscription = ref<SubscriptionStatus | null>(null);
  const subBusy = ref(false);
  const subError = ref<WorkbenchError | null>(null);
  /** Surfaced after a successful refresh/import (D1: next-start effect). */
  const refreshedNote = ref(false);

  async function refreshSubscriptionStatus(): Promise<boolean> {
    try {
      subscription.value = await networkSubscriptionShow();
      return subscription.value.configured;
    } catch {
      subscription.value = null;
      return false;
    }
  }

  async function importUrl(url: string): Promise<boolean> {
    return runSub(() => networkSubscriptionImport(url));
  }

  async function importContent(content: string): Promise<boolean> {
    return runSub(() => networkSubscriptionImportFile(content));
  }

  async function refreshSubscription(): Promise<boolean> {
    return runSub(() => networkSubscriptionRefresh());
  }

  async function clearSubscription(): Promise<boolean> {
    return runSub(async () => {
      await networkSubscriptionClear();
      subscription.value = null;
      return { configured: false } as SubscriptionStatus;
    });
  }

  async function runSub(
    op: () => Promise<SubscriptionStatus>,
  ): Promise<boolean> {
    subBusy.value = true;
    subError.value = null;
    refreshedNote.value = false;
    try {
      subscription.value = await op();
      refreshedNote.value = true;
      return true;
    } catch (e) {
      subError.value = e as WorkbenchError;
      return false;
    } finally {
      subBusy.value = false;
    }
  }

  const subConfigured = computed(() => subscription.value?.configured ?? false);

  // --- provider usage (D2: all workspaces) ------------------------------------

  const range = ref<UsageRange>("7d");
  const scope = ref<string>("all");
  const overview = ref<UsageOverview | null>(null);
  const loading = ref(false);
  const usageError = ref<string | null>(null);

  // --- display preferences (2d 手测 round 2: unit/currency toggles) -------
  // Session-level (not persisted): token magnitude and cost currency are
  // presentation choices over the same CLI numbers.

  /** Token display unit: auto adapts (k/M/B) by magnitude; the fixed units
   * always divide by their magnitude; raw shows the plain integer. */
  const tokenUnit = ref<"auto" | "k" | "M" | "raw">("auto");
  /** Cost display currency. cc-switch normalizes costs to USD; CNY is a
   * fixed-rate conversion shown with a note (provider bills stay
   * authoritative). */
  const currency = ref<"USD" | "CNY">("USD");

  const TOKEN_UNIT_CYCLE: Array<"auto" | "k" | "M" | "raw"> = ["auto", "k", "M", "raw"];
  function cycleTokenUnit(): void {
    const i = TOKEN_UNIT_CYCLE.indexOf(tokenUnit.value);
    tokenUnit.value = TOKEN_UNIT_CYCLE[(i + 1) % TOKEN_UNIT_CYCLE.length];
  }
  function toggleCurrency(): void {
    currency.value = currency.value === "USD" ? "CNY" : "USD";
  }

  async function fetchOverview(): Promise<UsageOverview | null> {
    loading.value = true;
    usageError.value = null;
    try {
      // Always fetch the FULL overview: the workspace selector is built from
      // the returned list, so a server-side --workspace filter would shrink
      // the dropdown to just the selected entry (2d 手测 round 3). `scope`
      // stays a purely client-side row filter.
      overview.value = await usageOverview(range.value);
      // The overview envelope carries the subscription snapshot too.
      if (overview.value?.subscription) subscription.value = overview.value.subscription;
      return overview.value;
    } catch (e) {
      usageError.value = (e as WorkbenchError).message;
      return null;
    } finally {
      loading.value = false;
    }
  }

  return {
    subscription,
    subBusy,
    subError,
    refreshedNote,
    subConfigured,
    refreshSubscriptionStatus,
    importUrl,
    importContent,
    refreshSubscription,
    clearSubscription,
    range,
    scope,
    overview,
    loading,
    usageError,
    fetchOverview,
    tokenUnit,
    currency,
    cycleTokenUnit,
    toggleCurrency,
  };
});
