import { defineStore } from "pinia";
import { ref } from "vue";
import type { RuntimeInfo, SessionInfo } from "../types";

/** Minimal Workbench state (S1.1 scaffold).
 * Real runtime/session lifecycle + reconciliation arrives in S1.2/S1.3. */
export const useRuntimeStore = defineStore("runtime", () => {
  const runtime = ref<RuntimeInfo | null>(null);
  const sessions = ref<SessionInfo[]>([]);

  return { runtime, sessions };
});
