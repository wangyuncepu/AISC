//! Stage 0 (S0.2): consume the shared `aisc.cli/v1` fixtures from Rust.
//!
//! B-A03: Python/Rust/TS all parse the same files under
//! `tests/fixtures/cli/`. These tests exercise `Envelope` deserialization,
//! `parse_and_validate` (protocol + exit-code checks), `BuildEvent` JSONL
//! parsing, unknown-field preservation, and the stable error-code manifest.

use std::fs;
use std::path::PathBuf;

use workbench_lib::cli::{parse_and_validate, BuildEvent, Envelope};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/cli")
        .join(name)
}

fn read_fixture(name: &str) -> Vec<u8> {
    fs::read(fixture(name)).expect("fixture must exist")
}

#[test]
fn version_envelope_parses_and_validates() {
    let env = parse_and_validate(&read_fixture("envelope-version.json"), Some(0))
        .expect("valid version envelope");
    assert_eq!(env.meta.command, "version");
    assert_eq!(env.meta.protocol, "aisc.cli/v1");
    assert_eq!(env.meta.exit_code, 0);
    assert!(env.errors.is_empty());

    let caps = env.data.as_ref().unwrap().get("capabilities").unwrap();
    assert_eq!(caps["runtime"], "aisc.runtime/v1");
    assert_eq!(caps["session"], "aisc.session/v1");
    assert_eq!(caps["providerStatus"], "aisc.provider-status/v1");
    assert_eq!(caps["buildEvents"], "aisc.build-events/v2");
}

#[test]
fn unsupported_protocol_is_rejected() {
    let err = parse_and_validate(&read_fixture("envelope-unsupported-protocol.json"), Some(0))
        .expect_err("unsupported protocol must fail closed");
    assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
}

#[test]
fn exit_code_mismatch_is_rejected() {
    // Valid envelope but the expected process exit code differs.
    let err = parse_and_validate(&read_fixture("envelope-version.json"), Some(2))
        .expect_err("exit-code mismatch must be a protocol error");
    assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
}

#[test]
fn error_envelopes_carry_stable_codes() {
    let invalid = parse_and_validate(
        &read_fixture("envelope-error-invalid-runtime-id.json"),
        Some(15),
    )
    .expect("invalid-runtime-id envelope");
    assert_eq!(invalid.errors[0].code, "AISC_ERR_INVALID_RUNTIME_ID");
    assert_eq!(invalid.meta.exit_code, 15);

    let usage = parse_and_validate(&read_fixture("envelope-error-usage.json"), Some(2))
        .expect("usage envelope");
    assert_eq!(usage.errors[0].code, "AISC_ERR_USAGE");
    assert_eq!(usage.meta.exit_code, 2);
}

#[test]
fn unknown_fields_are_preserved() {
    let raw = read_fixture("envelope-unknown-field.json");
    // Envelope struct itself ignores unknown fields but must still parse.
    let env: Envelope = serde_json::from_slice(&raw).expect("unknown-field envelope parses");
    assert_eq!(env.meta.command, "version");

    // Value-level parse proves the unknown fields survive an untouched round-trip.
    let value: serde_json::Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(value["x_future_top_level"]["kept"], true);
    assert!(value.get("x_data_future_note").is_some());
}

#[test]
fn build_events_jsonl_parses_sequentially() {
    let content = fs::read_to_string(fixture("events-build.jsonl")).unwrap();
    let events: Vec<BuildEvent> = content
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str::<BuildEvent>(l).expect("each line is a BuildEvent"))
        .collect();

    assert_eq!(events.len(), 5);
    for (i, ev) in events.iter().enumerate() {
        assert_eq!(ev.seq, i as u64 + 1, "seq must be monotonic from 1");
        assert_eq!(ev.protocol, "aisc.cli/v1");
        assert_eq!(ev.run_id, "00000000-0000-4000-8000-000000000006");
    }
    assert_eq!(events[0].event_type, "build.start");
    assert!(events[2..4].iter().all(|e| e.event_type == "build.output"));
    assert_eq!(events[4].event_type, "build.complete");
    assert_eq!(events[4].data["exit_code"], 0);
}

#[test]
fn error_codes_manifest_has_required_codes() {
    let value: serde_json::Value =
        serde_json::from_slice(&read_fixture("error-codes.json")).unwrap();
    for code in [
        "AISC_ERR_USAGE",
        "AISC_ERR_INVALID_RUNTIME_ID",
        "AISC_ERR_CLI_NOT_FOUND",
        "AISC_ERR_DOCKER_UNAVAILABLE",
        "AISC_ERR_IMAGE_MISSING",
        "AISC_ERR_BUILD_FAILED",
    ] {
        assert!(value.get(code).is_some(), "missing stable error code {code}");
        assert!(value[code].get("exit_code").is_some(), "{code} exit_code");
        assert!(value[code].get("action").is_some(), "{code} action");
    }
}
