//! Workspace-lease supervisor (runtime-lifecycle-ux Stage 2, D-RUNTIME-12).
//!
//! One tokio interval task per active workspace refreshes the lease
//! heartbeat through the CLI (`aisc runtime lease heartbeat`). The writer
//! MUST live Rust-side: WebView JS timers throttle once the window hides
//! to tray, which would expire leases for runtimes that are still in use.
//!
//! Semantics:
//! - `instance_id`: minted once per Workbench process; every claim, heartbeat
//!   and release for this run carries it.
//! - claim conflicts surface as `AISC_ERR_ACTIVE_WORKSPACE_LEASE` (the CLI
//!   maps it); a heartbeat that loses the lease to a takeover emits
//!   `workspace-lease-conflict` and stops beating (the frontend re-runs
//!   reconcile per 02 §2).
//! - transient heartbeat failures are tolerated up to the lease TTL (3
//!   periods, 15s each — mirrored from domain/workspace_lease.py); the task
//!   keeps beating unless cancelled or conflicted.
//! - `lease_release` cancels the task and releases via CLI; releasing an
//!   unknown workspace is a no-op.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio_util::sync::CancellationToken;

use crate::cli::{run_control, Envelope};
use crate::error::WorkbenchError;
use crate::runtime::{envelope_error, lease_argv, LEASE_TIMEOUT};
use crate::session::resolve_cli;

/// Heartbeat cadence — must stay in lockstep with
/// `LEASE_HEARTBEAT_INTERVAL_SECONDS` (15s) and the 45s TTL in
/// `src/aisc/domain/workspace_lease.py`.
pub const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct LeaseClaimResult {
    pub outcome: String, // claimed | claimed_stale | reclaimed
    pub lease_id: String,
    pub workspace_key: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SupervisorInfo {
    pub instance_id: String,
}

struct LeaseBeat {
    workspace: String,
    lease_id: String,
    cancel: CancellationToken,
}

#[derive(Default)]
pub struct LeaseSupervisor {
    instance_id: Mutex<Option<String>>,
    beats: Mutex<HashMap<String, LeaseBeat>>,
}

impl LeaseSupervisor {
    /// Per-run instance id, minted on first use.
    pub fn instance_id(&self) -> String {
        let mut g = self.instance_id.lock().unwrap_or_else(|p| p.into_inner());
        if g.is_none() {
            *g = Some(uuid::Uuid::new_v4().to_string());
        }
        g.clone().unwrap_or_default()
    }

    /// Workspaces currently holding a heartbeat task (shutdown releases
    /// exactly these).
    pub fn active_workspaces(&self) -> Vec<String> {
        let beats = self.beats.lock().unwrap_or_else(|p| p.into_inner());
        beats.keys().cloned().collect()
    }
}

/// Claim a workspace lease and start its heartbeat task.
#[tauri::command]
pub async fn lease_claim(
    app: AppHandle,
    workspace: String,
) -> Result<LeaseClaimResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let supervisor = app.state::<LeaseSupervisor>();
    let instance_id = supervisor.instance_id();
    let argv = lease_argv("claim", &workspace, Some(&instance_id), None);
    let env = run_control(&pin, argv, LEASE_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let claim: LeaseClaimResult = decode_lease_data(&env)
        .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("lease claim parse"))?;

    let cancel = CancellationToken::new();
    {
        let mut beats = supervisor.beats.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(old) = beats.insert(
            workspace.clone(),
            LeaseBeat {
                workspace: workspace.clone(),
                lease_id: claim.lease_id.clone(),
                cancel: cancel.clone(),
            },
        ) {
            old.cancel.cancel(); // replace any previous beat for this workspace
        }
    }

    let beat_app = app.clone();
    let beat_workspace = workspace.clone();
    let beat_lease = claim.lease_id.clone();
    let beat_instance = instance_id.clone();
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => break,
                _ = tokio::time::sleep(HEARTBEAT_INTERVAL) => {}
            }
            let Ok(pin) = resolve_cli(&beat_app).await else { continue };
            let argv = lease_argv(
                "heartbeat", &beat_workspace,
                Some(&beat_instance), Some(&beat_lease),
            );
            let Ok(env) = run_control(&pin, argv, LEASE_TIMEOUT, CancellationToken::new()).await
            else { continue };
            if let Some(err) = envelope_error(&env) {
                if err.code == "AISC_ERR_RUNTIME_LEASE_CONFLICT"
                    || err.code == "AISC_ERR_ACTIVE_WORKSPACE_LEASE"
                {
                    // Lost the lease (taken over after expiry): stop beating
                    // and tell the frontend to re-run reconcile (02 §2).
                    let supervisor = beat_app.state::<LeaseSupervisor>();
                    let mut beats =
                        supervisor.beats.lock().unwrap_or_else(|p| p.into_inner());
                    if beats
                        .get(&beat_workspace)
                        .map(|b| b.lease_id == beat_lease)
                        .unwrap_or(false)
                    {
                        beats.remove(&beat_workspace);
                    }
                    let _ = beat_app.emit(
                        "workspace-lease-conflict",
                        serde_json::json!({ "workspace": beat_workspace }),
                    );
                    break;
                }
                // Transient failure: keep beating; the TTL (3 periods)
                // absorbs it.
            }
        }
    });

    Ok(claim)
}

/// Stop the heartbeat task and release the lease (no-op when unknown).
#[tauri::command]
pub async fn lease_release(
    app: AppHandle,
    workspace: String,
) -> Result<bool, WorkbenchError> {
    let supervisor = app.state::<LeaseSupervisor>();
    let beat = {
        let mut beats = supervisor.beats.lock().unwrap_or_else(|p| p.into_inner());
        beats.remove(&workspace)
    };
    let Some(beat) = beat else { return Ok(false) };
    beat.cancel.cancel();
    let pin = resolve_cli(&app).await?;
    let argv = lease_argv(
        "release", &workspace,
        Some(&supervisor.instance_id()), Some(&beat.lease_id),
    );
    let env = run_control(&pin, argv, LEASE_TIMEOUT, CancellationToken::new()).await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    // data: {action, released, workspace_key}
    let released = env
        .data
        .as_ref()
        .and_then(|d| d.get("released"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    Ok(released)
}

/// This run's instance id (for diagnostics / reconcile calls).
#[tauri::command]
pub async fn lease_supervisor_info(
    app: AppHandle,
) -> Result<SupervisorInfo, WorkbenchError> {
    Ok(SupervisorInfo {
        instance_id: app.state::<LeaseSupervisor>().instance_id(),
    })
}

fn decode_lease_data(env: &Envelope) -> Option<LeaseClaimResult> {
    let data = env.data.as_ref()?;
    Some(LeaseClaimResult {
        outcome: data.get("outcome")?.as_str()?.to_string(),
        lease_id: data.get("lease_id")?.as_str()?.to_string(),
        workspace_key: data
            .get("workspace_key")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heartbeat_interval_matches_python_contract() {
        // domain/workspace_lease.py: 15s heartbeat, 45s TTL (3 periods).
        assert_eq!(HEARTBEAT_INTERVAL.as_secs(), 15);
    }

    #[test]
    fn instance_id_is_stable_per_supervisor() {
        let s = LeaseSupervisor::default();
        let a = s.instance_id();
        assert_eq!(a, s.instance_id());
        assert!(uuid::Uuid::parse_str(&a).is_ok(), "must be a UUID");
    }

    #[test]
    fn lease_claim_result_decodes_envelope_data() {
        let env = Envelope {
            data: Some(serde_json::json!({
                "outcome": "claimed", "lease_id": "l-1", "workspace_key": "k"
            })),
            ..empty_envelope()
        };
        let r = decode_lease_data(&env).expect("decodes");
        assert_eq!((r.outcome.as_str(), r.lease_id.as_str()), ("claimed", "l-1"));
    }

    #[test]
    fn lease_claim_result_missing_fields_is_none() {
        let env = Envelope {
            data: Some(serde_json::json!({"outcome": "claimed"})),
            ..empty_envelope()
        };
        assert!(decode_lease_data(&env).is_none());
    }

    fn empty_envelope() -> Envelope {
        serde_json::from_value(serde_json::json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "runtime",
                     "exit_code": 0, "timestamp": "", "version": "", "run_id": ""},
            "errors": []
        }))
        .expect("fixture envelope")
    }
}
