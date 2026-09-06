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

// ===========================================================================
// PERF P5b (D-13): direct heartbeat write — O6b 兑现.
//
// The heartbeat is a pure file refresh (lock → read → verify ids → update
// lease_last_seen_at); paying a full aisc.exe spawn (~750ms) every 15s per
// workspace = 240 spawns/hour of pure overhead. Lock interop with Python's
// msvcrt/fcntl file_lock is PROVEN both ways (tests/lock_interop.rs, P5a),
// so Rust takes the SAME lock and writes the SAME record shape
// (domain/workspace_lease.py `to_dict`). claim and release stay CLI-side
// (low-frequency control operations). `AISC_LEASE_HEARTBEAT=cli` restores
// the spawn path.
// ===========================================================================

const LEASE_SCHEMA: &str = "aisc.workspace-lease/v1";
const LEASE_SCHEMA_VERSION: i64 = 1;
const LEASE_REL: &str = "runtime-lease.json";
const LEASE_LOCK_NAME: &str = "runtime-lease";

/// Outcome of one in-process heartbeat attempt.
#[derive(Debug, PartialEq, Eq)]
pub enum DirectBeat {
    /// `lease_last_seen_at` refreshed in place.
    Refreshed,
    /// No (parseable) lease on disk — the CLI path re-claims.
    Absent,
    /// Another instance/lease owns the record — stop beating, re-reconcile.
    Conflict,
    /// Lock not acquired within budget — skip this beat (TTL absorbs two).
    Busy,
    /// Direct machinery unusable (no data root / IO errors) — CLI fallback.
    Unavailable,
}

/// `(lease_file, lock_file)` for a resolved root, mirroring
/// DataRootStore.path_for("workspace", LEASE_REL) and lock_path_for
/// (workspace-scoped: `<sha256-v1-<hex>>-runtime-lease.lock` under
/// `state/locks/`).
fn lease_paths_for(
    root: &crate::data_root::ResolvedDataRoot,
) -> (std::path::PathBuf, std::path::PathBuf) {
    let hash_dir = root.workspace_hash.replacen(':', "-", 1);
    let lock = root
        .root
        .join("state")
        .join("locks")
        .join(format!("{hash_dir}-{LEASE_LOCK_NAME}.lock"));
    (root.workspace_dir().join(LEASE_REL), lock)
}

/// RFC3339 UTC with `+00:00` (Python `datetime.isoformat` parity — every
/// Python we ship parses it with `fromisoformat`).
fn now_iso_utc() -> String {
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = d.as_secs() as i64;
    let micros = d.subsec_micros();
    let days = secs.div_euclid(86_400);
    let sod = secs.rem_euclid(86_400);
    let (y, m, dd) = civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{dd:02}T{:02}:{:02}:{:02}.{micros:06}+00:00",
        sod / 3600,
        (sod % 3600) / 60,
        sod % 60
    )
}

/// Howard Hinnant's civil-from-days (proleptic Gregorian; valid for any
/// realistic timestamp).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Explicit-unlock guard (fs4 locks are not auto-released on drop on every
/// platform/path — be deterministic).
struct LockGuard<'a>(&'a std::fs::File);
impl Drop for LockGuard<'_> {
    fn drop(&mut self) {
        use fs4::fs_std::FileExt;
        let _ = self.0.unlock();
    }
}

/// One in-process heartbeat: same semantics as
/// `WorkspaceLeaseStore.heartbeat` (workspace_lease_store.py L123-164) —
/// absent → Absent; id mismatch → Conflict; match → rewrite with only
/// `lease_last_seen_at` moved (schema fail-closed parity with
/// `lease_from_dict`: foreign/garbage → Absent).
pub fn beat_direct(
    workspace: &std::path::Path,
    instance_id: &str,
    lease_id: &str,
) -> DirectBeat {
    match crate::data_root::resolve_data_root(workspace) {
        Ok(root) => beat_direct_in(&root, instance_id, lease_id),
        Err(_) => DirectBeat::Unavailable,
    }
}

/// Root-injected core (tests construct the root directly — no env mutation,
/// which raced other suites' AISC_DATA_ROOT tests).
fn beat_direct_in(
    root: &crate::data_root::ResolvedDataRoot,
    instance_id: &str,
    lease_id: &str,
) -> DirectBeat {
    use fs4::fs_std::FileExt;

    let (lease_file, lock_file) = lease_paths_for(root);
    let Some(parent) = lock_file.parent() else {
        return DirectBeat::Unavailable;
    };
    if std::fs::create_dir_all(parent).is_err() {
        return DirectBeat::Unavailable;
    }
    let lock_handle = match std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(&lock_file)
    {
        Ok(f) => f,
        Err(_) => return DirectBeat::Unavailable,
    };
    // Bounded acquisition: 3s of retries, then skip the beat (the 45s TTL
    // absorbs two skipped periods; a CLI fallback here would just block on
    // the same lock for longer).
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    loop {
        match lock_handle.try_lock_exclusive() {
            Ok(true) => break,
            Ok(false) => {
                if std::time::Instant::now() >= deadline {
                    return DirectBeat::Busy;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(_) => return DirectBeat::Unavailable,
        }
    }
    let _guard = LockGuard(&lock_handle);

    let text = match std::fs::read_to_string(&lease_file) {
        Ok(t) => t,
        Err(_) => return DirectBeat::Absent,
    };
    let mut rec: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => return DirectBeat::Absent,
    };
    let schema_ok = rec["schema"].as_str().map_or(true, |s| s == LEASE_SCHEMA)
        && rec["schema_version"].as_i64().unwrap_or(LEASE_SCHEMA_VERSION) == LEASE_SCHEMA_VERSION;
    if !schema_ok {
        return DirectBeat::Absent;
    }
    let holder = rec["workbench_instance_id"].as_str().unwrap_or("");
    let current_lease = rec["lease_id"].as_str().unwrap_or("");
    if holder != instance_id || (!lease_id.is_empty() && current_lease != lease_id) {
        return DirectBeat::Conflict;
    }
    rec["lease_last_seen_at"] = serde_json::Value::String(now_iso_utc());
    let bytes = serde_json::to_vec_pretty(&rec).unwrap_or_default();
    match crate::storage::atomic_replace(&lease_file, &bytes) {
        Ok(()) => DirectBeat::Refreshed,
        Err(_) => DirectBeat::Unavailable,
    }
}

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
            // PERF P5b: in-process file refresh first — zero spawns. Absent
            // (lease file gone) and Unavailable (no data root / IO trouble)
            // fall back to the CLI heartbeat, which owns re-claim and the
            // rich error mapping; Busy skips the beat (TTL absorbs). The
            // escape hatch AISC_LEASE_HEARTBEAT=cli keeps the old path.
            let direct_allowed = std::env::var("AISC_LEASE_HEARTBEAT")
                .map(|v| v != "cli")
                .unwrap_or(true);
            if direct_allowed {
                let ws = beat_workspace.clone();
                let inst = beat_instance.clone();
                let lid = beat_lease.clone();
                let beat = tokio::task::spawn_blocking(move || {
                    beat_direct(std::path::Path::new(&ws), &inst, &lid)
                })
                .await
                .unwrap_or(DirectBeat::Unavailable);
                match beat {
                    DirectBeat::Refreshed => continue,
                    DirectBeat::Busy => continue,
                    DirectBeat::Conflict => {
                        handle_lease_conflict(&beat_app, &beat_workspace, &beat_lease);
                        break;
                    }
                    // Absent / Unavailable: CLI heartbeat below.
                    DirectBeat::Absent | DirectBeat::Unavailable => {}
                }
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
                    handle_lease_conflict(&beat_app, &beat_workspace, &beat_lease);
                    break;
                }
                // Transient failure: keep beating; the TTL (3 periods)
                // absorbs it.
            }
        }
    });

    Ok(claim)
}

/// Lost the lease (taken over after expiry): stop beating and tell the
/// frontend to re-run reconcile (02 §2). Shared by the direct-write and CLI
/// conflict paths.
fn handle_lease_conflict(app: &AppHandle, workspace: &str, lease_id: &str) {
    let supervisor = app.state::<LeaseSupervisor>();
    let mut beats = supervisor.beats.lock().unwrap_or_else(|p| p.into_inner());
    if beats
        .get(workspace)
        .map(|b| b.lease_id == lease_id)
        .unwrap_or(false)
    {
        beats.remove(workspace);
    }
    let _ = app.emit(
        "workspace-lease-conflict",
        serde_json::json!({ "workspace": workspace }),
    );
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

    // --- PERF P5b: direct heartbeat write --------------------------------

    use std::collections::BTreeMap;
    use std::fs;
    use std::path::{Path, PathBuf};

    /// A synthetic root pointing at a tempdir — NO env mutation (which raced
    /// other suites' AISC_DATA_ROOT tests when both locks were separate).
    fn synthetic_root(tmp: &Path) -> crate::data_root::ResolvedDataRoot {
        let mut shared: BTreeMap<&str, PathBuf> = BTreeMap::new();
        shared.insert("workspaces", tmp.join("workspaces"));
        crate::data_root::ResolvedDataRoot {
            root: tmp.to_path_buf(),
            origin: "env",
            workspace_hash: "sha256-v1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
            writable: true,
            shared_dirs: shared,
            workspace_dirs: BTreeMap::new(),
        }
    }

    fn write_lease(dir: &Path, instance: &str, lease: &str) -> PathBuf {
        let file = dir.join("runtime-lease.json");
        fs::write(
            &file,
            serde_json::json!({
                "schema": LEASE_SCHEMA, "schema_version": 1,
                "workspace_key": "sha256-v1:abc",
                "lease_id": lease,
                "workbench_instance_id": instance,
                "claimed_at": "2026-09-06T00:00:00+00:00",
                "lease_last_seen_at": "2026-09-06T00:00:01+00:00",
            })
            .to_string(),
        )
        .unwrap();
        file
    }

    #[test]
    fn civil_from_days_matches_known_dates() {
        // Unix epoch + spot checks (incl. a leap day).
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(19_782), (2024, 2, 29)); // 2024-02-29
        assert_eq!(civil_from_days(20_638), (2026, 7, 4));
    }

    #[test]
    fn beat_direct_matrix() {
        let tmp = tempfile::tempdir().unwrap();
        let root = synthetic_root(tmp.path());
        let lease_dir = root.workspace_dir();
        fs::create_dir_all(&lease_dir).unwrap();

        // Absent: no file.
        assert_eq!(beat_direct_in(&root, "inst-1", "lease-1"), DirectBeat::Absent);

        // Refreshed: matching ids -> only lease_last_seen_at moves.
        let file = write_lease(&lease_dir, "inst-1", "lease-1");
        assert_eq!(
            beat_direct_in(&root, "inst-1", "lease-1"),
            DirectBeat::Refreshed
        );
        let rec: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&file).unwrap()).unwrap();
        assert_eq!(rec["lease_id"], "lease-1");
        assert_eq!(rec["claimed_at"], "2026-09-06T00:00:00+00:00");
        assert_ne!(rec["lease_last_seen_at"], "2026-09-06T00:00:01+00:00");

        // Conflict: another instance owns it.
        assert_eq!(
            beat_direct_in(&root, "inst-2", "lease-1"),
            DirectBeat::Conflict
        );

        // Absent (fail-closed): foreign schema.
        fs::write(&file, r#"{"schema": "other/v9", "schema_version": 1}"#).unwrap();
        assert_eq!(beat_direct_in(&root, "inst-1", "lease-1"), DirectBeat::Absent);

        // Lock layout parity with Python lock_path_for(workspace).
        let (lease_file, lock_file) = lease_paths_for(&root);
        assert!(lease_file.ends_with("runtime-lease.json"));
        assert!(lock_file.ends_with(concat!(
            "sha256-v1-0123456789abcdef0123456789abcdef",
            "0123456789abcdef0123456789abcdef-runtime-lease.lock"
        )));
    }

    /// Cross-language parity: the record Rust writes must parse and read as
    /// FRESH through the Python domain model (`lease_from_dict` +
    /// `age_seconds`) — field names and the timestamp format are a contract.
    #[test]
    fn rust_lease_output_parses_in_python() {
        let tmp = tempfile::tempdir().unwrap();
        let root = synthetic_root(tmp.path());
        fs::create_dir_all(root.workspace_dir()).unwrap();
        write_lease(&root.workspace_dir(), "inst-p", "lease-p");
        assert_eq!(
            beat_direct_in(&root, "inst-p", "lease-p"),
            DirectBeat::Refreshed
        );

        let python = std::process::Command::new("python")
            .arg("-c")
            .arg(concat!(
                "import json,sys; sys.path.insert(0, r'",
                env!("CARGO_MANIFEST_DIR"),
                "/../../src');",
                "from aisc.domain.workspace_lease import lease_from_dict;",
                "rec=json.load(open(sys.argv[1], encoding='utf-8'));",
                "lease=lease_from_dict(rec);",
                "assert lease is not None, 'foreign shape';",
                "assert lease.workbench_instance_id=='inst-p';",
                "age=lease.age_seconds();",
                "assert age is not None and age < 60, age;",
                "print('fresh')"
            ))
            .arg(root.workspace_dir().join("runtime-lease.json"))
            .output();
        match python {
            Ok(out) if out.status.success() => {}
            Ok(out) => panic!(
                "python parity check failed: {:?} / {}",
                out.status.code(),
                String::from_utf8_lossy(&out.stderr)
            ),
            Err(e) => panic!("python parity check spawn failed: {e}"),
        }
    }
}
