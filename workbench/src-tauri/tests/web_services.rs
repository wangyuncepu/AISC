//! svc-0 (container web-service access): Rust consumer of the shared
//! fixtures under `tests/fixtures/web-services/`.
//!
//! Python (tests/test_web_services.py) and TS
//! (workbench/src/lib/__tests__/webServices.test.ts) parse the same files —
//! the svc-0 stage gate is all three decoding identically.

use std::fs;
use std::path::PathBuf;

use workbench_lib::web_services::{
    build_service_url, decode_runtime_services, WEB_GATEWAY_CONTAINER_PORT, WEB_SERVICE_SCHEMA_V1,
};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/web-services")
        .join(name)
}

#[test]
fn runtime_services_fixture_decodes() {
    let raw = fs::read(fixture("runtime-services.sample.json")).expect("fixture must exist");
    let result = decode_runtime_services(&raw).expect("fixture decodes");
    assert_eq!(result.schema_version, "aisc.runtime-services/v1");
    assert_eq!(result.runtime_id, "0e7b7e3b-0000-4000-8000-000000000001");
    assert_eq!(result.gateway.state, "ready");
    assert_eq!(result.gateway.container_port, WEB_GATEWAY_CONTAINER_PORT);
    assert_eq!(result.gateway.host_port, 47831);
    assert_eq!(result.gateway.host, "127.0.0.1");
    assert_eq!(
        result.services.iter().map(|s| s.port).collect::<Vec<_>>(),
        vec![3000, 5173]
    );
    assert_eq!(result.services[1].name, "");
    assert_eq!(result.observed_at, "2026-08-25T00:00:00Z");
}

#[test]
fn fixture_urls_match_url_builder() {
    let raw = fs::read(fixture("runtime-services.sample.json")).unwrap();
    let result = decode_runtime_services(&raw).unwrap();
    for svc in &result.services {
        assert_eq!(svc.url, build_service_url(svc.port, result.gateway.host_port));
    }
}

#[test]
fn web_service_record_fixture_shape() {
    let raw: serde_json::Value =
        serde_json::from_slice(&fs::read(fixture("web-service-record.sample.json")).unwrap())
            .unwrap();
    assert_eq!(raw["schema_version"], WEB_SERVICE_SCHEMA_V1);
    assert_eq!(raw["port"], 3000);
    assert_eq!(raw["state"], "registered");
    assert_eq!(raw["pid"], serde_json::Value::Null);
}

#[test]
fn fixture_round_trips_through_the_structs() {
    let raw = fs::read(fixture("runtime-services.sample.json")).unwrap();
    let result = decode_runtime_services(&raw).unwrap();
    let re = serde_json::to_value(&result).unwrap();
    let original: serde_json::Value = serde_json::from_slice(&raw).unwrap();
    // Field-by-field: our serialize order/shape must re-parse to the same
    // semantic payload (reason is conditional, absent here).
    assert_eq!(re["schema_version"], original["schema_version"]);
    assert_eq!(re["gateway"], original["gateway"]);
    assert_eq!(re["services"], original["services"]);
    assert_eq!(re["observed_at"], original["observed_at"]);
}
