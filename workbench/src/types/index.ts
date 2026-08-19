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

// --- G-13: one-click diagnosis (05 §六, Step 12) ---

export type DoctorStatus = "pass" | "warn" | "fail" | "skip";

/** One `aisc doctor` host check (05 §六): hint/detail are per-check, already
 * redacted Rust-side; unknown fields are ignored. */
export interface DoctorCheck {
  name: string;
  status: DoctorStatus;
  message: string;
  detail: string | null;
  hint: string | null;
}

export interface DoctorSummary {
  passed: number;
  warnings: number;
  failures: number;
  skipped: number;
}

/** `data.host` from the doctor envelope; `data.container` is not surfaced. */
export interface DoctorReport {
  checks: DoctorCheck[];
  summary: DoctorSummary;
}

/** Stage 6 (REL-01): one bounded operation trace. */
export interface OpTrace {
  operationId: string;
  source: string; // rust | cli | docker | ui
  phase: string;
  durationMs: number;
  outcome: string; // ok | error | cancel
  errorCode: string | null;
  retryable: boolean;
  action: string | null;
  detail: string | null;
}

/** Stage 6 (REL-01): allowlisted redacted diagnostic bundle (D6-05/06). */
export interface DiagnosticBundle {
  generatedAtMs: number;
  appVersion: string;
  platform: string;
  settings: unknown;
  envReadiness: EnvReadiness;
  doctor: DoctorReport | null;
  recentOperations: OpTrace[];
  /** Stage 7 (DATA-04): canonical data root { root, origin }. */
  dataRoot: { root: string; origin: string } | null;
  path: string | null;
}

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

// --- Stage 8e (CS-05/06): cc-switch provider data plane (v1, secret-free) ---

/** One provider row from the in-container adapter snapshot. The API key is
 * only ever represented as `api_key_mask` (**** + last 4). */
export interface CcSwitchProvider {
  id: string;
  name: string;
  app_type: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_mask: string;
  is_current: boolean;
  /** IDEA-5 (5c): secret-free whitelist view of the role-model env (five
   * slots + effort + base URL); credential keys are structurally absent.
   * Optional: older CLI envelopes predate it. */
  role_env?: Record<string, string>;
  /** Preset rows: historical ∪ current preset-written model ids (the
   * offline dropdown tier); custom rows carry an empty list. Optional for
   * the same envelope-compat reason. */
  known_models?: string[];
}

/** `aisc cc-switch fetch-models` result — tier 1 of the mapping dropdown.
 * `available=false` carries the upstream message (e.g. HTTP 401) as a hint;
 * the UI falls back to known_models + manual input. */
export interface FetchModelsResult {
  available: boolean;
  models: string[];
  message: string;
}

export interface CcSwitchProvidersResult {
  agent: string;
  providers: CcSwitchProvider[];
  operation_id: string;
}

/** Request document for add/edit. `api_key` is the secret channel (transient
 * form state → Tauri IPC → CLI stdin; never argv/storage/logs). */
export interface CcSwitchRequest {
  mode?: "simple" | "custom";
  id?: string;
  provider?: string; // preset id (simple mode)
  name?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
  patch?: {
    name?: string;
    base_url?: string;
    model?: string;
    env?: Record<string, string | null>;
  };
}

// --- IDEA-2 (2d): subscription status + provider token usage ---

/** Raw `subscription-userinfo` header values (bytes / unix seconds); the
 * whole object is null when the source provided no usage header. */
export interface SubscriptionUserInfo {
  upload?: number;
  download?: number;
  total?: number; // 0 = unlimited plan
  expire?: number;
}

/** Secret-free subscription snapshot (envelope of `aisc network subscription
 * …`); the full URL only ever lives in the data-root snapshot file. */
export interface SubscriptionStatus {
  configured: boolean;
  source: "download" | "manual" | null;
  url_masked: string | null;
  fetched_at: string | null;
  config_sha256: string | null;
  has_config_file: boolean;
  userinfo: SubscriptionUserInfo | null;
  config_path?: string;
}

export type UsageRange = "today" | "7d" | "30d";

/** Per-provider aggregation row (tokens = input+output+cache read+creation). */
export interface UsageProviderRow {
  app: string;
  provider_id: string;
  provider_name: string;
  requests: number;
  success: number;
  failed: number;
  tokens_total: number;
  cost_estimate: number;
  currency: string;
}

export interface UsageModelRow {
  app: string;
  model: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost_estimate: number;
}

export interface UsageWorkspaceEntry {
  workspace_hash: string;
  workspace_path: string;
  running: boolean;
  container: string;
  source: "live" | "cache" | "none";
  fetched_at: string | null;
  available: boolean;
  providers: UsageProviderRow[];
  models: UsageModelRow[];
}

export interface UsageOverview {
  subscription: SubscriptionStatus;
  range: UsageRange | string;
  since: number;
  workspaces: UsageWorkspaceEntry[];
  totals: {
    providers: UsageProviderRow[];
    requests: number;
    tokens_total: number;
    cost_estimate: number;
  };
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
  /** G-17: the tab's split tree (absent for a flat G-08 tab). */
  split_layout?: SplitLayout | null;
}

export interface Layout {
  active_tab_id: string | null;
  tabs: TabRecord[];
}

// --- G-17 (Step 16): PaneTree model (03 §6.1/6.3) ---

export type SplitAxis = "horizontal" | "vertical";

/** In-memory PaneTree tagged union (camelCase; see stores/paneTree.ts ops). */
export interface PaneSplitNode {
  kind: "split";
  axis: SplitAxis;
  ratio: number;
  first: PaneNode;
  second: PaneNode;
}
export interface PaneLeafNode {
  kind: "pane";
  paneId: string;
  sessionType: LaunchAgent;
}
export type PaneNode = PaneSplitNode | PaneLeafNode;

/** Persisted PaneTree tagged union (snake_case, mirrors the Rust PaneNode).
 * History schema v2. */
export type PersistedPaneNode =
  | {
      kind: "split";
      axis: SplitAxis;
      ratio: number;
      first: PersistedPaneNode;
      second: PersistedPaneNode;
    }
  | { kind: "pane"; pane_id: string; session_type: LaunchAgent };

/** Per-tab split layout persisted in history v2. */
export interface SplitLayout {
  version: number;
  active_pane_id: string;
  root: PersistedPaneNode;
}

/** Live per-pane session state (pane tree leaf runtime; the pane's static
 * session type lives in the leaf, not here). */
export interface PaneRuntime {
  sessionId: string | null;
  sessionState: TabSessionState;
  exit: TabExit | null;
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

// --- Stage 5 (ONB-01): onboarding state (schema-versioned, no secrets) ---

export type OnboardingStatus =
  | "not_started"
  | "in_progress"
  | "skipped"
  | "blocked"
  | "completed"
  | "abandoned";

export interface OnboardingState {
  schema_version: number;
  flow_version: number;
  status: OnboardingStatus;
  current_step: string;
  completed_steps: string[];
  skipped_steps: string[];
  last_error_code: string;
  source: string;
}

/** Frontend patch to onboarding_update; all fields optional, never secrets. */
export interface OnboardingPatch {
  status?: OnboardingStatus;
  currentStep?: string;
  completeStep?: string;
  skipStep?: string;
  lastErrorCode?: string;
  source?: string;
}

/** Installer handoff facts (NSIS → Workbench, non-sensitive, never a fact — D5-07). */
export interface InstallerHandoff {
  installer_source: string;
  installed_version: string;
  first_run: boolean;
  docker_hint: string;
  present: boolean;
  product_name: string;
}

// --- Stage 5 (A-ONB02): environment readiness (installed ≠ engine ready) ---

export interface EnvReadiness {
  cli: string;        // unknown | checking | ready | unavailable
  docker: string;     // unknown | not_installed | installing | installed | starting | ready | blocked
  engine: string;     // unknown | unavailable | starting | ready | permission_denied
  webview2: string;   // unknown | ready | missing
  dockerDesktopPath: string;
  cliPath: string;
  /** Redacted reason the engine probe is not ready (spawn err / exit / timeout /
   *  docker CLI missing). "" when ready. Surfaced for diagnostics (Stage 6 KI-1). */
  engineDetail: string;
}

export type LaunchAgent = "claude" | "codex" | "bash" | "cc-switch";

export interface LaunchConfig {
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
export type TabSessionState = "idle" | "guide" | SessionState;

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
 *
 * G-17 (Step 16): a tab owns a PaneTree. `agent`/`sessionId`/`sessionState`/
 * `exit` remain the ACTIVE pane projection (so TabBar/sidebar/title keep
 * working); `tree`/`activePaneId`/`panes` hold the pane model. A G-08 flat tab
 * is a single-leaf tree.
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
  /** G-17: the tab's split tree (camelCase in-memory PaneNode). */
  tree: PaneNode;
  /** G-17: active pane id (the session projection mirrors this pane). */
  activePaneId: string;
  /** G-17: per-pane live state keyed by pane id (always holds the active pane). */
  panes: Record<string, PaneRuntime>;
}

// --- Step 3: typed settings (02 §三.4; wire sections are snake_case, the
// document envelope is camelCase - defaults live in Rust, never here) ---

export interface UiSettings {
  language: string; // auto | zh-CN | en-US
  font_scale: number; // 0.80..=1.50
  theme: string; // system | dark | light
  /** User-configured Explorer ignore names (WX-01); complements built-ins. */
  explorer_ignore: string[];
  /** The agent tab the tab-bar + split button creates (IDEA-1); claude |
   * codex | bash | cc-switch. Defaults to "bash" in the Rust backend. */
  default_tab_agent: string;
  /** IDEA-3 (3f round 3): the workspace-bar `+` default target page
   * (workspace | settings; future feature pages extend this). */
  default_new_page: string;
}

export interface TerminalSettings {
  font_family: string; // non-empty, <=256
  font_size: number; // 10..=24
  line_height: number; // 1.0..=1.6
  letter_spacing: number; // -1..=3
  scrollback: number; // 1000..=50000
  renderer: string; // auto | default | webgl
  smooth_scroll_duration: number; // 0..=500 ms
}

export interface WindowGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  maximized: boolean;
}

export interface WindowSettings {
  remember_geometry: boolean;
  close_behavior: string; // quit | minimize-to-tray
  geometry: WindowGeometry | null;
}

export interface ValidationIssue {
  field: string;
  reason: string;
}

export interface SettingsDocument {
  schemaVersion: number;
  revision: number;
  aiscCliPath: string | null;
  ui: UiSettings;
  terminal: TerminalSettings;
  window: WindowSettings;
  issues: ValidationIssue[];
  /** On-disk file was corrupt and isolated; app runs on defaults. */
  corrupted: boolean;
  /** On-disk schema is newer than supported: read-only, saves refused. */
  readOnly: boolean;
}

/** Section-level GUI patch. Omitted sections stay unchanged. */
export interface SettingsPatch {
  ui?: UiSettings;
  terminal?: TerminalSettings;
  window?: WindowSettings;
}

export interface SaveOutcome {
  revision: number;
  issues: ValidationIssue[];
}

// --- Stage 3 (3c): Workspace Explorer + Agent Artifacts ---

export interface ArtifactRecord {
  schema_version: number;
  artifact_id: string;
  workspace_relative_path: string;
  action: "created" | "modified" | "deleted" | "renamed";
  kind: "deliverable" | "source_change" | "generated_output";
  media_type: string | null;
  label: string;
  open_with: "preview" | "system" | "reveal" | "none";
  producer: { agent: string; session_id: string; runtime_id: string };
  state: "present" | "deleted" | "moved" | "missing";
  provenance: "manifest" | "workspace_change";
  recorded_at: string;
  previous_path: string | null;
  extra: Record<string, unknown>;
}

export interface ArtifactListResult {
  schema_version: number;
  artifacts: ArtifactRecord[];
  next_cursor: number | null;
}

export interface ArtifactInspectResult {
  artifact: ArtifactRecord;
}

export interface WorkspaceNode {
  relative_path: string;
  name: string;
  kind: "dir" | "file";
  expandable: boolean;
  artifact_badges: string[];
  change_state: string;
}

export interface WorkspaceListResult {
  schema_version: number;
  nodes: WorkspaceNode[];
  next_cursor: string | null;
  truncated: boolean;
}

export interface WorkspacePreviewResult {
  relative_path: string;
  media_type: string;
  size: number;
  text: string | null;
  base64: string | null;
  truncated: boolean;
}

export interface WorkspaceCopyResult {
  relative_path: string;
  absolute_path: string;
}
