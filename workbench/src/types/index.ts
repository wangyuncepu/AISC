/** Minimal Workbench domain types (S1.1 scaffold).
 * Mirrors the aisc.cli/v1 JSON shapes consumed later (S1.2-S1.4). */

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
