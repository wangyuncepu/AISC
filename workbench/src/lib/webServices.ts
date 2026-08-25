/**
 * svc-0 (container web-service access): TypeScript mirror of the frozen
 * cross-language contract.
 *
 * Single source per language — Python `src/aisc/domain/web_services.py` is
 * authoritative; this module, Rust `web_services.rs` and the shared fixtures
 * under `tests/fixtures/web-services/` must stay in lockstep (decoded
 * identically — the svc-0 stage gate). See
 * docs/plans/container-service-access/decisions.md.
 *
 * Pure functions only; I/O lives in the store/IPC layers.
 */
import type { RuntimeServicesResult } from "../types";

/** Fixed container-side port the in-container gateway listens on. */
export const WEB_GATEWAY_CONTAINER_PORT = 45871;

/** Host loopback port range allocated to runtime gateways (inclusive). */
export const WEB_GATEWAY_HOST_PORT_MIN = 47000;
export const WEB_GATEWAY_HOST_PORT_MAX = 47999;

/** Registrable container service ports (non-privileged TCP only). */
export const WEB_SERVICE_PORT_MIN = 1024;
export const WEB_SERVICE_PORT_MAX = 65535;

/** Schema stamps (unknown versions fail closed at the decode boundary). */
export const WEB_SERVICE_SCHEMA_V1 = "aisc.web-service/v1";
export const RUNTIME_SERVICES_SCHEMA_V1 = "aisc.runtime-services/v1";

/** v1 protocol: HTTP/1.1-over-TCP (+ WebSocket upgrade). HTTPS is deferred. */
export const WEB_SERVICE_PROTOCOL = "http";

/** The gateway is host-published on loopback only, never 0.0.0.0. */
export const WEB_GATEWAY_HOST_BIND = "127.0.0.1";

/** URL scheme for user-facing service URLs (frozen for v1). */
export const WEB_SERVICE_URL_SCHEME = "http";

/** Hostname label the gateway routes on: `p<container-port>.localhost`. */
export const GATEWAY_HOST_SUFFIX = ".localhost";

/** Stable identifiers the in-container gateway returns on failures. */
export const WEB_ERROR_CODES = {
  badHost: "AISC_WEB_BAD_HOST",
  portInvalid: "AISC_WEB_PORT_INVALID",
  portNotExposed: "AISC_WEB_PORT_NOT_EXPOSED",
  targetUnavailable: "AISC_WEB_TARGET_UNAVAILABLE",
  registryUnavailable: "AISC_WEB_REGISTRY_UNAVAILABLE",
} as const;

/** Why `web_access.state` is `unavailable` (UI maps these to i18n strings). */
export const WEB_UNAVAILABLE_REASONS = [
  "legacy_runtime",
  "runtime_not_running",
  "gateway_unreachable",
  "docker_unavailable",
  "no_mapping",
] as const;

/** True when `port` is a registrable TCP port (1024..65535). */
export function isExposablePort(port: number): boolean {
  return Number.isInteger(port) && port >= WEB_SERVICE_PORT_MIN && port <= WEB_SERVICE_PORT_MAX;
}

/** Parse a service port argument; strict decimal string, bounded. Returns
 * `null` on anything else (mirrors Python `parse_expose_port` raising). */
export function parseExposePort(text: string): number | null {
  if (!/^[0-9]+$/.test(text)) return null;
  const port = Number.parseInt(text, 10);
  return isExposablePort(port) ? port : null;
}

/** Canonical user-facing URL: `http://p<container-port>.localhost:<host-port>/`.
 * Service labels never appear in the URL. Throws on out-of-range ports. */
export function buildServiceUrl(containerPort: number, hostPort: number): string {
  if (!isExposablePort(containerPort)) {
    throw new RangeError(`container port out of range: ${containerPort}`);
  }
  if (!Number.isInteger(hostPort) || hostPort < 1 || hostPort > 65535) {
    throw new RangeError(`host port out of range: ${hostPort}`);
  }
  return `${WEB_SERVICE_URL_SCHEME}://p${containerPort}${GATEWAY_HOST_SUFFIX}:${hostPort}/`;
}

const GATEWAY_HOST_RE = /^p([0-9]{1,5})\.localhost\.?(?::([0-9]{1,5}))?$/i;

/** Extract the container service port from a request Host header.
 * Accepts `p<port>.localhost` with an optional (ignored) gateway port suffix
 * and optional FQDN trailing dot, case-insensitive. `null` otherwise.
 * The port value is returned unvalidated; callers range-check separately. */
export function parseGatewayHost(hostValue: string): number | null {
  const m = GATEWAY_HOST_RE.exec(hostValue.trim());
  return m ? Number.parseInt(m[1], 10) : null;
}

/** Decode guard: an unknown schema version fails closed. */
export function isRuntimeServicesPayload(value: unknown): value is RuntimeServicesResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v.schema_version === RUNTIME_SERVICES_SCHEMA_V1;
}
