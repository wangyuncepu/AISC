//! svc-0 (container web-service access): Rust mirror of the frozen
//! cross-language contract.
//!
//! Python `src/aisc/domain/web_services.py` is authoritative; this module,
//! the TS `workbench/src/lib/webServices.ts` and the shared fixtures under
//! `tests/fixtures/web-services/` stay in lockstep (the svc-0 stage gate).
//! Pure data + validation only; IPC commands live in runtime.rs (svc-2/4).
//!
//! See docs/plans/container-service-access/decisions.md.

use serde::{Deserialize, Serialize};

/// Fixed container-side port the in-container gateway listens on.
pub const WEB_GATEWAY_CONTAINER_PORT: u16 = 45871;

/// Host loopback port range allocated to runtime gateways (inclusive).
pub const WEB_GATEWAY_HOST_PORT_MIN: u16 = 47000;
pub const WEB_GATEWAY_HOST_PORT_MAX: u16 = 47999;

/// Registrable container service ports (non-privileged TCP only).
pub const WEB_SERVICE_PORT_MIN: u16 = 1024;
pub const WEB_SERVICE_PORT_MAX: u16 = 65535;

/// Schema stamps (unknown versions fail closed at the decode boundary).
pub const WEB_SERVICE_SCHEMA_V1: &str = "aisc.web-service/v1";
pub const RUNTIME_SERVICES_SCHEMA_V1: &str = "aisc.runtime-services/v1";

/// v1 protocol: HTTP/1.1-over-TCP (+ WebSocket upgrade). HTTPS is deferred.
pub const WEB_SERVICE_PROTOCOL: &str = "http";

/// The gateway is host-published on loopback only, never 0.0.0.0.
pub const WEB_GATEWAY_HOST_BIND: &str = "127.0.0.1";

/// URL scheme for user-facing service URLs (frozen for v1).
pub const WEB_SERVICE_URL_SCHEME: &str = "http";

/// Hostname label the gateway routes on: `p<container-port>.localhost`.
pub const GATEWAY_HOST_SUFFIX: &str = ".localhost";

/// True when `port` is a registrable TCP port (1024..65535).
pub fn is_exposable_port(port: u16) -> bool {
    (WEB_SERVICE_PORT_MIN..=WEB_SERVICE_PORT_MAX).contains(&port)
}

/// Canonical user-facing URL: `http://p<container-port>.localhost:<host-port>/`.
/// Service labels never appear in the URL.
pub fn build_service_url(container_port: u16, host_port: u16) -> String {
    format!(
        "{WEB_SERVICE_URL_SCHEME}://p{container_port}{GATEWAY_HOST_SUFFIX}:{host_port}/"
    )
}

/// Gateway reachability snapshot; shared by `RuntimeSnapshot.web_access`
/// (svc-2) and `RuntimeServicesResult.gateway`. `reason` is present only
/// when unavailable — a missing key decodes as absent.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct WebGatewayInfo {
    pub state: String, // "ready" | "unavailable"
    #[serde(default = "default_container_port")]
    pub container_port: u16,
    #[serde(default)]
    pub host_port: u16,
    #[serde(default = "default_host_bind")]
    pub host: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub reason: String,
}

fn default_container_port() -> u16 {
    WEB_GATEWAY_CONTAINER_PORT
}

fn default_host_bind() -> String {
    WEB_GATEWAY_HOST_BIND.to_string()
}

/// One service row in a `runtime services` payload (URL attached).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WebServiceInfo {
    pub port: u16,
    #[serde(default = "default_protocol")]
    pub protocol: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub state: String, // v1: only "registered"
    #[serde(default)]
    pub url: String,
}

fn default_protocol() -> String {
    WEB_SERVICE_PROTOCOL.to_string()
}

/// `aisc runtime services` payload (schema aisc.runtime-services/v1).
/// Decode is strict on the schema stamp — see `decode_runtime_services`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeServicesResult {
    pub schema_version: String,
    pub runtime_id: String,
    pub gateway: WebGatewayInfo,
    #[serde(default)]
    pub services: Vec<WebServiceInfo>,
    #[serde(default)]
    pub observed_at: String,
}

/// Fail-closed decode: a foreign or missing schema version is a protocol
/// error, not an empty result.
pub fn decode_runtime_services(raw: &[u8]) -> Result<RuntimeServicesResult, String> {
    let value: serde_json::Value =
        serde_json::from_slice(raw).map_err(|e| format!("invalid JSON: {e}"))?;
    let schema = value
        .get("schema_version")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if schema != RUNTIME_SERVICES_SCHEMA_V1 {
        return Err(format!("unsupported schema_version: {schema:?}"));
    }
    serde_json::from_value(value).map_err(|e| format!("payload shape: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn constants_mirror_python() {
        assert_eq!(WEB_GATEWAY_CONTAINER_PORT, 45871);
        assert_eq!(WEB_GATEWAY_HOST_PORT_MIN, 47000);
        assert_eq!(WEB_GATEWAY_HOST_PORT_MAX, 47999);
        assert_eq!(WEB_SERVICE_PORT_MIN, 1024);
        assert_eq!(WEB_SERVICE_PORT_MAX, 65535);
        assert_eq!(WEB_GATEWAY_HOST_BIND, "127.0.0.1");
        assert_eq!(WEB_SERVICE_SCHEMA_V1, "aisc.web-service/v1");
        assert_eq!(RUNTIME_SERVICES_SCHEMA_V1, "aisc.runtime-services/v1");
    }

    #[test]
    fn url_builder_is_canonical() {
        assert_eq!(build_service_url(3000, 47831), "http://p3000.localhost:47831/");
        assert_eq!(build_service_url(5173, 47000), "http://p5173.localhost:47000/");
    }

    #[test]
    fn exposable_bounds() {
        assert!(!is_exposable_port(1023));
        assert!(is_exposable_port(1024));
        assert!(is_exposable_port(65535));
    }

    #[test]
    fn gateway_reason_round_trips_conditionally() {
        let ready = WebGatewayInfo {
            state: "ready".into(),
            container_port: 45871,
            host_port: 47831,
            host: "127.0.0.1".into(),
            reason: String::new(),
        };
        let json = serde_json::to_value(&ready).unwrap();
        assert!(json.get("reason").is_none(), "ready omits reason");
        let back: WebGatewayInfo = serde_json::from_value(json).unwrap();
        assert_eq!(back, ready);

        let legacy = WebGatewayInfo {
            state: "unavailable".into(),
            reason: "legacy_runtime".into(),
            ..Default::default()
        };
        let json = serde_json::to_value(&legacy).unwrap();
        assert_eq!(json["reason"], "legacy_runtime");
    }

    #[test]
    fn decode_fail_closed_on_foreign_schema() {
        assert!(decode_runtime_services(b"{\"schema_version\":\"aisc.runtime-services/v2\"}")
            .is_err());
        assert!(decode_runtime_services(b"{}").is_err());
        assert!(decode_runtime_services(b"not json").is_err());
    }
}
