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
  | "starting"
  | "running"
  | "stopped"
  | "not_found"
  | "unknown";

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

export type CandidateSource = "explicit" | "saved" | "path" | "platform";

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
