/**
 * Stage 8e (CS-05/06): cc-switch Provider UI store — the data-plane boundary
 * for the Provider tab (layer contract F-A01: components never import ipc
 * fact commands directly). Holds the secret-free snapshot + op state; secrets
 * pass through as call arguments only (never stored here).
 */
import { defineStore } from "pinia";
import { computed, reactive, ref } from "vue";
import * as ipc from "../lib/ipc";
import type { CcSwitchProvider, CcSwitchRequest, FetchModelsResult } from "../types";

export type CcSwitchAgent = "claude" | "codex";

export const useCcSwitchUiStore = defineStore("ccSwitchUi", () => {
  const agent = ref<CcSwitchAgent>("claude");
  const providers = ref<CcSwitchProvider[]>([]);
  const loading = ref(false);
  const busy = ref("");
  const error = ref<string | null>(null);
  /** Manual-test r5 #3: the mapped message alone hid the diagnosis (the
   * generic 「AISC CLI 返回错误」 bucket carries the real reason in
   * technical_detail) and the failure left NO timeline trace. The banner
   * now renders this detail line; list() failures log to the timeline. */
  const errorDetail = ref<string | null>(null);
  /** IDEA-5 (5d): last fetch-models result per provider id (the dropdown's
   * tier-1 source; unavailable results carry the upstream hint). */
  const fetchedModels = reactive<Record<string, FetchModelsResult>>({});

  /** PP r3 (user ruling): the edit dance is delete→re-add server-side, which
   * used to reorder cards after every save. First-seen order is pinned here
   * per agent — edits/additions never reshuffle the list. */
  const orderSeq = new Map<string, number>();
  function _order(id: string): number {
    let seq = orderSeq.get(id);
    if (seq === undefined) {
      seq = orderSeq.size;
      orderSeq.set(id, seq);
    }
    return seq;
  }

  function _apply(result: { providers: CcSwitchProvider[] }): void {
    // Pre-pin every id BEFORE sorting: assigning seqs inside the comparator
    // makes the result depend on the engine's comparison order.
    for (const p of result.providers) _order(p.id);
    providers.value = [...result.providers].sort((a, b) => _order(a.id) - _order(b.id));
  }

  /** 2.1.11 P1: edit-time explicit view — fetch the FULL api_key of one
   * provider. The reveal snapshot is used for the key only and is NOT
   * applied to the card list (the list must stay secret-free).
   * Manual-test r3: failures PROPAGATE — swallowing them into `null` made
   * the eye button a silent no-op whenever the chain broke (e.g. a runtime
   * container whose baked adapter predates `--reveal-id`), the exact
   * "保存无反应" dead-button pattern PP r4 fixed for save. The editor
   * renders the error inline. */
  async function revealKey(ws: string, rt: string, providerId: string): Promise<string | null> {
    const result = await ipc.ccSwitchProviders(ws, rt, agent.value, providerId);
    const row = result.providers.find((p) => p.id === providerId);
    return row?.api_key ?? null;
  }

  function _setError(e: unknown): void {
    const err = e as { message?: string; technical_detail?: string | null };
    error.value = err?.message ?? String(e);
    const detail = err?.technical_detail;
    errorDetail.value = detail && detail !== error.value ? detail : null;
  }

  async function list(ws: string, rt: string): Promise<boolean> {
    loading.value = true;
    error.value = null;
    errorDetail.value = null;
    try {
      _apply(await ipc.ccSwitchProviders(ws, rt, agent.value));
      return true;
    } catch (e) {
      _setError(e);
      void ipc.logUiEvent?.("cc_switch_list", "error",
        (e as { code?: string })?.code ?? undefined);
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function switchAgent(a: CcSwitchAgent, ws: string, rt: string): Promise<void> {
    if (agent.value === a) return;
    agent.value = a;
    orderSeq.clear(); // per-agent namespace: the other agent re-pins afresh
    // PP r5 (user report): drop the stale list IMMEDIATELY — during the
    // fetch window the old agent's cards (with the 使用中 badge on the
    // wrong rows) used to linger into the new agent's view, defeating the
    // crossfade. The view's loading branch covers the gap.
    providers.value = [];
    await list(ws, rt);
  }

  async function _run(
    op: string, fn: () => Promise<{ providers: CcSwitchProvider[] }>,
  ): Promise<boolean> {
    busy.value = op;
    error.value = null;
    errorDetail.value = null;
    try {
      _apply(await fn());
      void ipc.logUiEvent?.(`cc_switch_${op.split(":")[0]}`, "ok");
      return true;
    } catch (e) {
      _setError(e);
      void ipc.logUiEvent?.(`cc_switch_${op.split(":")[0]}`, "error",
        (e as { code?: string })?.code ?? undefined);
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

  /** IDEA-5 (5d): tier 1 of the mapping dropdown. Never throws to the
   * caller — failures land in the result (available=false + message) and
   * the form falls back to known models + manual input. `apiKey` (PP r3):
   * the form's unsaved key, forwarded so fetch works before the first
   * save; it rides the stdin channel only and is never stored here. */
  async function fetchModels(
    ws: string, rt: string, providerId: string | null, apiKey?: string,
    baseUrl?: string,
  ): Promise<boolean> {
    // 手测 r2#3: providerId null = add-mode inline probe (form endpoint).
    const key = providerId ?? "__add__";
    busy.value = `fetch:${key}`;
    error.value = null;
    try {
      fetchedModels[key] =
        await ipc.ccSwitchFetchModels(ws, rt, agent.value, providerId, apiKey, baseUrl);
      void ipc.logUiEvent?.("cc_switch_fetch", "ok");
      return true;
    } catch (e) {
      fetchedModels[key] = {
        available: false, models: [],
        message: (e as { message?: string })?.message ?? String(e),
      };
      void ipc.logUiEvent?.("cc_switch_fetch", "error");
      return false;
    } finally {
      busy.value = "";
    }
  }

  /** O4 (D-11): the op segment of `busy` ("" | "add" | "edit" | "switch" |
   * "delete" | "fetch") — the tab uses it to scope disabling: mutating ops
   * stay mutually exclusive, while `fetch` (a read-only network query) no
   * longer freezes the whole panel. */
  const busyOp = computed(() => (busy.value ? busy.value.split(":")[0]! : ""));

  return {
    agent, providers, loading, busy, busyOp, error, errorDetail, fetchedModels,
    list, switchAgent, add, edit, activate, remove, fetchModels, revealKey,
  };
});
