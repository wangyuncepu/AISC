/** Minimal Workbench domain types (S1.1 scaffold + S1.4 UI types).
 * Mirrors the aisc.cli/v1 JSON shapes and Workbench Tauri command payloads. */

export type Agent = "claude" | "codex" | "bash" | "cc-switch";

export interface RuntimeConfig {
  workspace: string;
  image: string;
  network: "direct" | "proxy";
  scope: "project" | "temporary";
}

export type RuntimeState =
  | "unknown"
  | "not_found"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "removing";

export interface RuntimeInfo {
  runtime_id: string;
  container_name: string;
  state: RuntimeState;
  config: RuntimeConfig;
}

export type SessionState =
  | "starting"
  | "running"
  | "closing"
  | "exited"
  | "failed"
  | "disconnected";

export interface SessionInfo {
  session_id: string;
  runtime_id: string;
  agent: Agent;
  state: SessionState;
  exit_code: number | null;
}

// --- S1.2: CLI runner / capability / errors ---

export type WorkbenchAction =
  | "retry"
  | "refresh"
  | "upgrade_cli"
  | "start_docker"
  | "build_image"
  | "choose_workspace"
  | "choose_cli"
  | "none";

export interface WorkbenchError {
  code: string;
  message: string;
  technical_detail: string | null;
  retryable: boolean;
  action: WorkbenchAction;
}

export interface VersionInfo {
  cli_version: string | null;
  bundle_version: string | null;
  contract_version: string | null;
  image_version: string | null;
  claude_version: string | null;
  python_version: string | null;
}

export interface Capabilities {
  runtime: string | null;
  session: string | null;
  providerStatus: string | null;
  buildEvents: string | null;
}

export interface CapabilityReport {
  required_ok: boolean;
  runtime: boolean;
  session: boolean;
  provider_status: boolean;
  build_events: boolean;
  missing_required: string[];
  missing_optional: string[];
  version_info: VersionInfo | null;
  error: WorkbenchError | null;
}

export type CandidateSource = "explicit" | "saved" | "path" | "platform" | "sidecar";

export interface Candidate {
  path: string;
  source: CandidateSource;
  valid: boolean;
  version_info: VersionInfo | null;
  capabilities: Capabilities | null;
  error: string | null;
}

export interface DiscoveryReport {
  candidates: Candidate[];
  selected: string | null;
  needs_confirm: boolean;
  error: WorkbenchError | null;
}

// --- S1.3: PTY / session ---

export interface SessionSnapshot {
  session_id: string;
  runtime_id: string;
  agent: Agent;
  state: SessionState;
  generation: number;
}

export type AckResult = "acknowledged" | "already_acknowledged";

/** Result of the unified exit coordinator (03 §4.3). */
export interface ShutdownReport {
  graceful_closed: number;
  force_reaped: number;
  terminate_timed_out: number;
  reap_timed_out: number;
  unreaped_session_ids: string[];
  flush_errors: string[];
}

export interface SessionExit {
  exit_code: number | null;
  reason: string;
  finished_at_ms: number;
}

export type PtyEvent =
  | { type: "output"; seq: number; bytes: string }
  | { type: "exit"; reason: string; exitCode: number | null }
  | { type: "error"; code: string; message: string };

// --- S1.4: runtime control ---

export interface RuntimeStartResult {
  runtime_id: string;
  container_name: string;
  state: string;
  ready: boolean;
}

/** Request for Terminal.vue to open a session (owned by the store). */
export interface SessionRequest {
  runtimeId: string;
  sessionId: string;
}

// --- S2.1.a: preflight + inspect ---

export type CheckStatus = "pass" | "warn" | "fail";

export interface PreflightCheck {
  id: string; // docker | workspace | image | network | runtime_conflict
  status: CheckStatus;
  error_code: string | null;
  detail: string | null;
}

export type RecommendedAction = "start" | "reuse" | "restart" | "resolve_conflict";

export interface PreflightReport {
  spec: unknown;
  checks: PreflightCheck[];
  can_start: boolean;
  recommended_action: RecommendedAction;
  matching_runtime_id: string | null;
  conflicts: unknown;
  observed_at: string;
}

/** `aisc runtime inspect/list/stop/restart/remove` snapshot (05 §5.3-5.5).
 * Mirrors the CLI RuntimeSnapshot.to_dict(); no `ready` field (that is on the
 * start payload only). */
export interface RuntimeSnapshot {
  runtime_id: string;
  state: RuntimeState;
  config: RuntimeConfig;
  owner: string;
  config_fingerprint: string;
  container_name: string;
  container_id: string;
  registry_state: string;
  observed_at: string;
  stale: boolean;
}

/** `aisc runtime list` envelope data (05 §5.3). */
export interface RuntimeListResult {
  runtimes: RuntimeSnapshot[];
  observed_at: string;
}

/** `aisc provider current` snapshot (05 §七). Secret-free: routing/auth only.
 * `agent` is claude | codex (bash/cc-switch are not applicable). */
export interface ProviderStatus {
  runtime_id: string;
  agent: Agent;
  provider_id: string;
  provider_name: string;
  route_mode: string; // official-direct | cc-switch-proxy | unknown
  auth_status: string; // configured | login_required | not_configured | unknown
  observed_at: string;
}

// --- S2.4.a: workbench history (02 §九.2 subset) ---

export interface RuntimeRef {
  runtime_id: string;
  image: string;
  network: string;
  scope: string;
}

export interface TabRecord {
  tab_id: string;
  agent: Agent;
  title: string;
  position: number;
}

export interface Layout {
  active_tab_id: string | null;
  tabs: TabRecord[];
}

export interface WorkspaceRecord {
  path: string;
  last_used_at: string;
  pinned: boolean;
  last_agent: string;
  runtime: RuntimeRef | null;
  layout: Layout | null;
}

/** Patch a window submits to save_history: workspaces to upsert by path. */
export interface HistoryPatch {
  workspaces: WorkspaceRecord[];
}

export interface WorkbenchHistory {
  schema_version: number;
  revision: number;
  workspaces: WorkspaceRecord[];
}

export type LaunchAgent = "claude" | "codex" | "bash" | "cc-switch";

export interface LaunchConfig {
  agent: LaunchAgent;
  image: string;
  network: "direct" | "proxy";
  scope: "project" | "temporary";
}

// --- S2.1.b: build events (05 §4.1) ---

export interface BuildEvent {
  protocol?: string;
  command?: string;
  run_id?: string;
  seq?: number;
  type: string; // build.start | build.plan | build.output | build.complete | build.failed | build.cancelled
  ts?: string;
  data?: Record<string, unknown>;
}

export type BuildStatus = "idle" | "building" | "complete" | "failed" | "cancelled";

// --- S2.3.a: observability (04 §六.1) ---

/** Runtime observation freshness quality (not a Runtime state). */
export type Freshness = "fresh" | "stale" | "unknown";

// --- S2.2.a: multi-tab (03 §五/§六) ---

/** Per-tab session lifecycle. `idle` = never opened; the rest mirror SessionState. */
export type TabSessionState = "idle" | SessionState;

/** Minimal exit info shown on an exited/failed tab (reason + code only). */
export interface TabExit {
  reason: string;
  exitCode: number | null;
}

/**
 * A fixed agent tab (03 §六). `sessionId` is null while idle or after exit;
 * the session state machine drives the binding (idle -> starting -> running ->
 * exited/disconnected/failed). Tab identity persists for the workspace session;
 * history persistence lands in S2.4.
 */
export interface Tab {
  tabId: string;
  agent: LaunchAgent;
  title: string;
  sessionId: string | null;
  sessionState: TabSessionState;
  exit: TabExit | null;
  /** Saved history tab_id when restored (02 §2.3 saved→new mapping); null for
   * freshly created tabs. */
  savedTabId: string | null;
}
