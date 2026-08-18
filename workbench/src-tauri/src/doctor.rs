//! One-click diagnostics (G-13, Step 12): `aisc doctor --format json`.
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §六 (Doctor contract) - `data.host.checks` /
//!   `data.host.summary`, `data.container` currently null / future structure,
//!   `hint` is per-check not report-level, unknown fields ignored.
//! - 02-startup-flow.md §五 (F-4) - error/blocked view diagnostic button, same
//!   entry point from ready details, no auto-repair.
//! - 01-risk-analysis.md R-10 - timeout / protocol error / secret leak.
//!
//! A doctor run whose checks FAIL still yields a valid envelope: the CLI emits
//! BOTH `data.host` (with per-check status/message/hint) and an `errors[]`
//! entry for the mapped AISC_ERR_*. As long as `data.host` parses we return the
//! report so the UI shows exactly which check failed and why; only transport /
//! protocol failures (timeout, invalid JSON, stdout overflow, missing host)
//! become a `WorkbenchError` - the original error page facts are preserved
//! (A-G13-1). Each check's `detail`/`hint` is passed through `redact()` before
//! it reaches the UI (A-G13-4).

use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::AppHandle;
use tokio_util::sync::CancellationToken;

use crate::cli::{run_control, Envelope};
use crate::error::{redact, WorkbenchError};
use crate::session::resolve_cli;

const DOCTOR_TIMEOUT: Duration = Duration::from_secs(30);

/// Pure argv builder for `aisc doctor --format json` (05 §六).
pub fn doctor_argv() -> Vec<String> {
    vec!["doctor".into(), "--format".into(), "json".into()]
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DoctorCheck {
    pub name: String,
    pub status: String, // pass | warn | fail | skip
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DoctorSummary {
    pub passed: u64,
    pub warnings: u64,
    pub failures: u64,
    pub skipped: u64,
}

/// `data.host` from the doctor envelope (05 §六). `data.container` is ignored:
/// it is null today and may become a future structure without breaking host
/// parsing (A-G13-4). Unknown fields at any level are skipped by serde.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DoctorHost {
    pub checks: Vec<DoctorCheck>,
    pub summary: DoctorSummary,
}

#[derive(Debug, Clone, Serialize)]
pub struct DoctorReport {
    pub checks: Vec<DoctorCheck>,
    pub summary: DoctorSummary,
}

fn redact_opt(s: Option<String>) -> Option<String> {
    s.map(|v| redact(&v))
}

/// Convert a validated `aisc.cli/v1` envelope into a `DoctorReport`.
///
/// Pure + unit-testable. Assumes transport validation (protocol, exit-code
/// consistency, stdout cap) already ran in `run_control`. Checks:
/// - envelope `errors[]` + unusable `data.host` -> mapped AISC error;
/// - `meta.command != doctor` -> protocol error;
/// - missing / malformed `data.host` -> protocol error.
pub fn doctor_report_from_envelope(env: Envelope) -> Result<DoctorReport, WorkbenchError> {
    if env.meta.command != "doctor" {
        return Err(WorkbenchError::cli_protocol()
            .with_detail(format!("unexpected command: {}", env.meta.command)));
    }
    let data = env.data.unwrap_or(Value::Null);
    let host = data.get("host").cloned().unwrap_or(Value::Null);
    match serde_json::from_value::<DoctorHost>(host) {
        Ok(host) => {
            let checks = host
                .checks
                .into_iter()
                .map(|mut c| {
                    c.detail = redact_opt(c.detail);
                    c.hint = redact_opt(c.hint);
                    c
                })
                .collect();
            Ok(DoctorReport {
                checks,
                summary: host.summary,
            })
        }
        Err(e) => {
            // Unusable host: fall back to the envelope error when present (the
            // CLI error code is the stable mapping, A-G13-2), else protocol.
            if let Some(err) = env.errors.first() {
                return Err(WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()));
            }
            Err(WorkbenchError::cli_protocol().with_detail(format!("doctor host parse: {e}")))
        }
    }
}

#[tauri::command]
pub async fn run_doctor(app: AppHandle) -> Result<DoctorReport, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let env = run_control(&pin, doctor_argv(), DOCTOR_TIMEOUT, CancellationToken::new()).await?;
    doctor_report_from_envelope(env)
}

// --- Stage 6 (REL-01): redacted diagnostic bundle (D6-05/06) ---

/// The allowlisted diagnostic bundle. ONLY: app version / platform /
/// redacted settings / env readiness / stable doctor report / recent op
/// timings. Never prompts, PTY content, full env, or secrets (D6-06: the
/// frontend shows the manifest before writing).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticBundle {
    pub generated_at_ms: u128,
    pub app_version: String,
    pub platform: String,
    pub settings: serde_json::Value,
    pub env_readiness: crate::env::EnvReadiness,
    pub doctor: Option<DoctorReport>,
    pub recent_operations: Vec<crate::trace::OpTrace>,
    /// Stage 7 (DATA-04): the canonical data root facts (root path,
    /// origin, writability) so diagnostics and the CLI doctor agree.
    pub data_root: serde_json::Value,
    /// Set when the bundle was written to disk.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

/// Redacted data-root section for the diagnostic bundle (path + origin +
/// writability only; never a workspace path or hash unless explicitly
/// exported).
fn data_root_section() -> serde_json::Value {
    let root = crate::data_root::default_data_root();
    serde_json::json!({
        "root": root.to_string_lossy(),
        "origin": if std::env::var("AISC_DATA_ROOT").map(|v| !v.is_empty()).unwrap_or(false) {
            "env"
        } else {
            "default"
        },
    })
}

fn rfc3339_now() -> String {
    // No chrono dependency; a readable local-time approximation via SystemTime.
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis().to_string())
        .unwrap_or_else(|_| "0".into())
}

#[tauri::command]
pub async fn diagnostic_bundle(
    app: AppHandle,
    write_path: Option<String>,
) -> Result<DiagnosticBundle, WorkbenchError> {
    let env = crate::env::compute_readiness(app.clone()).await;
    let doctor = run_doctor(app.clone()).await.ok();
    let settings = crate::settings::load_settings(app.clone())
        .await
        .ok()
        .and_then(|doc| serde_json::to_value(&doc).ok())
        .unwrap_or(serde_json::Value::Null);
    let mut bundle = DiagnosticBundle {
        generated_at_ms: rfc3339_now().parse().unwrap_or(0),
        app_version: app.package_info().version.to_string(),
        platform: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
        settings,
        env_readiness: env,
        doctor,
        recent_operations: crate::trace::snapshot(),
        data_root: data_root_section(),
        path: None,
    };
    if let Some(p) = write_path {
        let bytes = serde_json::to_vec_pretty(&bundle)
            .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("bundle encode: {e}")))?;
        std::fs::write(&p, bytes)
            .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("bundle write: {e}")))?;
        bundle.path = Some(p);
    }
    Ok(bundle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn host(checks: Value, summary: Value) -> Value {
        json!({ "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 0},
                "data": {"host": {"checks": checks, "summary": summary}, "container": null},
                "errors": [] })
    }

    fn env(v: Value) -> Envelope {
        serde_json::from_value(v).expect("valid envelope")
    }

    #[test]
    fn doctor_argv_is_fixed() {
        assert_eq!(doctor_argv(), vec!["doctor", "--format", "json"]);
    }

    #[test]
    fn parses_host_checks_and_summary() {
        let checks = json!([
            {"name": "docker-cli", "status": "pass", "message": "found", "detail": "/usr/bin/docker"},
            {"name": "aisc-root", "status": "fail", "message": "bad", "hint": "run install"}
        ]);
        let summary = json!({"passed": 1, "warnings": 0, "failures": 1, "skipped": 0});
        let report = doctor_report_from_envelope(env(host(checks, summary))).expect("ok");
        assert_eq!(report.checks.len(), 2);
        assert_eq!(report.checks[0].status, "pass");
        assert_eq!(report.checks[1].hint.as_deref(), Some("run install"));
        assert_eq!(report.summary.failures, 1);
        assert_eq!(report.summary.passed, 1);
    }

    #[test]
    fn ignores_unknown_check_fields_and_container_future_shape() {
        // A-G13-4: unknown check fields ignored; `data.container` present as a
        // future structure does not break host parsing.
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 0},
            "data": {
                "host": {
                    "checks": [{"name": "docker-daemon", "status": "warn", "message": "slow",
                                "future_field": "x"}],
                    "summary": {"passed": 0, "warnings": 1, "failures": 0, "skipped": 0},
                    "extra_host_key": true
                },
                "container": {"future": {"nested": [1, 2, 3]}}
            },
            "errors": []
        });
        let report = doctor_report_from_envelope(env(v)).expect("ok");
        assert_eq!(report.checks.len(), 1);
        assert_eq!(report.checks[0].name, "docker-daemon");
        assert_eq!(report.summary.warnings, 1);
    }

    #[test]
    fn container_null_is_omitted() {
        let report = doctor_report_from_envelope(env(host(
            json!([]),
            json!({"passed": 0, "warnings": 0, "failures": 0, "skipped": 0}),
        )))
        .expect("ok");
        assert!(report.checks.is_empty());
    }

    #[test]
    fn redacts_check_detail_and_hint() {
        let checks = json!([
            {"name": "auth", "status": "warn", "message": "m",
             "detail": "ANTHROPIC_API_KEY=sk-ant-abc123def456"}
        ]);
        let summary = json!({"passed": 0, "warnings": 1, "failures": 0, "skipped": 0});
        let report = doctor_report_from_envelope(env(host(checks, summary))).expect("ok");
        let d = report.checks[0].detail.as_deref().unwrap();
        assert!(d.contains("ANTHROPIC_API_KEY=<redacted>"));
        assert!(!d.contains("sk-ant-abc123def456"));
    }

    #[test]
    fn wrong_command_is_protocol_error() {
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 0},
            "data": {"host": {"checks": [], "summary": {"passed": 0, "warnings": 0, "failures": 0, "skipped": 0}}},
            "errors": []
        });
        let err = doctor_report_from_envelope(env(v)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn missing_host_maps_to_mapped_error_when_present() {
        // CLI error with no usable host -> stable AISC mapping (A-G13-2).
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 3},
            "data": {"container": null},
            "errors": [{"code": "AISC_ERR_DOCKER_UNAVAILABLE", "message": "docker down"}]
        });
        let err = doctor_report_from_envelope(env(v)).unwrap_err();
        assert_eq!(err.code, "AISC_ERR_DOCKER_UNAVAILABLE");
        assert_eq!(err.action, crate::error::Action::StartDocker);
    }

    #[test]
    fn missing_host_without_errors_is_protocol_error() {
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 0},
            "data": {"container": null},
            "errors": []
        });
        let err = doctor_report_from_envelope(env(v)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn malformed_host_is_protocol_error() {
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 0},
            "data": {"host": {"checks": "not-a-list", "summary": {}}},
            "errors": []
        });
        let err = doctor_report_from_envelope(env(v)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn failures_in_checks_still_yield_report() {
        // Non-zero-exit doctor that still produced data.host keeps the report
        // (the failed checks carry the diagnosis), preserving the original
        // error facts (A-G13-1).
        let checks = json!([
            {"name": "docker-cli", "status": "fail", "message": "not found",
             "hint": "Install Docker: https://docs.docker.com/get-docker/"}
        ]);
        let summary = json!({"passed": 0, "warnings": 0, "failures": 1, "skipped": 0});
        let v = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "doctor", "exit_code": 3},
            "data": {"host": {"checks": checks, "summary": summary}, "container": null},
            "errors": [{"code": "AISC_ERR_DOCKER_UNAVAILABLE", "message": "Docker CLI not found"}]
        });
        let report = doctor_report_from_envelope(env(v)).expect("report");
        assert_eq!(report.summary.failures, 1);
        assert_eq!(report.checks[0].status, "fail");
        assert!(report.checks[0].hint.as_deref().unwrap().contains("docs.docker.com"));
    }
}
