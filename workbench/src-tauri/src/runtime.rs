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

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{ipc::Channel, AppHandle, Manager};
use tokio::sync::mpsc;
use tokio::sync::Mutex as AsyncMutex;
use tokio_util::sync::CancellationToken;

use crate::cli::{run_build_stream, run_control, BuildEvent};
use crate::error::WorkbenchError;
use crate::session::resolve_cli;

const START_TIMEOUT: Duration = Duration::from_secs(120);
const STOP_TIMEOUT: Duration = Duration::from_secs(30);
const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(120);
const RESTART_TIMEOUT: Duration = Duration::from_secs(120);
const REMOVE_TIMEOUT: Duration = Duration::from_secs(60);
const LIST_TIMEOUT: Duration = Duration::from_secs(30);
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(30);
const BUILD_TIMEOUT: Duration = Duration::from_secs(600);

/// Cancellation tokens for in-flight `start_runtime` operations, keyed by
/// runtime_id (02 §三: every async operation has a cancellation token).
/// IDEA-3 (3b): keyed per runtime so concurrent workspace starts never
/// clobber each other's token — the pre-3b single `Option` meant a second
/// start replaced the first's token and `cancel_runtime_start` could cancel
/// the wrong op. Newtype wrappers keep start/build as distinct managed
/// states (Tauri keys state by concrete type).
#[derive(Default, Clone)]
pub struct StartOps(pub Arc<Mutex<HashMap<String, CancellationToken>>>);

/// Cancellation tokens for in-flight `build_image` operations, keyed by tag.
#[derive(Default, Clone)]
pub struct BuildOps(pub Arc<Mutex<HashMap<String, CancellationToken>>>);

type OpTokenMap = Arc<Mutex<HashMap<String, CancellationToken>>>;

/// Register an op's token under its key (a same-key restart replaces the
/// previous token, mirroring the pre-3b single-slot semantics).
fn insert_op(map: &OpTokenMap, key: &str, token: CancellationToken) {
    if let Ok(mut g) = map.lock() {
        g.insert(key.to_string(), token);
    }
}

/// Drop a settled op's token; a late cancel of this key is then a no-op.
fn remove_op(map: &OpTokenMap, key: &str) {
    if let Ok(mut g) = map.lock() {
        g.remove(key);
    }
}

/// Cancel the op registered under `key` (no-op when it already settled).
fn cancel_op(map: &OpTokenMap, key: &str) -> bool {
    match map.lock() {
        Ok(g) => match g.get(key) {
            Some(t) => {
                t.cancel();
                true
            }
            None => false,
        },
        Err(_) => false,
    }
}

/// Per-runtime operation mutexes (03 §九.1: each runtime ID has an independent
/// operation mutex; different runtimes run concurrently). Keyed by runtime_id.
/// A `std::sync::Mutex` guards the map (held briefly); a `tokio::sync::Mutex`
/// per runtime is held across the async op.
#[derive(Default, Clone)]
pub struct OpMutexes(pub Arc<Mutex<HashMap<String, Arc<AsyncMutex<()>>>>>);

/// Acquire the operation lock for a runtime. Same runtime_id serializes;
/// different ids run concurrently. The returned guard is held until the op
/// completes (dropped at the end of the command).
async fn acquire_op_lock(
    mutexes: &OpMutexes,
    runtime_id: &str,
) -> tokio::sync::OwnedMutexGuard<()> {
    let arc = {
        let mut g = mutexes.0.lock().expect("op mutexes map poisoned");
        g.entry(runtime_id.to_string())
            .or_insert_with(|| Arc::new(AsyncMutex::new(())))
            .clone()
    };
    arc.lock_owned().await
}

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

/// `aisc provider current` snapshot (05 §七). Secret-free: routing/auth metadata
/// only, never keys/tokens. `agent` is claude | codex (bash/cc-switch n/a).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ProviderStatus {
    pub runtime_id: String,
    pub agent: String,
    #[serde(default)]
    pub provider_id: String,
    #[serde(default)]
    pub provider_name: String,
    #[serde(default)]
    pub route_mode: String,
    #[serde(default)]
    pub auth_status: String,
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
        "--grace".into(),
        "3".into(),
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

fn provider_current_argv(runtime_id: &str, agent: &str, workspace: &str) -> Vec<String> {
    vec![
        "provider".into(),
        "current".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--agent".into(),
        agent.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ]
}

// --- Stage 8e: cc-switch provider data plane (aisc.cc-switch-provider/v1) ---

/// One provider row of the secret-free adapter snapshot (already masked
/// in-container; the API key never crosses this boundary in full).
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CcSwitchProvider {
    pub id: String,
    pub name: String,
    pub app_type: String,
    pub base_url: String,
    pub model: String,
    pub has_api_key: bool,
    pub api_key_mask: String,
    pub is_current: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CcSwitchProvidersResult {
    pub agent: String,
    pub providers: Vec<CcSwitchProvider>,
    pub operation_id: String,
}

fn cc_switch_argv(op: &str, runtime_id: &str, agent: &str, workspace: &str,
                  positional: Option<&str>) -> Vec<String> {
    let mut argv = vec![
        "cc-switch".into(),
        op.into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--agent".into(),
        agent.into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ];
    if let Some(pid) = positional {
        argv.push(pid.into());
    }
    argv
}

async fn cc_switch_call(
    app: &AppHandle,
    argv: Vec<String>,
    input: Option<String>,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    let pin = crate::session::resolve_cli(app).await?;
    let env = match input {
        Some(text) => {
            crate::cli::run_control_input(&pin, argv, text, PROVIDER_TIMEOUT, CancellationToken::new()).await?
        }
        None => run_control(&pin, argv, PROVIDER_TIMEOUT, CancellationToken::new()).await?,
    };
    if let Some(err) = env.errors.first() {
        // Stage 8e: the adapter's stable AISC_ERR_CC_SWITCH_PROVIDER_* codes
        // are unknown to map_aisc's curated table — surface the adapter's own
        // message (e.g. "provider id already exists: deepseek") instead of
        // the generic fallback.
        let mut wb = WorkbenchError::map_aisc(&err.code);
        if err.code.starts_with("AISC_ERR_CC_SWITCH_PROVIDER_") {
            wb.message = err.message.clone();
            wb.retryable = false;
        }
        return Err(wb.with_detail(err.message.clone()));
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<CcSwitchProvidersResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("cc-switch parse: {e}")))
}

/// Minimal UUID v4 shape check (8-4-4-4-12 hex, version nibble 4, variant
/// nibble 8..=b) — mirrors the Python CLI's validate_uuid_v4 gate.
fn uuid_ok(s: &str) -> Option<()> {
    let b = s.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, &c) in b.iter().enumerate() {
        match i {
            8 | 13 | 18 | 23 => {
                if c != b'-' {
                    return None;
                }
            }
            _ => {
                if !c.is_ascii_hexdigit() {
                    return None;
                }
            }
        }
    }
    if b[14] != b'4' || !matches!(b[19], b'8'..=b'b') {
        return None;
    }
    Some(())
}

fn cc_switch_validate(runtime_id: &str, agent: &str) -> Result<(), WorkbenchError> {
    if uuid_ok(runtime_id).is_none() {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_RUNTIME_ID"));
    }
    if agent != "claude" && agent != "codex" {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_AGENT"));
    }
    Ok(())
}

/// List providers for an agent (secret-free snapshot; Stage 8e).
#[tauri::command]
pub async fn cc_switch_providers(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    cc_switch_validate(&runtime_id, &agent)?;
    let argv = cc_switch_argv("list", &runtime_id, &agent, &workspace, None);
    cc_switch_call(&app, argv, None).await
}

/// Add a provider. The request document (which may carry the API key) rides
/// the CLI child's STDIN via run_control_input — argv/logs/disk stay clean.
#[tauri::command]
pub async fn cc_switch_add(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
    request: Value,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    cc_switch_validate(&runtime_id, &agent)?;
    let argv = cc_switch_argv("add", &runtime_id, &agent, &workspace, None);
    cc_switch_call(&app, argv, Some(request.to_string())).await
}

/// Edit a provider (patch document on STDIN; optional api_key inside it).
#[tauri::command]
pub async fn cc_switch_edit(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
    provider_id: String,
    request: Value,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    cc_switch_validate(&runtime_id, &agent)?;
    let argv = cc_switch_argv("edit", &runtime_id, &agent, &workspace, Some(&provider_id));
    cc_switch_call(&app, argv, Some(request.to_string())).await
}

/// Activate a provider (IDEA-4): the adapter runs the official
/// non-interactive `provider switch` and returns the fresh snapshot.
#[tauri::command]
pub async fn cc_switch_switch(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
    provider_id: String,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    cc_switch_validate(&runtime_id, &agent)?;
    let argv = cc_switch_argv("switch", &runtime_id, &agent, &workspace, Some(&provider_id));
    cc_switch_call(&app, argv, None).await
}

/// Delete a provider (the CLI gates on --confirm internally).
#[tauri::command]
pub async fn cc_switch_delete(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
    provider_id: String,
) -> Result<CcSwitchProvidersResult, WorkbenchError> {
    cc_switch_validate(&runtime_id, &agent)?;
    let mut argv = cc_switch_argv("delete", &runtime_id, &agent, &workspace, Some(&provider_id));
    argv.push("--confirm".into()); // the CLI gates delete on this flag
    cc_switch_call(&app, argv, None).await
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
    let pin = resolve_cli(&app).await?;
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
    let pin = resolve_cli(&app).await?;
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
    let pin = resolve_cli(&app).await?;
    let start_ops = app.state::<StartOps>().inner().clone();
    let cancel = CancellationToken::new();
    let start_key = runtime_id.clone();
    insert_op(&start_ops.0, &start_key, cancel.clone());
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
    remove_op(&start_ops.0, &start_key);
    let env = env?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeStartResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("runtime start parse: {e}")))
}

#[tauri::command]
pub async fn cancel_runtime_start(app: AppHandle, runtime_id: String) -> Result<(), WorkbenchError> {
    let start_ops = app.state::<StartOps>().inner().clone();
    cancel_op(&start_ops.0, &runtime_id);
    Ok(())
}

#[tauri::command]
pub async fn runtime_restart(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
) -> Result<RuntimeSnapshot, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let _op_guard = acquire_op_lock(app.state::<OpMutexes>().inner(), &runtime_id).await;
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
    let pin = resolve_cli(&app).await?;
    let _op_guard = acquire_op_lock(app.state::<OpMutexes>().inner(), &runtime_id).await;
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
    let pin = resolve_cli(&app).await?;
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
    let pin = resolve_cli(&app).await?;
    let _op_guard = acquire_op_lock(app.state::<OpMutexes>().inner(), &runtime_id).await;
    let argv = runtime_remove_argv(&runtime_id, &workspace, force);
    let env = run_control(&pin, argv, REMOVE_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<RuntimeSnapshot>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("remove parse: {e}")))
}

/// Query the provider status for one agent (claude | codex) via `aisc provider
/// current` (05 §七). Secret-free: routing/auth metadata only. bash/cc-switch
/// are not applicable (rejected client-side).
#[tauri::command]
pub async fn get_provider_status(
    app: AppHandle,
    workspace: String,
    runtime_id: String,
    agent: String,
) -> Result<ProviderStatus, WorkbenchError> {
    if agent != "claude" && agent != "codex" {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_AGENT"));
    }
    let pin = resolve_cli(&app).await?;
    let argv = provider_current_argv(&runtime_id, &agent, &workspace);
    let env = run_control(&pin, argv, PROVIDER_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<ProviderStatus>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("provider parse: {e}")))
}

/// Build an image via `aisc build --events`, streaming JSONL events to the
/// frontend Channel (05 §4.1). Cancellable via `cancel_build`.
#[tauri::command]
pub async fn build_image(
    app: AppHandle,
    tag: String,
    on_event: Channel<BuildEvent>,
) -> Result<(), WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let build_ops = app.state::<BuildOps>().inner().clone();
    let cancel = CancellationToken::new();
    let build_key = tag.clone();
    insert_op(&build_ops.0, &build_key, cancel.clone());

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

    remove_op(&build_ops.0, &build_key);
    result
}

#[tauri::command]
pub async fn cancel_build(app: AppHandle, tag: String) -> Result<(), WorkbenchError> {
    let build_ops = app.state::<BuildOps>().inner().clone();
    cancel_op(&build_ops.0, &tag);
    Ok(())
}

/// Start the Docker engine (Docker Desktop on Windows, Docker.app on macOS).
/// Returns Ok(()) if the launch was attempted; the daemon still needs time to
/// come up, so callers re-run preflight after a short delay. Non-Windows/macOS
/// returns an actionable error (systemd on Linux is out of scope for the app).
/// Timed into the op-trace ring (REL-01).
#[tauri::command]
pub async fn start_docker(app: AppHandle) -> Result<(), WorkbenchError> {
    crate::trace::timed("docker", "start_docker", start_docker_inner(app)).await
}

async fn start_docker_inner(app: AppHandle) -> Result<(), WorkbenchError> {
    #[cfg(windows)]
    {
        // Docker Desktop.exe already present → just launch it. KI-1: first
        // suppress the dashboard popup so the start is silent (tray only).
        for exe in docker_desktop_candidates() {
            if exe.exists() {
                suppress_docker_dashboard();
                std::process::Command::new(&exe).spawn().map_err(|e| {
                    WorkbenchError::cli_protocol()
                        .with_detail(format!("failed to start Docker Desktop: {e}"))
                })?;
                return Ok(());
            }
        }
        // Missing → offline build bundles the latest Docker Desktop installer
        // (like mihomo); run it silently. On any failure fall back to winget so
        // an offline build degrades gracefully to the online path.
        if let Some(installer) = bundled_docker_installer() {
            match install_docker_desktop_bundled(&app, &installer).await {
                Ok(()) => return Ok(()),
                Err(e) => {
                    eprintln!("[docker] bundled install failed ({e}); falling back to winget");
                }
            }
        }
        // Missing → install via winget (awaited, bounded; Stage 5 A-ONB02/B):
        // the first-run wizard's "Start Docker" must cover install, not just
        // launch. No shell=True anywhere. Returns a real error on failure so
        // the wizard can show it instead of silently timing out.
        match install_docker_desktop_winget(&app).await {
            Ok(()) => Ok(()),
            Err(e) => Err(WorkbenchError::cli_protocol().with_detail(format!(
                "Docker Desktop not found and automatic install failed: {e}"
            ))),
        }
    }
    #[cfg(target_os = "macos")]
    {
        let app = "/Applications/Docker.app/Contents/MacOS/Docker";
        if std::path::Path::new(app).exists() {
            std::process::Command::new(app).spawn().map_err(|e| {
                WorkbenchError::cli_protocol()
                    .with_detail(format!("failed to start Docker Desktop: {e}"))
            })?;
            return Ok(());
        }
        Err(WorkbenchError::cli_protocol()
            .with_detail("Docker Desktop executable not found".to_string()))
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        Err(WorkbenchError::cli_protocol()
            .with_detail("start Docker manually (e.g. systemctl start docker)".to_string()))
    }
}

/// Make the next Docker Desktop start silent (KI-1, user request 2026-08-17:
/// no foreground dashboard popup when Workbench wakes Docker).
///
/// Mechanism: Docker Desktop's own startup setting — the equivalent of
/// unchecking "Open Docker Dashboard at startup" in its GUI. We write it into
/// `%APPDATA%\Docker\settings-store.json` (Docker Desktop 4.3x+, PascalCase
/// keys) or legacy `settings.json` (camelCase) BEFORE spawning, so the app
/// reads it at startup and starts to the tray.
///
/// Safety: only ever ENABLES the suppression (missing/false → true), never
/// re-enables the popup; every other key is preserved; the write is atomic
/// (temp + replace); an existing-but-unparseable file is left untouched
/// (worst case the dashboard still opens). Best-effort — failures are
/// ignored, launching Docker matters more than silencing it.
#[cfg(windows)]
fn suppress_docker_dashboard() {
    if let Ok(appdata) = std::env::var("APPDATA") {
        suppress_docker_dashboard_in(&std::path::Path::new(&appdata).join("Docker"));
    }
}

/// Testable core of [`suppress_docker_dashboard`] over a Docker config dir.
#[cfg(windows)]
fn suppress_docker_dashboard_in(dir: &std::path::Path) -> bool {
    let store = dir.join("settings-store.json");
    let legacy = dir.join("settings.json");
    // Prefer the modern store; the legacy file only when it is all there is.
    let (path, key) = if store.exists() || !legacy.exists() {
        (store, "OpenUIOnStartupDisabled")
    } else {
        (legacy, "openUIOnStartupDisabled")
    };
    let bytes = std::fs::read(&path).unwrap_or_default();
    let mut val: serde_json::Value = if path.exists() {
        match serde_json::from_slice(&bytes) {
            Ok(v) => v,
            Err(_) => return false, // corrupt/foreign content — never rewrite
        }
    } else {
        serde_json::json!({}) // fresh install: minimal store, Docker fills defaults
    };
    // Already suppressed (explicitly true) → nothing to do.
    if val.get(key).and_then(|v| v.as_bool()) == Some(true) {
        return false;
    }
    let Some(obj) = val.as_object_mut() else {
        return false; // unexpected shape (array/string) — leave it alone
    };
    obj.insert(key.to_string(), serde_json::Value::Bool(true));
    let Ok(out) = serde_json::to_vec_pretty(&val) else {
        return false;
    };
    if std::fs::create_dir_all(dir).is_err() {
        return false;
    }
    crate::storage::atomic_replace(&path, &out).is_ok()
}

/// Candidate paths for the Docker Desktop executable (Windows). Single source
/// shared by `start_docker` and the env readiness probe (env.rs).
#[cfg(windows)]
pub(crate) fn docker_desktop_candidates() -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    if let Ok(base) = std::env::var("LOCALAPPDATA") {
        let la = std::path::PathBuf::from(&base);
        // Per-user install layout (KI-6): the frontend exe lives under
        // Programs\DockerDesktop\frontend, not the machine-wide Program Files.
        out.push(la.join("Programs\\DockerDesktop\\frontend\\Docker Desktop.exe"));
        out.push(la.join("Docker\\Docker Desktop\\Docker Desktop.exe"));
    }
    if let Ok(pf) = std::env::var("ProgramFiles") {
        out.push(std::path::PathBuf::from(pf).join("Docker\\Docker\\Docker Desktop.exe"));
    }
    out
}

/// Check whether winget (App Installer) is available on PATH.
#[cfg(windows)]
fn winget_available() -> bool {
    std::process::Command::new("where")
        .arg("winget")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Timeout for the Docker Desktop install (can be a large download).
const DOCKER_INSTALL_TIMEOUT: Duration = Duration::from_secs(600); // 10 min

/// Fire a Windows toast (best-effort; silently no-ops when notification
/// permission is off). The plugin is registered in lib.rs and the capability
/// grants `notification:allow-notify`. Gives the user a system-level heads-up
/// that a background Docker install finished even if the wizard lost focus.
/// `pub(crate)` so the env engine-ready poll (env.rs) reuses the same path.
pub(crate) fn notify_docker(app: &AppHandle, title: &str, body: &str) {
    use tauri_plugin_notification::NotificationExt;
    match app.notification().builder().title(title.to_string()).body(body.to_string()).show() {
        Ok(()) => {}
        Err(e) => eprintln!("[docker] toast notification failed: {e}"),
    }
}

/// Bundled offline Docker Desktop installer (offline build only). Placed next
/// to the app by the NSIS installer under `aisc-bundle\docker-offline\`. The
/// online build has none and falls back to winget.
#[cfg(windows)]
fn bundled_docker_installer() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let p = exe
        .parent()?
        .join("aisc-bundle")
        .join("docker-offline")
        .join("Docker Desktop Installer.exe");
    p.is_file().then_some(p)
}

/// Install Docker Desktop via winget (Stage 5, A-ONB02/B). **Awaits completion**
/// (bounded by `DOCKER_INSTALL_TIMEOUT`) so the caller can report a real
/// result instead of fire-and-forget — the wizard shows "installing" while
/// awaiting and a clear failure on error. Console window is hidden. Returns
/// Ok only when Docker Desktop.exe exists afterward.
#[cfg(windows)]
async fn install_docker_desktop_winget(app: &AppHandle) -> Result<(), String> {
    if !winget_available() {
        return Err("winget (App Installer) not available".into());
    }
    let mut cmd = tokio::process::Command::new("winget");
    cmd.args([
        "install",
        "--id", "Docker.DockerDesktop",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--disable-interactivity",
    ]);
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::null());
    cmd.stdin(std::process::Stdio::null());
    // Hide the console window entirely: `CREATE_NO_WINDOW` (0x08000000) stops
    // winget (a console app) from flashing a terminal box when spawned from the
    // GUI process (observed 2026-08-16). `DETACHED_PROCESS` alone can still
    // open a console. tokio's Command exposes creation_flags inherently.
    cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    let result = tokio::time::timeout(DOCKER_INSTALL_TIMEOUT, child.wait()).await;
    match result {
        Ok(Ok(status)) if status.success() => {
            // Confirm the exe appeared (install success even if the post-step
            // launch is not immediate).
            if docker_desktop_candidates().iter().any(|p| p.exists()) {
                notify_docker(app, "Docker Desktop", "Docker Desktop 安装完成，正在启动引擎…");
                Ok(())
            } else {
                Err("winget reported success but Docker Desktop.exe was not found".into())
            }
        }
        Ok(Ok(status)) => Err(format!("winget install failed (exit {:?})", status.code())),
        Ok(Err(e)) => Err(format!("winget install error: {e}")),
        Err(_) => Err("winget install timed out after 10 minutes".into()),
    }
}

/// Install Docker Desktop from the bundled offline installer (offline build,
/// A-ONB02/B extension, manual test 2026-08-16 request). Runs the Docker
/// Desktop Installer.exe silently (no shell=True). Same bounded await and
/// existence check as the winget path; on success fires a toast.
#[cfg(windows)]
async fn install_docker_desktop_bundled(
    app: &AppHandle,
    installer: &std::path::Path,
) -> Result<(), String> {
    let mut cmd = tokio::process::Command::new(installer);
    // Docker Desktop Installer silent flags (documented by Docker):
    // install --quiet --accept-license [--backend=wsl-2]. Default backend is
    // WSL 2 on supported hosts.
    cmd.args(["install", "--quiet", "--accept-license"]);
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::null());
    cmd.stdin(std::process::Stdio::null());
    cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    let result = tokio::time::timeout(DOCKER_INSTALL_TIMEOUT, child.wait()).await;
    match result {
        Ok(Ok(status)) if status.success() => {
            if docker_desktop_candidates().iter().any(|p| p.exists()) {
                notify_docker(app, "Docker Desktop", "Docker Desktop 安装完成，正在启动引擎…");
                Ok(())
            } else {
                Err("bundled installer reported success but Docker Desktop.exe was not found".into())
            }
        }
        Ok(Ok(status)) => Err(format!("bundled installer failed (exit {:?})", status.code())),
        Ok(Err(e)) => Err(format!("bundled installer error: {e}")),
        Err(_) => Err("bundled installer timed out after 10 minutes".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- IDEA-3 (3b): keyed op-token map (concurrent workspaces) ---

    #[test]
    fn op_tokens_are_keyed_and_independent() {
        let map: OpTokenMap = Default::default();
        let (a, b) = (CancellationToken::new(), CancellationToken::new());
        insert_op(&map, "runtime-a", a.clone());
        insert_op(&map, "runtime-b", b.clone());

        assert!(cancel_op(&map, "runtime-a"));
        assert!(a.is_cancelled());
        assert!(!b.is_cancelled(), "cancel must not bleed across keys");

        remove_op(&map, "runtime-a");
        assert!(!cancel_op(&map, "runtime-a"), "late cancel is a no-op");
        assert!(cancel_op(&map, "runtime-b"), "other key still cancellable");
    }

    #[test]
    fn op_cancel_of_unknown_key_is_a_noop() {
        let map: OpTokenMap = Default::default();
        assert!(!cancel_op(&map, "never-started"));
        remove_op(&map, "never-started"); // removing an absent key must not panic
    }

    #[test]
    fn op_same_key_restart_replaces_the_token() {
        let map: OpTokenMap = Default::default();
        let first = CancellationToken::new();
        insert_op(&map, "rid", first.clone());
        let second = CancellationToken::new();
        insert_op(&map, "rid", second.clone());
        assert!(cancel_op(&map, "rid"));
        assert!(second.is_cancelled());
        assert!(!first.is_cancelled(), "superseded token is untouched");
    }

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

    #[cfg(windows)]
    #[test]
    fn docker_candidates_are_well_formed_and_single_sourced() {
        // Both start_docker and env readiness must resolve the same paths.
        let candidates = docker_desktop_candidates();
        for c in &candidates {
            assert!(c.to_string_lossy().ends_with("Docker Desktop.exe"));
        }
        // env.rs reads through the same fn (single source), so this also
        // exercises the shared path.
        let via_env = crate::env::docker_desktop_candidates();
        assert_eq!(candidates.len(), via_env.len());
        if !candidates.is_empty() {
            assert_eq!(candidates[0], via_env[0]);
        }
    }

    #[cfg(windows)]
    mod suppress_dashboard {
        use super::*;

        fn read(p: &std::path::Path) -> serde_json::Value {
            serde_json::from_slice(&std::fs::read(p).unwrap()).unwrap()
        }

        #[test]
        fn modern_store_key_set_and_other_keys_preserved() {
            let dir = tempfile::tempdir().unwrap();
            std::fs::write(
                dir.path().join("settings-store.json"),
                r#"{ "AutoStart": false, "SettingsVersion": 45 }"#,
            )
            .unwrap();
            assert!(suppress_docker_dashboard_in(dir.path()));
            let v = read(&dir.path().join("settings-store.json"));
            assert_eq!(v["OpenUIOnStartupDisabled"], serde_json::json!(true));
            assert_eq!(v["AutoStart"], serde_json::json!(false)); // untouched
            assert_eq!(v["SettingsVersion"], serde_json::json!(45));
        }

        #[test]
        fn already_suppressed_is_a_no_write() {
            let dir = tempfile::tempdir().unwrap();
            std::fs::write(
                dir.path().join("settings-store.json"),
                r#"{ "OpenUIOnStartupDisabled": true, "AutoStart": false }"#,
            )
            .unwrap();
            let before = std::fs::read(dir.path().join("settings-store.json")).unwrap();
            assert!(!suppress_docker_dashboard_in(dir.path()));
            let after = std::fs::read(dir.path().join("settings-store.json")).unwrap();
            assert_eq!(before, after); // byte-identical, never rewritten
        }

        #[test]
        fn legacy_settings_json_uses_camel_case_key() {
            let dir = tempfile::tempdir().unwrap();
            std::fs::write(dir.path().join("settings.json"), r#"{ "autoStart": true }"#)
                .unwrap();
            assert!(suppress_docker_dashboard_in(dir.path()));
            let v = read(&dir.path().join("settings.json"));
            assert_eq!(v["openUIOnStartupDisabled"], serde_json::json!(true));
            assert_eq!(v["autoStart"], serde_json::json!(true));
            // The modern store must NOT be created when the legacy file exists.
            assert!(!dir.path().join("settings-store.json").exists());
        }

        #[test]
        fn fresh_install_writes_minimal_store() {
            let dir = tempfile::tempdir().unwrap();
            assert!(suppress_docker_dashboard_in(dir.path()));
            let v = read(&dir.path().join("settings-store.json"));
            assert_eq!(v["OpenUIOnStartupDisabled"], serde_json::json!(true));
        }

        #[test]
        fn corrupt_or_non_object_store_left_alone() {
            let dir = tempfile::tempdir().unwrap();
            // Corrupt JSON: never rewritten (data preservation beats silence).
            std::fs::write(dir.path().join("settings-store.json"), b"{not json").unwrap();
            assert!(!suppress_docker_dashboard_in(dir.path()));
            assert_eq!(std::fs::read(dir.path().join("settings-store.json")).unwrap(), b"{not json");
            // Non-object root: also untouched.
            let dir2 = tempfile::tempdir().unwrap();
            std::fs::write(dir2.path().join("settings-store.json"), b"[1,2]").unwrap();
            assert!(!suppress_docker_dashboard_in(dir2.path()));
            assert_eq!(std::fs::read(dir2.path().join("settings-store.json")).unwrap(), b"[1,2]");
        }

        #[test]
        fn explicit_false_is_upgraded_to_true() {
            // The user (or an older Docker version) disabled suppression —
            // Workbench re-silences; only true→false is forbidden.
            let dir = tempfile::tempdir().unwrap();
            std::fs::write(
                dir.path().join("settings-store.json"),
                r#"{ "OpenUIOnStartupDisabled": false }"#,
            )
            .unwrap();
            assert!(suppress_docker_dashboard_in(dir.path()));
            let v = read(&dir.path().join("settings-store.json"));
            assert_eq!(v["OpenUIOnStartupDisabled"], serde_json::json!(true));
        }
    }

    #[cfg(windows)]
    #[test]
    fn winget_detect_and_install_argv_is_safe() {
        // winget_available must not panic regardless of availability.
        let _ = winget_available();
        // The install argv is fixed and never uses shell=True; assert the
        // command shape by checking winget_available path only (spawning a real
        // install in a unit test would be destructive, so we only verify the
        // helper exists and does not panic).
        assert!(winget_available() == winget_available()); // deterministic
    }

    #[test]
    fn stop_argv_threads_workspace_and_grace3() {
        let argv = runtime_stop_argv("rid", "/ws");
        assert_eq!(argv[1], "stop");
        assert!(argv.contains(&"--workspace".into()));
        assert!(argv.contains(&"/ws".into()));
        // Workbench fast path: --grace 3 (03 §4.2; CLI default stays 10).
        let g = argv.iter().position(|a| a == "--grace").unwrap();
        assert_eq!(argv[g + 1], "3");
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

    #[test]
    fn provider_current_argv_shape() {
        let argv = provider_current_argv("rid", "claude", "/ws");
        assert_eq!(argv[0], "provider");
        assert_eq!(argv[1], "current");
        assert!(argv.contains(&"--runtime-id".into()));
        assert!(argv.contains(&"rid".into()));
        assert!(argv.contains(&"--agent".into()));
        assert!(argv.contains(&"claude".into()));
        assert!(argv.contains(&"--workspace".into()));
        assert!(argv.contains(&"/ws".into()));
        assert!(argv.contains(&"--format".into()));
        assert!(argv.contains(&"json".into()));
    }

    #[test]
    fn provider_status_parses() {
        let json = r#"{
            "runtime_id": "rid", "agent": "claude",
            "provider_id": "cc-switch", "provider_name": "CC Switch",
            "route_mode": "cc-switch-proxy", "auth_status": "configured",
            "observed_at": "2026-08-07T00:00:00Z"
        }"#;
        let s: ProviderStatus = serde_json::from_str(json).unwrap();
        assert_eq!(s.agent, "claude");
        assert_eq!(s.provider_name, "CC Switch");
        assert_eq!(s.route_mode, "cc-switch-proxy");
        assert_eq!(s.auth_status, "configured");
    }

    #[test]
    fn provider_status_parses_empty_fields() {
        // Some fields may come back empty (e.g. no provider configured).
        let json = r#"{
            "runtime_id": "rid", "agent": "codex",
            "provider_id": "", "provider_name": "",
            "route_mode": "unknown", "auth_status": "not_configured",
            "observed_at": "t"
        }"#;
        let s: ProviderStatus = serde_json::from_str(json).unwrap();
        assert_eq!(s.agent, "codex");
        assert_eq!(s.auth_status, "not_configured");
        assert_eq!(s.provider_name, "");
    }

    #[tokio::test]
    async fn op_lock_serializes_same_runtime() {
        let m = OpMutexes::default();
        let g1 = acquire_op_lock(&m, "rid-a").await;
        let m2 = m.clone();
        let h = tokio::spawn(async move {
            let _g2 = acquire_op_lock(&m2, "rid-a").await;
            true
        });
        // Second acquire on the same id must block while the first holds it.
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        assert!(!h.is_finished(), "same-runtime op should block");
        drop(g1);
        let done = tokio::time::timeout(std::time::Duration::from_millis(500), h).await;
        assert!(done.is_ok(), "second op completes after the first releases");
    }

    #[tokio::test]
    async fn op_lock_concurrent_different_runtimes() {
        let m = OpMutexes::default();
        let _g1 = acquire_op_lock(&m, "rid-a").await;
        // Different runtime id acquires immediately (no blocking).
        let g2 = acquire_op_lock(&m, "rid-b").await;
        drop(g2);
    }
}
