/**
 * Typed settings store (Step 3, 02 §三.4).
 *
 * The backend is the single source of truth: defaults live in Rust, unknown
 * fields survive round-trips, invalid fields fall back per-field with issues.
 * The store holds the loaded document, a last-saved snapshot for the dirty
 * indicator (A-G01-5: in-memory values are never conflated with what is on
 * disk), and save/reset with backend-side conflict replay.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as ipc from "../lib/ipc";
import { applyLocale } from "../i18n";
import type { SaveOutcome, SettingsDocument, SettingsPatch } from "../types";

export type SaveState = "idle" | "saving" | "saved" | "error";

function cloneDoc(d: SettingsDocument): SettingsDocument {
  return JSON.parse(JSON.stringify(d)) as SettingsDocument;
}

export const useSettingsStore = defineStore("settings", () => {
  const doc = ref<SettingsDocument | null>(null);
  /** Last known disk state (after load/save/reset). `dirty` compares against it. */
  const lastSaved = ref<SettingsDocument | null>(null);
  const saveState = ref<SaveState>("idle");
  const error = ref<string | null>(null);

  const loaded = computed(() => doc.value !== null);
  const readOnly = computed(() => doc.value?.readOnly ?? false);
  const corrupted = computed(() => doc.value?.corrupted ?? false);

  /** Any GUI field differs from the last saved/loaded disk state. */
  const dirty = computed(() => {
    if (!doc.value || !lastSaved.value) return false;
    return (
      JSON.stringify(doc.value.ui) !== JSON.stringify(lastSaved.value.ui) ||
      JSON.stringify(doc.value.terminal) !== JSON.stringify(lastSaved.value.terminal) ||
      JSON.stringify(doc.value.window) !== JSON.stringify(lastSaved.value.window)
    );
  });

  function applyDoc(d: SettingsDocument): void {
    doc.value = cloneDoc(d);
    lastSaved.value = cloneDoc(d);
    saveState.value = "idle";
    error.value = null;
  }

  async function load(): Promise<void> {
    try {
      applyDoc(await ipc.loadSettings());
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      saveState.value = "error";
    }
  }

  /** Apply GUI edits to the working copy (not persisted until save()). */
  function patch(p: SettingsPatch): void {
    if (!doc.value) return;
    if (p.ui) doc.value.ui = { ...doc.value.ui, ...p.ui };
    if (p.terminal) doc.value.terminal = { ...doc.value.terminal, ...p.terminal };
    if (p.window) doc.value.window = { ...doc.value.window, ...p.window };
  }

  /** Discard unsaved edits and return to the last saved/loaded state. */
  function cancel(): void {
    if (lastSaved.value) doc.value = cloneDoc(lastSaved.value);
    saveState.value = "idle";
    error.value = null;
  }

  /** G-09: language is immediate-effect - re-resolve the locale after a
   * persisted language change (explicit value wins; auto re-runs the chain). */
  async function applyLanguage(): Promise<void> {
    applyLocale(await ipc.resolveLocale(doc.value?.ui.language ?? "auto"));
  }

  async function save(): Promise<SaveOutcome | null> {
    if (!doc.value || saveState.value === "saving") return null;
    saveState.value = "saving";
    error.value = null;
    try {
      const outcome = await ipc.saveSettings(doc.value.revision, {
        ui: doc.value.ui,
        terminal: doc.value.terminal,
        window: doc.value.window,
      });
      doc.value.revision = outcome.revision;
      doc.value.issues = outcome.issues;
      lastSaved.value = cloneDoc(doc.value);
      saveState.value = "saved";
      await applyLanguage();
      void ipc.logUiEvent?.("settings_save", "ok");
      return outcome;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      saveState.value = "error";
      void ipc.logUiEvent?.("settings_save", "error",
        (e as { code?: string })?.code ?? undefined);
      return null;
    }
  }

  /** Reset GUI fields to defaults; aisc_cli_path/history/Runtime untouched.
   * Reloads from the backend so defaults never live in the frontend. */
  async function reset(): Promise<SaveOutcome | null> {
    if (!doc.value || saveState.value === "saving") return null;
    saveState.value = "saving";
    error.value = null;
    try {
      const outcome = await ipc.resetGuiSettings(doc.value.revision);
      applyDoc(await ipc.loadSettings());
      await applyLanguage(); // language back to auto -> re-resolve
      return outcome;
    } catch (e) {
      error.value = (e as { message?: string })?.message ?? String(e);
      saveState.value = "error";
      return null;
    }
  }

  // --- O7 (D-11): docker disk & cache panel (settings card) ---
  const cacheUsage = ref<import("../lib/ipc").CacheUsage | null>(null);
  const cacheBusy = ref(false);
  const cacheError = ref<string | null>(null);
  const cacheLog = ref<string[]>([]);

  async function loadCacheUsage(): Promise<void> {
    cacheBusy.value = true;
    cacheError.value = null;
    try {
      cacheUsage.value = await ipc.cacheUsage();
    } catch (e) {
      cacheError.value = (e as { message?: string })?.message ?? String(e);
    } finally {
      cacheBusy.value = false;
    }
  }

  async function runCacheCleanup(minAgeHours: number): Promise<void> {
    cacheBusy.value = true;
    cacheError.value = null;
    try {
      const result = await ipc.cacheCleanup(minAgeHours);
      for (const p of result.prunes) {
        cacheLog.value.push(
          `${p.kind}: ${p.reclaimed || (p.error ? "失败 " + p.error : "无回收")}`
        );
      }
      for (const w of result.warnings) cacheLog.value.push(`⚠ ${w}`);
      if (cacheLog.value.length > 20) cacheLog.value.splice(0, cacheLog.value.length - 20);
      cacheUsage.value = { dockerAvailable: true, rows: result.rows_after };
    } catch (e) {
      cacheError.value = (e as { message?: string })?.message ?? String(e);
    } finally {
      cacheBusy.value = false;
    }
  }

  return {
    doc,
    lastSaved,
    saveState,
    error,
    loaded,
    cacheUsage,
    cacheBusy,
    cacheError,
    cacheLog,
    loadCacheUsage,
    runCacheCleanup,
    readOnly,
    corrupted,
    dirty,
    load,
    patch,
    cancel,
    save,
    reset,
  };
});
