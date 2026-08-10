/** Typed wrappers over the Workbench Tauri commands (S1.2-S1.4). */
import { Channel, invoke } from "@tauri-apps/api/core";
import type {
  AckResult,
  BuildEvent,
  CapabilityReport,
  DiscoveryReport,
  DoctorReport,
  HistoryPatch,
  PreflightReport,
  ProviderStatus,
  PtyEvent,
  RuntimeListResult,
  RuntimeSnapshot,
  RuntimeStartResult,
  SaveOutcome,
  SessionExit,
  SessionSnapshot,
  SettingsDocument,
  SettingsPatch,
  ShutdownReport,
  WorkbenchHistory,
} from "../types";

// --- S1.2: CLI discovery / pin / capability ---

export const negotiateCapabilities = () => invoke<CapabilityReport>("negotiate_capabilities");

export const cliDiscover = (explicitPath: string | null = null) =>
  invoke<DiscoveryReport>("cli_discover", { explicitPath });

export const cliPin = (path: string) => invoke<CapabilityReport>("cli_pin", { path });

// --- S1.3: session data plane ---

export const openSession = (
  runtimeId: string,
  sessionId: string,
  agent: string,
  workspace: string,
  onEvent: Channel<PtyEvent>
) => invoke<SessionSnapshot>("open_session", { runtimeId, sessionId, agent, workspace, onEvent });

export const writeSession = (sessionId: string, bytes: number[]) =>
  invoke<void>("write_session", { sessionId, bytes });

export const resizeSession = (sessionId: string, cols: number, rows: number) =>
  invoke<void>("resize_session", { sessionId, cols, rows });

export const closeSession = (sessionId: string) => invoke<SessionExit>("close_session", { sessionId });

/** Natural-exit ack (03 §3.3): idempotent, removes terminal registry entries. */
export const ackSessionExit = (sessionId: string) =>
  invoke<AckResult>("ack_session_exit", { sessionId });

/** Unified exit coordinator: bounded session close + force-reap + flush. */
export const shutdownWorkbench = (stopRuntime: boolean = false) =>
  invoke<ShutdownReport>("shutdown_workbench", { stopRuntime });

// --- Step 3: typed settings (02 §三.4; conflict replay is Rust-side) ---

export const loadSettings = () => invoke<SettingsDocument>("load_settings");

export const saveSettings = (expectedRevision: number, patch: SettingsPatch) =>
  invoke<SaveOutcome>("save_settings", { expectedRevision, patch });

export const resetGuiSettings = (expectedRevision: number) =>
  invoke<SaveOutcome>("reset_gui_settings", { expectedRevision });

/** Resolve the final locale (explicit > installer > system > zh-CN). */
export const resolveLocale = (language: string | null = null) =>
  invoke<string>("resolve_locale", { language });

// --- S1.4: runtime control ---

export const startRuntime = (
  workspace: string,
  runtimeId: string,
  image: string | null = null,
  network: string | null = null,
  scope: string | null = null
) => invoke<RuntimeStartResult>("start_runtime", { workspace, runtimeId, image, network, scope });

export const stopRuntime = (workspace: string, runtimeId: string) =>
  invoke<RuntimeSnapshot>("stop_runtime", { workspace, runtimeId });

// --- S2.1.a: preflight / inspect / restart / cancel ---

export const runtimePreflight = (
  workspace: string,
  runtimeId: string,
  image: string | null = null,
  network: string | null = null,
  scope: string | null = null
) =>
  invoke<PreflightReport>("runtime_preflight", {
    workspace,
    runtimeId,
    image,
    network,
    scope,
  });

export const runtimeInspect = (workspace: string, runtimeId: string) =>
  invoke<RuntimeSnapshot>("runtime_inspect", { workspace, runtimeId });

export const runtimeRestart = (workspace: string, runtimeId: string) =>
  invoke<RuntimeSnapshot>("runtime_restart", { workspace, runtimeId });

export const listRuntimes = (workspace: string, owner: string | null = null) =>
  invoke<RuntimeListResult>("list_runtimes", { workspace, owner });

export const removeRuntime = (workspace: string, runtimeId: string, force = false) =>
  invoke<RuntimeSnapshot>("remove_runtime", { workspace, runtimeId, force });

export const getProviderStatus = (workspace: string, runtimeId: string, agent: string) =>
  invoke<ProviderStatus>("get_provider_status", { workspace, runtimeId, agent });

export const cancelRuntimeStart = () => invoke<void>("cancel_runtime_start");

// --- S2.1.b: build --events streaming ---

export const buildImage = (tag: string, onEvent: Channel<BuildEvent>) =>
  invoke<void>("build_image", { tag, onEvent });

export const cancelBuild = () => invoke<void>("cancel_build");

// --- S4.1.b fix: start the Docker engine (Docker Desktop) ---

export const startDocker = () => invoke<void>("start_docker");

// --- S2.4.a: history persistence (02 §九) ---

export const loadHistory = () => invoke<WorkbenchHistory>("load_history");

export const saveHistory = (expectedRevision: number, patch: HistoryPatch) =>
  invoke<number>("save_history", { expectedRevision, patch });

// --- G-10: window geometry save/restore (02 §A-G10) ---

export const captureWindowGeometry = () => invoke<boolean>("capture_window_geometry");

// --- G-13: one-click diagnosis (05 §六, Step 12) ---

export const runDoctor = () => invoke<DoctorReport>("run_doctor");
