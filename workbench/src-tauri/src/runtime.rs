//! Minimal runtime control for the S1.4 end-to-end slice: thin
//! `run_control` wrappers over `aisc runtime start/stop`. No state machine,
//! reconciliation, list/inspect/restart/remove - those land in S2.2.
//!
//! Spec refs: 05-cli-gui-contract.md §5.2 (start argv), §5.5 (stop).

use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
use tokio_util::sync::CancellationToken;

use crate::cli::run_control;
use crate::error::WorkbenchError;
use crate::session::resolve_pin;

const START_TIMEOUT: Duration = Duration::from_secs(120);
const STOP_TIMEOUT: Duration = Duration::from_secs(30);

/// Subset of the `aisc runtime start` envelope `data` (extra fields ignored).
#[derive(Debug, Deserialize, Serialize)]
pub struct RuntimeStartResult {
    pub runtime_id: String,
    pub container_name: String,
    pub state: String,
    pub ready: bool,
}

#[tauri::command]
pub async fn start_runtime(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
) -> Result<RuntimeStartResult, WorkbenchError> {
    let pin = resolve_pin(&app)?;
    let argv = vec![
        "runtime".into(),
        "start".into(),
        "--runtime-id".into(),
        runtime_id,
        "--workspace".into(),
        workspace,
        "--image".into(),
        "super-claude:latest".into(),
        "--network".into(),
        "direct".into(),
        "--scope".into(),
        "project".into(),
        "--owner".into(),
        "workbench".into(),
        "--format".into(),
        "json".into(),
    ];
    let env = run_control(&pin, argv, START_TIMEOUT, CancellationToken::new()).await?;
    if let Some(err) = env.errors.first() {
        return Err(WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()));
    }
    let data = env.data.unwrap_or(serde_json::Value::Null);
    serde_json::from_value::<RuntimeStartResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("runtime start parse: {e}")))
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
    if let Some(err) = env.errors.first() {
        return Err(WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()));
    }
    Ok(())
}
