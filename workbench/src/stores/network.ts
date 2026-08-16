/**
 * Network onboarding store (Stage 5, A-ONB05).
 *
 * Offers direct / host-proxy / container-TUN / skip. The user's choice is only
 * applied to the runtime launch config after explicit confirmation (impact
 * shown first) and can always be revoked back to "direct". We never touch the
 * host's own proxy configuration (the contract forbids overriding it); the
 * container-TUN path reuses the existing `network: "proxy"` launch setting.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as ipc from "../lib/ipc";
import type { EnvReadiness } from "../types";

/** User-facing network modes the wizard offers. */
export type NetworkChoice = "direct" | "host_proxy" | "container_tun" | "skipped";

const NETWORK_LABEL: Record<NetworkChoice, string> = {
  direct: "direct",
  host_proxy: "host_proxy",
  container_tun: "container_tun",
  skipped: "skipped",
};

export const useNetworkStore = defineStore("network", () => {
  const choice = ref<NetworkChoice>("direct");
  const probing = ref(false);
  const probeResult = ref<string | null>(null); // "ok" | "failed" | null
  const confirmed = ref(false);
  const error = ref<string | null>(null);

  const selected = computed(() => NETWORK_LABEL[choice.value]);

  async function probe(): Promise<void> {
    probing.value = true;
    probeResult.value = null;
    error.value = null;
    try {
      // Best-effort connectivity probe via the environment readiness engine
      // state (daemon reachable). A proxy/TUN-specific reachability probe would
      // need a target host; the contract keeps the probe non-destructive and
      // the user can skip if it cannot be verified.
      const r: EnvReadiness = await ipc.envReadiness();
      probeResult.value = r.engine === "ready" ? "ok" : "failed";
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      probeResult.value = "failed";
    } finally {
      probing.value = false;
    }
  }

  function setChoice(c: NetworkChoice) {
    choice.value = c;
    confirmed.value = false; // changing choice requires a fresh confirm
    probeResult.value = null;
  }

  /** Confirm the choice (the UI shows impact before calling this). */
  function confirm() {
    confirmed.value = true;
  }

  /** Revoke/rollback: reset to direct, un-confirm. Never touches host proxy. */
  function revoke() {
    choice.value = "direct";
    confirmed.value = false;
    probeResult.value = null;
  }

  return {
    choice,
    probing,
    probeResult,
    confirmed,
    error,
    selected,
    probe,
    setChoice,
    confirm,
    revoke,
  };
});
