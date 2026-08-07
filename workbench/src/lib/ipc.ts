/** Typed wrappers over the Workbench Tauri commands (S1.2-S1.4). */
import { Channel, invoke } from "@tauri-apps/api/core";
import type {
  BuildEvent,
  CapabilityReport,
  DiscoveryReport,
  PreflightReport,
  PtyEvent,
  RuntimeSnapshot,
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

export const startRuntime = (
  workspace: string,
  runtimeId: string,
  image: string | null = null,
  network: string | null = null,
  scope: string | null = null
) => invoke<RuntimeStartResult>("start_runtime", { workspace, runtimeId, image, network, scope });

export const stopRuntime = (runtimeId: string) => invoke<void>("stop_runtime", { runtimeId });

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

export const runtimeInspect = (runtimeId: string) =>
  invoke<RuntimeSnapshot>("runtime_inspect", { runtimeId });

export const runtimeRestart = (runtimeId: string) =>
  invoke<void>("runtime_restart", { runtimeId });

export const cancelRuntimeStart = () => invoke<void>("cancel_runtime_start");

// --- S2.1.b: build --events streaming ---

export const buildImage = (tag: string, onEvent: Channel<BuildEvent>) =>
  invoke<void>("build_image", { tag, onEvent });

export const cancelBuild = () => invoke<void>("cancel_build");
