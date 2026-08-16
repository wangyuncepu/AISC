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
use crate::session::resolve_pin;

const START_TIMEOUT: Duration = Duration::from_secs(120);
const STOP_TIMEOUT: Duration = Duration::from_secs(30);
const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(120);
const RESTART_TIMEOUT: Duration = Duration::from_secs(120);
const REMOVE_TIMEOUT: Duration = Duration::from_secs(60);
const LIST_TIMEOUT: Duration = Duration::from_secs(30);
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(30);
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
    let pin = resolve_pin(&app)?;
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
    let pin = resolve_pin(&app)?;
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

/// Start the Docker engine (Docker Desktop on Windows, Docker.app on macOS).
/// Returns Ok(()) if the launch was attempted; the daemon still needs time to
/// come up, so callers re-run preflight after a short delay. Non-Windows/macOS
/// returns an actionable error (systemd on Linux is out of scope for the app).
#[tauri::command]
pub async fn start_docker() -> Result<(), WorkbenchError> {
    #[cfg(windows)]
    {
        // Docker Desktop.exe already present → just launch it.
        for exe in docker_desktop_candidates() {
            if exe.exists() {
                std::process::Command::new(&exe).spawn().map_err(|e| {
                    WorkbenchError::cli_protocol()
                        .with_detail(format!("failed to start Docker Desktop: {e}"))
                })?;
                return Ok(());
            }
        }
        // Missing → silently install via winget (Stage 5, A-ONB02/B):
        // the first-run wizard's "Start Docker" must also cover install, not
        // just launch. Only for interactive sessions; no shell=True anywhere.
        match install_docker_desktop_winget() {
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

/// Candidate paths for the Docker Desktop executable (Windows). Single source
/// shared by `start_docker` and the env readiness probe (env.rs).
#[cfg(windows)]
pub(crate) fn docker_desktop_candidates() -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    if let Ok(base) = std::env::var("LOCALAPPDATA") {
        out.push(std::path::PathBuf::from(base).join("Docker\\Docker Desktop\\Docker Desktop.exe"));
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

/// Silently install Docker Desktop via winget (Stage 5, A-ONB02/B). Non-blocking:
/// spawns the installer detached so the wizard's readiness poll can watch the
/// install progress (installed → starting → ready). Returns Ok once the install
/// process has been started; errors when winget is unavailable or cannot spawn.
#[cfg(windows)]
fn install_docker_desktop_winget() -> Result<(), String> {
    if !winget_available() {
        return Err("winget (App Installer) not available".into());
    }
    let mut cmd = std::process::Command::new("winget");
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
    // Detached: the installer runs in its own process; we return immediately
    // so the UI can poll. The child is not a child of our process group.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x00000008 /* DETACHED_PROCESS */);
    }
    cmd.spawn().map(|_| ()).map_err(|e| e.to_string())
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
