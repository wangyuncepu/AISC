/** Typed wrappers over the Workbench Tauri commands (S1.2-S1.4). */
import { Channel, invoke } from "@tauri-apps/api/core";
import type {
  AckResult,
  BuildEvent,
  CapabilityReport,
  CcSwitchProvidersResult,
  CcSwitchRequest,
  DiagnosticBundle,
  DiscoveryReport,
  DoctorReport,
  EnvReadiness,
  FetchModelsResult,
  OpTrace,
  HistoryPatch,
  InstallerHandoff,
  OnboardingPatch,
  OnboardingState,
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
  SubscriptionStatus,
  UsageOverview,
  UsageRange,
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

// --- Stage 8e: cc-switch provider data plane (aisc.cc-switch-provider/v1) ---
// The request document (with any API key) rides the CLI child's stdin via the
// Rust side — never argv, never persisted.

export const ccSwitchProviders = (workspace: string, runtimeId: string, agent: string) =>
  invoke<CcSwitchProvidersResult>("cc_switch_providers", { workspace, runtimeId, agent });

export const ccSwitchAdd = (
  workspace: string, runtimeId: string, agent: string, request: CcSwitchRequest,
) => invoke<CcSwitchProvidersResult>("cc_switch_add", { workspace, runtimeId, agent, request });

export const ccSwitchEdit = (
  workspace: string, runtimeId: string, agent: string, providerId: string,
  request: CcSwitchRequest,
) => invoke<CcSwitchProvidersResult>("cc_switch_edit", {
  workspace, runtimeId, agent, providerId, request,
});

export const ccSwitchSwitch = (workspace: string, runtimeId: string, agent: string, providerId: string) =>
  invoke<CcSwitchProvidersResult>("cc_switch_switch", { workspace, runtimeId, agent, providerId });

export const ccSwitchDelete = (workspace: string, runtimeId: string, agent: string, providerId: string) =>
  invoke<CcSwitchProvidersResult>("cc_switch_delete", { workspace, runtimeId, agent, providerId });

/** IDEA-5 (5c): remote model list for the mapping dropdown. Degrades to
 * `available=false` (with the upstream message) instead of an error. */
export const ccSwitchFetchModels = (workspace: string, runtimeId: string, agent: string, providerId: string) =>
  invoke<FetchModelsResult>("cc_switch_fetch_models", { workspace, runtimeId, agent, providerId });

// --- IDEA-2 (2d): subscription + usage data plane ---
// The subscription URL / content ride the CLI child's stdin on the Rust side
// (credentials never travel via argv, logs or disk).

export const networkSubscriptionImport = (url: string) =>
  invoke<SubscriptionStatus>("network_subscription_import", { url });

export const networkSubscriptionImportFile = (content: string) =>
  invoke<SubscriptionStatus>("network_subscription_import_file", { content });

export const networkSubscriptionRefresh = () =>
  invoke<SubscriptionStatus>("network_subscription_refresh");

export const networkSubscriptionClear = () =>
  invoke<{ configured: boolean }>("network_subscription_clear");

export const networkSubscriptionShow = () =>
  invoke<SubscriptionStatus>("network_subscription_show");

export const usageOverview = (range: UsageRange, workspace?: string) =>
  invoke<UsageOverview>("usage_overview", { range, workspace: workspace ?? null });

/** IDEA-3 (3b): keyed by runtime_id — concurrent workspace starts each cancel
 * only their own op (a no-op once the start settled). */
export const cancelRuntimeStart = (runtimeId: string) =>
  invoke<void>("cancel_runtime_start", { runtimeId });

// --- S2.1.b: build --events streaming ---

export const buildImage = (tag: string, onEvent: Channel<BuildEvent>) =>
  invoke<void>("build_image", { tag, onEvent });

/** IDEA-3 (3b): keyed by the build tag. */
export const cancelBuild = (tag: string) => invoke<void>("cancel_build", { tag });

// --- S4.1.b fix: start the Docker engine (Docker Desktop) ---

export const startDocker = () => invoke<void>("start_docker");

// --- Stage 5 (A-ONB02): environment readiness (installed ≠ engine ready) ---

export const envReadiness = () => invoke<EnvReadiness>("env_readiness");

export const envPollEngine = (deadlineMs: number) =>
  invoke<EnvReadiness>("env_poll_engine", { deadlineMs });

// --- S2.4.a: history persistence (02 §九) ---

export const loadHistory = () => invoke<WorkbenchHistory>("load_history");

export const saveHistory = (expectedRevision: number, patch: HistoryPatch) =>
  invoke<number>("save_history", { expectedRevision, patch });

// --- Stage 5 (ONB-01): onboarding state (schema-versioned, no secrets) ---

export const onboardingLoad = () => invoke<OnboardingState>("onboarding_load");

export const onboardingUpdate = (patch: OnboardingPatch) =>
  invoke<OnboardingState>("onboarding_update", { patch });

// --- Stage 5 (A-INS01/A-ONB08): installer handoff (non-sensitive, D5-07) ---

export const installerHandoff = () => invoke<InstallerHandoff>("installer_handoff");

// --- G-10: window geometry save/restore (02 §A-G10) ---

export const captureWindowGeometry = () => invoke<boolean>("capture_window_geometry");

// --- G-13: one-click diagnosis (05 §六, Step 12) ---

export const runDoctor = () => invoke<DoctorReport>("run_doctor");

// --- Stage 6 (REL-01): op-trace ring + redacted diagnostic bundle ---

export const opTraces = () => invoke<OpTrace[]>("op_traces");
export const diagnosticBundle = (writePath?: string) =>
  invoke<DiagnosticBundle>("diagnostic_bundle", { writePath: writePath ?? null });

// --- G-16: tray availability (03 §A-G16-4, Step 15) ---

export const trayAvailable = () => invoke<boolean>("tray_available");

/** Hide the tray icon immediately after the exit confirm passes (the window
 * already hides instantly; cleanup continues in the background). */
export const trayRemove = () => invoke<void>("tray_remove");

// --- Stage 3 (3c): Workspace Explorer + Agent Artifacts ---

export const artifactList = (kind: string | null = null, cursor: number | null = null) =>
  invoke<import("../types").ArtifactListResult>("artifact_list", { kind, cursor });

export const artifactInspect = (artifactId: string) =>
  invoke<import("../types").ArtifactInspectResult>("artifact_inspect", { artifactId });

export const artifactRefresh = (workspace: string) =>
  invoke<unknown>("artifact_refresh", { workspace });

export const workspaceList = (
  workspace: string,
  relativeDir: string,
  cursor: string | null = null,
  includeIgnored = false,
) =>
  invoke<import("../types").WorkspaceListResult>("workspace_list", {
    workspace,
    relativeDir,
    cursor: cursor ? Number(cursor) : null,
    includeIgnored,
  });

export const workspaceOpen = (workspace: string, relativePath: string) =>
  invoke<void>("workspace_open", { workspace, relativePath });

export const workspacePreview = (workspace: string, relativePath: string) =>
  invoke<import("../types").WorkspacePreviewResult>("workspace_preview", {
    workspace,
    relativePath,
  });

export const workspaceReveal = (workspace: string, relativePath: string) =>
  invoke<void>("workspace_reveal", { workspace, relativePath });

export const workspaceCopyPath = (workspace: string, relativePath: string) =>
  invoke<import("../types").WorkspaceCopyResult>("workspace_copy_path", {
    workspace,
    relativePath,
  });

// --- Stage 3 (3d): workspace watcher ---

export const workspaceWatchStart = (workspace: string) =>
  invoke<void>("workspace_watch_start", { workspace });

export const workspaceWatchStop = () => invoke<void>("workspace_watch_stop");

export const workspaceRescan = (workspace: string) =>
  invoke<void>("workspace_rescan", { workspace });
