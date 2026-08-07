/** Typed wrappers over the Workbench Tauri commands (S1.2-S1.4). */
import { Channel, invoke } from "@tauri-apps/api/core";
import type {
  CapabilityReport,
  DiscoveryReport,
  PtyEvent,
  RuntimeStartResult,
  SessionExit,
  SessionSnapshot,
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
  onEvent: Channel<PtyEvent>
) => invoke<SessionSnapshot>("open_session", { runtimeId, sessionId, agent, onEvent });

export const writeSession = (sessionId: string, bytes: number[]) =>
  invoke<void>("write_session", { sessionId, bytes });

export const resizeSession = (sessionId: string, cols: number, rows: number) =>
  invoke<void>("resize_session", { sessionId, cols, rows });

export const closeSession = (sessionId: string) => invoke<SessionExit>("close_session", { sessionId });

// --- S1.4: runtime control ---

export const startRuntime = (workspace: string, runtimeId: string) =>
  invoke<RuntimeStartResult>("start_runtime", { workspace, runtimeId });

export const stopRuntime = (runtimeId: string) => invoke<void>("stop_runtime", { runtimeId });
