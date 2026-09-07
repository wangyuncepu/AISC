//! 2.1.10 R2c: the active CLI target — which machine's aisc the Workbench
//! drives. `None` = this machine (the only mode before 2.1.10); `Some` = a
//! machine from settings `remoteMachines`, reached per-op over SSH (D-8's
//! dual-channel model: control ops per-op ssh, PTY streams over serve).
//!
//! R2c-lite scope: the SESSION plane consults this state (serve PTY path);
//! the runtime/lease op routing and the docker_api direct-connection
//! degradation (G2) land in the R2c continuation batch.

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
pub async fn target_get(app: tauri::AppHandle) -> Result<TargetInfo, WorkbenchError> {
    let state = app
        .state::<ActiveTarget>()
        .current();
    Ok(TargetInfo {
        kind: if state.is_some() { "remote" } else { "local" },
        machine: state,
    })
}

#[tauri::command]
pub async fn target_set(
    app: tauri::AppHandle,
    name: String,
) -> Result<TargetInfo, WorkbenchError> {
    let machine = machine_by_name(&app, &name)?;
    let state = app.state::<ActiveTarget>();
    *state
        .0
        .lock()
        .map_err(|_| WorkbenchError::cli_protocol().with_detail("target lock"))? = Some(machine.clone());
    let _ = &app;
    crate::logging::append_event(
        "info",
        "app",
        "target_set",
        None,
        serde_json::json!({ "machine": machine.name, "host": machine.host }),
    );
    Ok(TargetInfo { machine: Some(machine), kind: "remote" })
}

#[tauri::command]
pub async fn target_clear(app: tauri::AppHandle) -> Result<TargetInfo, WorkbenchError> {
    let state = app.state::<ActiveTarget>();
    *state
        .0
        .lock()
        .map_err(|_| WorkbenchError::cli_protocol().with_detail("target lock"))? = None;
    Ok(TargetInfo { machine: None, kind: "local" })
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
