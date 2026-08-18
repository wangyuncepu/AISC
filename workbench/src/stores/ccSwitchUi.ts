/**
 * Stage 8e (CS-05/06): cc-switch Provider UI store — the data-plane boundary
 * for the Provider tab (layer contract F-A01: components never import ipc
 * fact commands directly). Holds the secret-free snapshot + op state; secrets
 * pass through as call arguments only (never stored here).
 */
import { defineStore } from "pinia";
import { ref } from "vue";
import * as ipc from "../lib/ipc";
import type { CcSwitchProvider, CcSwitchRequest } from "../types";

export type CcSwitchAgent = "claude" | "codex";

export const useCcSwitchUiStore = defineStore("ccSwitchUi", () => {
  const agent = ref<CcSwitchAgent>("claude");
  const providers = ref<CcSwitchProvider[]>([]);
  const loading = ref(false);
  const busy = ref("");
  const error = ref<string | null>(null);

  function _apply(result: { providers: CcSwitchProvider[] }): void {
    providers.value = result.providers;
  }

  async function list(ws: string, rt: string): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      _apply(await ipc.ccSwitchProviders(ws, rt, agent.value));
      return true;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function switchAgent(a: CcSwitchAgent, ws: string, rt: string): Promise<void> {
    if (agent.value === a) return;
    agent.value = a;
    await list(ws, rt);
  }

  async function _run(
    op: string, fn: () => Promise<{ providers: CcSwitchProvider[] }>,
  ): Promise<boolean> {
    busy.value = op;
    error.value = null;
    try {
      _apply(await fn());
      return true;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      return false;
    } finally {
      busy.value = "";
    }
  }

  function add(ws: string, rt: string, request: CcSwitchRequest): Promise<boolean> {
    return _run(`add:${request.id ?? ""}`, () =>
      ipc.ccSwitchAdd(ws, rt, agent.value, request));
  }

  function edit(
    ws: string, rt: string, providerId: string, request: CcSwitchRequest,
  ): Promise<boolean> {
    return _run(`edit:${providerId}`, () =>
      ipc.ccSwitchEdit(ws, rt, agent.value, providerId, request));
  }

  function activate(ws: string, rt: string, providerId: string): Promise<boolean> {
    return _run(`switch:${providerId}`, () =>
      ipc.ccSwitchSwitch(ws, rt, agent.value, providerId));
  }

  function remove(ws: string, rt: string, providerId: string): Promise<boolean> {
    return _run(`delete:${providerId}`, () =>
      ipc.ccSwitchDelete(ws, rt, agent.value, providerId));
  }

  return {
    agent, providers, loading, busy, error,
    list, switchAgent, add, edit, activate, remove,
  };
});
