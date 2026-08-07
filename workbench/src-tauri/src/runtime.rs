//! Runtime control: thin `run_control` wrappers over `aisc runtime
//! preflight/inspect/start/stop/restart/list/remove` + `build --events`.
//!
//! S2.2.b: snapshot aligned to the CLI `RuntimeSnapshot.to_dict()` (the S2.1.a
//! struct had a `ready` field the CLI never emits on inspect/list, so inspect
//! parsing silently failed); `list_runtimes` + `remove_runtime` added; all
//! lifecycle commands thread `--workspace` so the per-workspace registry is
//! located and `config` is populated.
//!
//! Spec refs: 05-cli-gui-contract.md §5.1 (preflight), §5.2 (start), §5.3
//! (list), §5.4 (inspect), §5.5 (stop/restart/remove), §4.1 (build events);
//! 03-lifecycle-contract.md §四 (runtime state machine), §十 (domain API).

use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{ipc::Channel, AppHandle, Manager};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::cli::{run_build_stream, run_control, BuildEvent};
use crate::error::WorkbenchError;
use crate::session::resolve_pin;

const START_TIMEOUT: Duration = Duration::from_secs(120);
const STOP_TIMEOUT: Duration = Duration::from_secs(30);
const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(120);
const RESTART_TIMEOUT: Duration = Duration::from_secs(120);
const REMOVE_TIMEOUT: Duration = Duration::from_secs(60);
const LIST_TIMEOUT: Duration = Duration::from_secs(30);
const BUILD_TIMEOUT: Duration = Duration::from_secs(600);

/// Cancellation token for the in-flight `start_runtime` operation (02 §三:
/// every async operation has a cancellation token). One at a time - S2.1.a is
/// single-session. Newtype wrapper so it is a distinct managed state from
/// `BuildOp` (Tauri keys state by concrete type).
#[derive(Default, Clone)]
pub struct StartOp(pub Arc<Mutex<Option<CancellationToken>>>);

/// Cancellation token for the in-flight `build_image` operation.
#[derive(Default, Clone)]
pub struct BuildOp(pub Arc<Mutex<Option<CancellationToken>>>);

/// Subset of the `aisc runtime start` envelope `data` (extra fields ignored).
/// The start payload is a distinct shape from `RuntimeSnapshot`: it carries
/// `ready`/`reused` (§5.2).
#[derive(Debug, Deserialize, Serialize)]
pub struct RuntimeStartResult {
    pub runtime_id: String,
    pub container_name: String,
    pub state: String,
    pub ready: bool,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct PreflightCheck {
    pub id: String,
    pub status: String, // pass | warn | fail
    pub error_code: Option<String>,
    pub detail: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct PreflightReport {
    #[serde(default)]
    pub spec: Value,
    pub checks: Vec<PreflightCheck>,
    pub can_start: bool,
    pub recommended_action: String, // start | reuse | restart | resolve_conflict
    #[serde(default)]
    pub matching_runtime_id: Option<String>,
    #[serde(default)]
    pub conflicts: Value,
    pub observed_at: String,
}

/// `aisc runtime` config value object (03 §三 RuntimeSpec).
#[derive(Debug, Default, Clone, Deserialize, Serialize)]
pub struct RuntimeConfig {
    #[serde(default)]
    pub workspace: String,
    #[serde(default)]
    pub image: String,
    #[serde(default)]
    pub network: String,
    #[serde(default)]
    pub scope: String,
}

/// `aisc runtime inspect/list/stop/restart/remove` snapshot (§5.3-5.5). Mirrors
/// the CLI `RuntimeSnapshot.to_dict()` exactly: there is no `ready` field (that
/// is only on the start payload `RuntimeStartResult`). `state` is unknown |
/// not_found | starting | running | stopping | stopped | removing (03 §四.1).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RuntimeSnapshot {
    pub runtime_id: String,
    pub state: String,
    pub config: RuntimeConfig,
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub config_fingerprint: String,
    #[serde(default)]
    pub container_name: String,
    #[serde(default)]
    pub container_id: String,
    #[serde(default)]
    pub registry_state: String,
    #[serde(default)]
    pub observed_at: String,
    #[serde(default)]
    pub stale: bool,
}

/// `aisc runtime list` envelope `data` (§5.3): `{runtimes, observed_at}`.
#[derive(Debug, Deserialize, Serialize)]
pub struct RuntimeListResult {
    pub runtimes: Vec<RuntimeSnapshot>,
    #[serde(default)]
    pub observed_at: String,
}

fn envelope_error(env: &crate::cli::Envelope) -> Option<WorkbenchError> {
    env.errors.first().map(|err| WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()))
}

// --- argv builders (pure, unit-testable; cf. session.rs) ---

fn runtime_inspect_argv(runtime_id: &str, workspace: &str) -> Vec<String> {
    vec![
        "runtime".into(),
        "inspect".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn runtime_stop_argv(runtime_id: &str, workspace: &str) -> Vec<String> {
    vec![
        "runtime".into(),
        "stop".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn runtime_restart_argv(runtime_id: &str, workspace: &str) -> Vec<String> {
    vec![
        "runtime".into(),
        "restart".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn runtime_remove_argv(runtime_id: &str, workspace: &str, force: bool) -> Vec<String> {
    let mut argv = vec![
        "runtime".into(),
        "remove".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ];
    if force {
        argv.push("--force".into());
    }
    argv
}

fn runtime_list_argv(workspace: &str, owner: Option<&str>) -> Vec<String> {
    let mut argv = vec![
        "runtime".into(),
        "list".into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ];
    if let Some(o) = owner {
        argv.push("--owner".into());
        argv.push(o.into());
    }
    argv
}

#[tauri::command]
pub async fn runtime_preflight(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
    image: Option<String>,
    network: Option<String>,
    scope: Option<String>,
) -> Result<PreflightReport, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let mut argv = vec![
        "runtime".into(),
        "preflight".into(),
        "--runtime-id".into(),
        runtime_id,
        "--workspace".into(),
        workspace,
        "--format".into(),
        "json".into(),
    ];
    if let Some(v) = image {
        argv.push("--image".into());
        argv.push(v);
    }
    if let Some(v) = network {
        argv.push("--network".into());
        argv.push(v);
    }
    if let Some(v) = scope {
        argv.push("--scope".into());
        argv.push(v);
    }
    let env = run_control(&pin, argv, PREFLIGHT_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<PreflightReport>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("preflight parse: {e}")))
}

#[tauri::command]
pub async fn runtime_inspect(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = runtime_inspect_argv(&runtime_id, &workspace);
    let env = run_control(&pin, argv, STOP_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeSnapshot>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("inspect parse: {e}")))
}

#[tauri::command]
pub async fn start_runtime(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    image: Option<String>,
    network: Option<String>,
    scope: Option<String>,
) -> Result<RuntimeStartResult, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let start_op = app.state::<StartOp>().inner().clone();
    let cancel = CancellationToken::new();
    if let Ok(mut g) = start_op.0.lock() {
        *g = Some(cancel.clone());
    }
    let image = image.unwrap_or_else(|| "super-claude:latest".to_string());
    let network = network.unwrap_or_else(|| "direct".to_string());
    let scope = scope.unwrap_or_else(|| "project".to_string());
    let argv = vec![
        "runtime".into(),
        "start".into(),
        "--runtime-id".into(),
        runtime_id,
        "--workspace".into(),
        workspace,
        "--image".into(),
        image,
        "--network".into(),
        network,
        "--scope".into(),
        scope,
        "--owner".into(),
        "workbench".into(),
        "--format".into(),
        "json".into(),
    ];
    let env = run_control(&pin, argv, START_TIMEOUT, cancel).await;
    // Clear the in-flight token regardless of outcome.
    if let Ok(mut g) = start_op.0.lock() {
        *g = None;
    }
    let env = env?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeStartResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("runtime start parse: {e}")))
}

#[tauri::command]
pub async fn cancel_runtime_start(app: AppHandle) -> Result<(), WorkbenchError> {
    let start_op = app.state::<StartOp>().inner().clone();
    if let Ok(g) = start_op.0.lock() {
        if let Some(t) = g.as_ref() {
            t.cancel();
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn runtime_restart(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = runtime_restart_argv(&runtime_id, &workspace);
    let env = run_control(&pin, argv, RESTART_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeSnapshot>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("restart parse: {e}")))
}

#[tauri::command]
pub async fn stop_runtime(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = runtime_stop_argv(&runtime_id, &workspace);
    let env = run_control(&pin, argv, STOP_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeSnapshot>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("stop parse: {e}")))
}

#[tauri::command]
pub async fn list_runtimes(
    app: AppHandle,
    workspace: String,
    owner: Option<String>,
) -> Result<RuntimeListResult, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = runtime_list_argv(&workspace, owner.as_deref());
    let env = run_control(&pin, argv, LIST_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeListResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("list parse: {e}")))
}

#[tauri::command]
pub async fn remove_runtime(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
    force: bool,
) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = runtime_remove_argv(&runtime_id, &workspace, force);
    let env = run_control(&pin, argv, REMOVE_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeSnapshot>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("remove parse: {e}")))
}

/// Build an image via `aisc build --events`, streaming JSONL events to the
/// frontend Channel (05 §4.1). Cancellable via `cancel_build`.
#[tauri::command]
pub async fn build_image(
    app: AppHandle,
    tag: String,
    on_event: Channel<BuildEvent>,
) -> Result<(), WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let build_op = app.state::<BuildOp>().inner().clone();
    let cancel = CancellationToken::new();
    if let Ok(mut g) = build_op.0.lock() {
        *g = Some(cancel.clone());
    }

    let (tx, mut rx) = mpsc::channel::<BuildEvent>(256);
    // Bridge mpsc -> Tauri Channel.
    tokio::spawn(async move {
        while let Some(ev) = rx.recv().await {
            if on_event.send(ev).is_err() {
                break;
            }
        }
    });

    let argv = vec!["build".into(), "--tag".into(), tag, "--events".into()];
    let result = run_build_stream(&pin, argv, BUILD_TIMEOUT, cancel, tx).await;

    if let Ok(mut g) = build_op.0.lock() {
        *g = None;
    }
    result
}

#[tauri::command]
pub async fn cancel_build(app: AppHandle) -> Result<(), WorkbenchError> {
    let build_op = app.state::<BuildOp>().inner().clone();
    if let Ok(g) = build_op.0.lock() {
        if let Some(t) = g.as_ref() {
            t.cancel();
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inspect_argv_threads_workspace() {
        let argv = runtime_inspect_argv("rid", "/ws");
        assert_eq!(argv[0], "runtime");
        assert_eq!(argv[1], "inspect");
        assert!(argv.contains(&"--runtime-id".into()));
        assert!(argv.contains(&"rid".into()));
        assert!(argv.contains(&"--workspace".into()));
        assert!(argv.contains(&"/ws".into()));
        assert!(argv.contains(&"--format".into()));
        assert!(argv.contains(&"json".into()));
    }

    #[test]
    fn stop_argv_threads_workspace() {
        let argv = runtime_stop_argv("rid", "/ws");
        assert_eq!(argv[1], "stop");
        assert!(argv.contains(&"--workspace".into()));
        assert!(argv.contains(&"/ws".into()));
    }

    #[test]
    fn restart_argv_threads_workspace() {
        let argv = runtime_restart_argv("rid", "/ws");
        assert_eq!(argv[1], "restart");
        assert!(argv.contains(&"--workspace".into()));
    }

    #[test]
    fn remove_argv_force_toggle() {
        let without = runtime_remove_argv("rid", "/ws", false);
        assert_eq!(without[1], "remove");
        assert!(!without.contains(&"--force".into()));
        assert!(without.contains(&"--workspace".into()));

        let with_force = runtime_remove_argv("rid", "/ws", true);
        assert!(with_force.contains(&"--force".into()));
    }

    #[test]
    fn list_argv_owner_optional() {
        let no_owner = runtime_list_argv("/ws", None);
        assert_eq!(no_owner[1], "list");
        assert!(no_owner.contains(&"--workspace".into()));
        assert!(!no_owner.contains(&"--owner".into()));

        let with_owner = runtime_list_argv("/ws", Some("workbench"));
        assert!(with_owner.contains(&"--owner".into()));
        assert!(with_owner.contains(&"workbench".into()));
    }

    #[test]
    fn snapshot_parses_cli_dict_without_ready() {
        // Exact shape emitted by RuntimeSnapshot.to_dict() (no `ready` field).
        let json = r#"{
            "runtime_id": "rid",
            "state": "running",
            "config": {"workspace": "/ws", "image": "super-claude:latest", "network": "direct", "scope": "project"},
            "owner": "workbench",
            "config_fingerprint": "sha256:abc",
            "container_name": "aisc-rid",
            "container_id": "abc123",
            "registry_state": "registered",
            "observed_at": "2026-08-07T00:00:00Z",
            "stale": false
        }"#;
        let snap: RuntimeSnapshot = serde_json::from_str(json).unwrap();
        assert_eq!(snap.runtime_id, "rid");
        assert_eq!(snap.state, "running");
        assert_eq!(snap.config.workspace, "/ws");
        assert_eq!(snap.config.image, "super-claude:latest");
        assert_eq!(snap.owner, "workbench");
        assert_eq!(snap.registry_state, "registered");
        assert!(!snap.stale);
    }

    #[test]
    fn snapshot_parses_minimal_docker_only() {
        // Docker-only (registry missing) snapshot: many fields empty/absent.
        let json = r#"{
            "runtime_id": "rid",
            "state": "stopped",
            "config": {},
            "container_name": "aisc-rid",
            "registry_state": "missing",
            "observed_at": "2026-08-07T00:00:00Z",
            "stale": false
        }"#;
        let snap: RuntimeSnapshot = serde_json::from_str(json).unwrap();
        assert_eq!(snap.state, "stopped");
        assert_eq!(snap.registry_state, "missing");
        assert_eq!(snap.config.workspace, "");
        assert_eq!(snap.owner, "");
    }

    #[test]
    fn list_result_parses() {
        let json = r#"{
            "runtimes": [
                {"runtime_id": "a", "state": "running", "config": {}, "observed_at": "t1", "stale": false},
                {"runtime_id": "b", "state": "stopped", "config": {}, "observed_at": "t1", "stale": false}
            ],
            "observed_at": "t1"
        }"#;
        let res: RuntimeListResult = serde_json::from_str(json).unwrap();
        assert_eq!(res.runtimes.len(), 2);
        assert_eq!(res.runtimes[0].state, "running");
        assert_eq!(res.runtimes[1].state, "stopped");
        assert_eq!(res.observed_at, "t1");
    }
}
