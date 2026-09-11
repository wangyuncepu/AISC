//! 2.1.10 R2c: the active CLI target — which machine's aisc the Workbench
//! drives. `None` = this machine (the only mode before 2.1.10); `Some` = a
//! machine from settings `remoteMachines`, reached per-op over SSH (D-8's
//! dual-channel model: control ops per-op ssh, PTY streams over serve).
//!
//! R2c-lite scope: the SESSION plane consults this state (serve PTY path);
//! the runtime/lease op routing and the docker_api direct-connection
//! degradation (G2) land in the R2c continuation batch.

use std::collections::HashMap;
use std::sync::Mutex;

use tauri::Manager;

use serde::Serialize;

use crate::cli::{CliTarget, SshTarget};
use crate::error::WorkbenchError;

/// One remote machine profile (settings `remoteMachines`; hand-edited JSON
/// until R4's machine manager UI).
#[derive(Debug, Clone, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteMachine {
    pub name: String,
    pub host: String,
    #[serde(default)]
    pub user: Option<String>,
    #[serde(default)]
    pub port: Option<u16>,
    /// Private key path ON THIS MACHINE (a reference, never copied).
    #[serde(default)]
    pub key_path: Option<String>,
}

impl RemoteMachine {
    pub fn to_ssh_target(&self) -> SshTarget {
        let host = match &self.user {
            Some(u) if !u.trim().is_empty() => format!("{}@{}", u, self.host),
            _ => self.host.clone(),
        };
        SshTarget {
            host,
            port: self.port,
            key_path: self.key_path.clone(),
            extra_args: Vec::new(),
        }
    }
}

/// Managed Tauri state: the machine the Workbench is currently driving.
#[derive(Default)]
pub struct ActiveTarget(pub Mutex<Option<RemoteMachine>>);

/// W3 手测 r3（user ruling #3）: PER-WINDOW drive targets. One workspace
/// per window means one MACHINE per window — a remote workspace window and
/// a local window must never fight over a single process-global target
/// (field evidence: opening a remote recent closed the local window's
/// runtime — its poll rerouted to the remote registry, reconcile saw its
/// container "gone" and recycled it). Windows without an entry fall back
/// to the legacy global [`ActiveTarget`] (pre-switch main window).
#[derive(Default)]
pub struct WindowTargets(pub Mutex<HashMap<String, Option<RemoteMachine>>>);

impl ActiveTarget {
    pub fn current(&self) -> Option<RemoteMachine> {
        self.0.lock().ok().and_then(|g| g.clone())
    }

    pub fn machine(&self, name: &str) -> Option<RemoteMachine> {
        self.current().filter(|m| m.name == name)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TargetInfo {
    /// None = local machine.
    pub machine: Option<RemoteMachine>,
    pub kind: &'static str,
}

#[tauri::command]
pub async fn target_get(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
) -> Result<TargetInfo, WorkbenchError> {
    let state = window_target(&app, &window);
    Ok(TargetInfo {
        kind: if state.is_some() { "remote" } else { "local" },
        machine: state,
    })
}

/// This window's target: its own entry, else the legacy global fallback.
fn window_target(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
) -> Option<RemoteMachine> {
    if let Ok(map) = app.state::<WindowTargets>().0.lock() {
        if let Some(entry) = map.get(window.label()) {
            return entry.clone();
        }
    }
    app.state::<ActiveTarget>().current()
}

#[tauri::command]
pub async fn target_set(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    name: String,
) -> Result<TargetInfo, WorkbenchError> {
    let machine = machine_by_name(&app, &name)?;
    // W3: the switch is THIS window's only — other windows keep driving
    // their machines (see WindowTargets).
    set_window_target(&app, &window, Some(machine.clone()))?;
    // Tunnels bound to the PREVIOUS machine must not shadow the new one on
    // the same ports — tear them all down on every switch (tunnels remain
    // process-global resources; port collisions are real).
    crate::tunnel::close_all_tunnels(app.state::<crate::tunnel::TunnelRegistry>().inner());
    crate::logging::append_event(
        "info",
        "app",
        "target_set",
        None,
        serde_json::json!({ "machine": machine.name, "host": machine.host,
                            "window": window.label() }),
    );
    Ok(TargetInfo { machine: Some(machine), kind: "remote" })
}

#[tauri::command]
pub async fn target_clear(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
) -> Result<TargetInfo, WorkbenchError> {
    crate::tunnel::close_all_tunnels(app.state::<crate::tunnel::TunnelRegistry>().inner());
    set_window_target(&app, &window, None)?;
    Ok(TargetInfo { machine: None, kind: "local" })
}

fn set_window_target(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    target: Option<RemoteMachine>,
) -> Result<(), WorkbenchError> {
    let map = app.state::<WindowTargets>();
    let mut guard = map
        .0
        .lock()
        .map_err(|_| WorkbenchError::cli_protocol().with_detail("window target lock"))?;
    guard.insert(window.label().to_string(), target);
    Ok(())
}

fn machine_by_name(app: &tauri::AppHandle, name: &str) -> Result<RemoteMachine, WorkbenchError> {
    let dir = crate::session::config_dir(app)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("settings dir: {e:?}")))?;
    let doc = crate::settings::load_settings_document(&dir)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("settings: {e}")))?;
    doc.remote_machines
        .into_iter()
        .find(|m| m.name == name)
        .ok_or_else(|| {
            WorkbenchError::cli_protocol()
                .with_detail(format!("no remoteMachines entry named {name:?}"))
        })
}

/// Where session/CLI ops execute right now: local pin or the active machine.
/// The local leg keeps the self-healing `resolve_cli` chain untouched.
pub async fn resolve_target(app: &tauri::AppHandle) -> Result<CliTarget, WorkbenchError> {
    match app.state::<ActiveTarget>().current() {
        None => Ok(CliTarget::Local(crate::session::resolve_cli(app).await?)),
        Some(m) => Ok(CliTarget::Remote(m.to_ssh_target())),
    }
}

/// W3: the caller's WINDOW-scoped target (its own entry, else the global
/// fallback). Every IPC command that spawns CLI work resolves through this.
pub async fn resolve_target_for(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
) -> Result<CliTarget, WorkbenchError> {
    match window_target(app, window) {
        None => Ok(CliTarget::Local(crate::session::resolve_cli(app).await?)),
        Some(m) => Ok(CliTarget::Remote(m.to_ssh_target())),
    }
}
