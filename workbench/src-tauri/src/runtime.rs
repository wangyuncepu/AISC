//! Minimal runtime control for the S1.4/S2.1.a slices: thin `run_control`
//! wrappers over `aisc runtime preflight/inspect/start/restart/stop`. No state
//! machine, reconciliation, list/remove - those land in S2.2.
//!
//! Spec refs: 05-cli-gui-contract.md §5.1 (preflight), §5.4 (inspect),
//! §5.2 (start), §5.5 (stop/restart); 02-startup-flow.md §八 (cancellable start).

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

/// Subset of `aisc runtime inspect` snapshot (§5.4). `state` is
/// not_found | stopped | running | unknown.
#[derive(Debug, Deserialize, Serialize)]
pub struct RuntimeSnapshot {
    pub runtime_id: String,
    pub container_name: String,
    pub state: String,
    pub ready: bool,
}

fn envelope_error(env: &crate::cli::Envelope) -> Option<WorkbenchError> {
    env.errors.first().map(|err| WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()))
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
pub async fn runtime_inspect(app: AppHandle, runtime_id: String) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = vec![
        "runtime".into(),
        "inspect".into(),
        "--runtime-id".into(),
        runtime_id,
        "--format".into(),
        "json".into(),
    ];
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
pub async fn runtime_restart(app: AppHandle, runtime_id: String) -> Result<(), WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = vec![
        "runtime".into(),
        "restart".into(),
        "--runtime-id".into(),
        runtime_id,
        "--format".into(),
        "json".into(),
    ];
    let env = run_control(&pin, argv, RESTART_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    Ok(())
}

#[tauri::command]
pub async fn stop_runtime(app: AppHandle, runtime_id: String) -> Result<(), WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = vec![
        "runtime".into(),
        "stop".into(),
        "--runtime-id".into(),
        runtime_id,
        "--format".into(),
        "json".into(),
    ];
    let env = run_control(&pin, argv, STOP_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    Ok(())
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
