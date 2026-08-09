//! Session data-plane Tauri commands + registry. Wraps `pty.rs` core with
//! AISC session semantics (runtime_id/session_id/agent/workspace,
//! terminate-on-close, exit ack, shutdown coordination).
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §4.1 (canonical workspace as Session identity),
//!   §6.1 (session open argv, text-only TTY), §9.2 (per-Session handles)
//! - 03-lifecycle-contract.md §2.3 (SessionRegistry Reserved/Closing/ack/TTL),
//!   §3.3 (natural-exit ack), §4.3 (shutdown coordinator), §五 (state machine)

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use serde::Serialize;
use tauri::{ipc::Channel, AppHandle, Manager};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::cli::run_control;
use crate::error::WorkbenchError;
use crate::pty::{
    spawn_pty_session, now_ms, ExitSignal, PtyEvent, PtySession, SessionExit, SessionState,
    REASON_TRANSPORT_ERROR, REASON_USER_CLOSE,
};
use crate::settings::Settings;

const DEFAULT_COLS: u16 = 80;
const DEFAULT_ROWS: u16 = 24;
const MAX_WRITE_BYTES: usize = 1024 * 1024; // 1 MB paste cap (05 §9.2)
// G-07 budgets (03 §4.1): Workbench fast path uses explicit --grace 3; the
// CLI defaults (10/5) stay untouched. These are hard upper bounds, not
// targets.
const TERMINATE_TIMEOUT: Duration = Duration::from_secs(5);
const CLOSE_WAIT: Duration = Duration::from_secs(4);
const CLOSE_FORCE_WAIT: Duration = Duration::from_secs(2);
const EVENT_CHANNEL_CAP: usize = 256;
/// Terminal (reaped) entry TTL before lazy eviction (03 §3.3.5).
const TERMINAL_TTL_MS: i64 = 60_000;
/// Max terminal entries retained per runtime (03 §3.3.5).
const MAX_TERMINAL_ENTRIES_PER_RUNTIME: usize = 32;

const AGENTS: &[&str] = &["claude", "codex", "bash", "cc-switch"];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionSnapshot {
    pub session_id: String,
    pub runtime_id: String,
    pub agent: String,
    pub state: SessionState,
    pub generation: u64,
}

pub struct SessionEntry {
    /// `None` while the entry is `Reserved` (pre-spawn) or during closing.
    pub session: Option<PtySession>,
    pub signal: ExitSignal,
    pub state: SessionState,
    pub exit: Option<SessionExit>,
    pub runtime_id: String,
    pub agent: String,
    /// Canonical workspace (sole producer: Rust backend canonicalize), used as
    /// the identity key for open/terminate argv (05 §4.1). Never the raw
    /// frontend string.
    pub workspace: String,
    /// Monotonic per-registry generation; guards late events after reopen.
    pub generation: u64,
    /// Shared closing completion: concurrent closes await the same result
    /// (03 §2.3.4); set once the terminal exit is known.
    pub close: Option<Arc<ExitSignal>>,
}

/// Managed Tauri state: `session_id -> SessionEntry`, with the spawn-reserve
/// gate and shutdown reject flag. Clone is cheap (Arc fields); managed as
/// `SessionRegistry::default()`.
#[derive(Clone)]
pub struct SessionRegistry {
    map: Arc<Mutex<HashMap<String, SessionEntry>>>,
    next_generation: Arc<AtomicU64>,
    rejecting: Arc<AtomicBool>,
}

impl Default for SessionRegistry {
    fn default() -> Self {
        Self {
            map: Arc::new(Mutex::new(HashMap::new())),
            next_generation: Arc::new(AtomicU64::new(0)),
            rejecting: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl SessionRegistry {
    pub fn lock(&self) -> Result<MutexGuard<'_, HashMap<String, SessionEntry>>, WorkbenchError> {
        self.map
            .lock()
            .map_err(|_| WorkbenchError::cli_protocol().with_detail("registry lock"))
    }

    fn next_generation(&self) -> u64 {
        self.next_generation.fetch_add(1, Ordering::SeqCst)
    }

    /// Shutdown gate: after `reject_new`, `open_session` refuses new sessions.
    pub fn reject_new(&self) {
        self.rejecting.store(true, Ordering::SeqCst);
    }

    pub fn accepting(&self) -> bool {
        !self.rejecting.load(Ordering::SeqCst)
    }
}

fn registry(app: &AppHandle) -> SessionRegistry {
    app.state::<SessionRegistry>().inner().clone()
}

pub fn config_dir(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    app.path()
        .app_config_dir()
        .map_err(|e| WorkbenchError::settings_error().with_detail(format!("config dir: {e}")))
}

pub fn resolve_pin(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    let dir = config_dir(app)?;
    let settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    settings
        .aisc_cli_path()
        .map(PathBuf::from)
        .ok_or_else(WorkbenchError::cli_not_found)
}

fn is_uuid_v4(s: &str) -> bool {
    if s.len() != 36 {
        return false;
    }
    for (i, c) in s.chars().enumerate() {
        match i {
            8 | 13 | 18 | 23 => {
                if c != '-' {
                    return false;
                }
            }
            14 => {
                if c != '4' {
                    return false;
                }
            }
            19 => {
                if !matches!(c, '8' | '9' | 'a' | 'b' | 'A' | 'B') {
                    return false;
                }
            }
            _ => {
                if !c.is_ascii_hexdigit() {
                    return false;
                }
            }
        }
    }
    true
}

fn session_open_argv(
    runtime_id: &str,
    session_id: &str,
    agent: &str,
    workspace: &str,
) -> Vec<String> {
    vec![
        "session".into(),
        "open".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--session-id".into(),
        session_id.into(),
        "--agent".into(),
        agent.into(),
        "--workspace".into(),
        workspace.into(),
    ]
}

fn session_terminate_argv(runtime_id: &str, session_id: &str, workspace: &str) -> Vec<String> {
    vec![
        "session".into(),
        "terminate".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--session-id".into(),
        session_id.into(),
        "--workspace".into(),
        workspace.into(),
        "--grace".into(),
        "3".into(),
        "--format".into(),
        "json".into(),
    ]
}

/// Sole producer of the canonical workspace used as Session identity key
/// (05 §4.1). Frontend raw strings never become Session identity.
fn canonical_workspace(raw: &str) -> Result<String, WorkbenchError> {
    let p = Path::new(raw);
    let canon = std::fs::canonicalize(p).map_err(|e| {
        WorkbenchError::map_aisc("AISC_ERR_WORKSPACE_INVALID")
            .with_detail(format!("canonicalize {raw}: {e}"))
    })?;
    Ok(canon.to_string_lossy().into_owned())
}

fn session_failed(detail: impl Into<String>) -> WorkbenchError {
    WorkbenchError::map_aisc("AISC_ERR_SESSION_FAILED").with_detail(detail)
}

fn is_terminal(state: SessionState) -> bool {
    matches!(state, SessionState::Exited | SessionState::Failed | SessionState::Disconnected)
}

/// Lazy eviction of reaped-but-unacknowledged terminal entries (03 §3.3.5):
/// drop entries past `TERMINAL_TTL_MS`, then per runtime keep at most
/// `MAX_TERMINAL_ENTRIES_PER_RUNTIME`, removing oldest by finished time.
fn sweep_terminal_entries(map: &mut HashMap<String, SessionEntry>) {
    let now = now_ms();
    map.retain(|_, e| {
        e.exit
            .as_ref()
            .map(|x| x.finished_at_ms + TERMINAL_TTL_MS > now)
            .unwrap_or(true)
    });
    let mut per_runtime: HashMap<String, Vec<(String, i64)>> = HashMap::new();
    for (id, e) in map.iter() {
        if let Some(exit) = &e.exit {
            per_runtime
                .entry(e.runtime_id.clone())
                .or_default()
                .push((id.clone(), exit.finished_at_ms));
        }
    }
    for (_, mut entries) in per_runtime {
        if entries.len() <= MAX_TERMINAL_ENTRIES_PER_RUNTIME {
            continue;
        }
        entries.sort_by_key(|(_, finished)| *finished);
        let surplus = entries.len().saturating_sub(MAX_TERMINAL_ENTRIES_PER_RUNTIME);
        for (id, _) in entries.into_iter().take(surplus) {
            map.remove(&id);
        }
    }
}

#[tauri::command]
pub async fn open_session(
    app: AppHandle,
    runtime_id: String,
    session_id: String,
    agent: String,
    workspace: String,
    on_event: Channel<PtyEvent>,
) -> Result<SessionSnapshot, WorkbenchError> {
    if !is_uuid_v4(&runtime_id) {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_RUNTIME_ID"));
    }
    if !is_uuid_v4(&session_id) {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_SESSION_ID"));
    }
    if !AGENTS.contains(&agent.as_str()) {
        return Err(WorkbenchError::map_aisc("AISC_ERR_INVALID_AGENT"));
    }
    // Canonicalize before any spawn: the frontend raw string never becomes
    // Session identity (05 §4.1). Missing/unreadable workspace -> stable
    // workspace error, no child is started.
    let ws = canonical_workspace(&workspace)?;

    let reg = registry(&app);
    if !reg.accepting() {
        return Err(session_failed("shutdown in progress: new sessions rejected"));
    }

    // Reserve BEFORE spawn (03 §2.3.1): duplicate session_id fails pre-spawn.
    let generation = {
        let mut g = reg.lock()?;
        if g.contains_key(&session_id) {
            return Err(session_failed("session_id already open"));
        }
        sweep_terminal_entries(&mut g);
        let gen = reg.next_generation();
        g.insert(
            session_id.clone(),
            SessionEntry {
                session: None,
                signal: ExitSignal::new(),
                state: SessionState::Starting,
                exit: None,
                runtime_id: runtime_id.clone(),
                agent: agent.clone(),
                workspace: ws.clone(),
                generation: gen,
                close: None,
            },
        );
        gen
    };

    let pin = resolve_pin(&app)?;
    let argv = session_open_argv(&runtime_id, &session_id, &agent, &ws);

    let (event_tx, event_rx) = mpsc::channel::<PtyEvent>(EVENT_CHANNEL_CAP);
    let spawned = spawn_pty_session(&pin, argv, DEFAULT_COLS, DEFAULT_ROWS, event_tx);
    let (session, signal) = match spawned {
        Ok(pair) => pair,
        Err(e) => {
            // Roll back the reservation; wake any concurrent closer.
            let mut g = reg.lock()?;
            if let Some(en) = g.get_mut(&session_id) {
                if en.state == SessionState::Starting && en.session.is_none() {
                    if let Some(close) = en.close.take() {
                        close.set(SessionExit {
                            exit_code: None,
                            reason: REASON_USER_CLOSE.into(),
                            finished_at_ms: now_ms(),
                        });
                    }
                    g.remove(&session_id);
                }
            }
            return Err(e);
        }
    };

    // Commit Running, or roll back if the reservation was closed/removed while
    // the spawn was in flight (concurrent close, shutdown).
    enum CommitOutcome {
        Committed,
        Rollback(PtySession),
    }
    let outcome = {
        let mut g = reg.lock()?;
        match g.get_mut(&session_id) {
            Some(en) if en.state == SessionState::Starting && en.session.is_none() => {
                en.session = Some(session);
                en.signal = signal.clone();
                en.state = SessionState::Running;
                CommitOutcome::Committed
            }
            // Closing/removed: the closer owns the entry; we kill + reap the
            // child we just created and hand the result to the completion.
            _ => CommitOutcome::Rollback(session),
        }
    };

    let session = match outcome {
        CommitOutcome::Committed => None,
        CommitOutcome::Rollback(session) => Some(session),
    };
    if let Some(session) = session {
        // A closer is waiting on the shared completion: kill + reap.
        // Reservation was closed/removed mid-spawn: kill and reap the child we
        // just created; never leak it (03 §2.3.2).
        session.force_kill();
        let exit = signal
            .wait_timeout(CLOSE_FORCE_WAIT)
            .await
            .unwrap_or(SessionExit {
                exit_code: None,
                reason: REASON_TRANSPORT_ERROR.into(),
                finished_at_ms: now_ms(),
            });
        let mut g = reg.lock()?;
        if let Some(en) = g.get_mut(&session_id) {
            en.state = SessionState::Exited;
            en.exit = Some(exit.clone());
            if let Some(close) = en.close.take() {
                close.set(exit);
            }
        }
        return Err(session_failed("session closed while opening"));
    }

    // Bridge mpsc -> Tauri Channel (frontend receives Output/Exit events).
    tokio::spawn(async move {
        let mut rx = event_rx;
        while let Some(ev) = rx.recv().await {
            if on_event.send(ev).is_err() {
                break;
            }
        }
    });

    // Observer: update registry state/exit when the child exits on its own
    // (process_exit / transport_error) so close_session on an already-exited
    // session returns the cached exit.
    let reg_obs = reg.clone();
    let sig_obs = signal.clone();
    let sid_obs = session_id.clone();
    tokio::spawn(async move {
        let exit = sig_obs.wait().await;
        if let Ok(mut g) = reg_obs.lock() {
            if let Some(e) = g.get_mut(&sid_obs) {
                e.state = if exit.reason == REASON_TRANSPORT_ERROR {
                    SessionState::Disconnected
                } else {
                    SessionState::Exited
                };
                e.exit = Some(exit);
            }
        }
    });

    Ok(SessionSnapshot {
        session_id,
        runtime_id,
        agent,
        state: SessionState::Running,
        generation,
    })
}

#[tauri::command]
pub async fn write_session(
    app: AppHandle,
    session_id: String,
    bytes: Vec<u8>,
) -> Result<(), WorkbenchError> {
    if bytes.len() > MAX_WRITE_BYTES {
        return Err(WorkbenchError::input_too_large());
    }
    let sender = {
        let reg = registry(&app);
        let g = reg.lock()?;
        let entry = g
            .get(&session_id)
            .ok_or_else(|| WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND"))?;
        if entry.state != SessionState::Running {
            return Err(session_failed(format!("session state: {:?}", entry.state)));
        }
        entry.session.as_ref().ok_or_else(|| session_failed("session not running"))?.writer_sender()
    };
    sender
        .send(bytes)
        .await
        .map_err(|_| WorkbenchError::cli_protocol().with_detail("session writer closed"))
}

#[tauri::command]
pub async fn resize_session(
    app: AppHandle,
    session_id: String,
    cols: u16,
    rows: u16,
) -> Result<(), WorkbenchError> {
    if cols == 0 || rows == 0 {
        return Err(WorkbenchError::cli_protocol().with_detail("cols/rows must be > 0"));
    }
    let reg = registry(&app);
    let g = reg.lock()?;
    let entry = g
        .get(&session_id)
        .ok_or_else(|| WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND"))?;
    entry
        .session
        .as_ref()
        .ok_or_else(|| session_failed("session not running"))?
        .resize(cols, rows)
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AckResult {
    Acknowledged,
    AlreadyAcknowledged,
}

/// Natural-exit ack (03 §3.3): removes a terminal registry entry; idempotent
/// for already-deleted entries; live sessions return a stable error.
#[tauri::command]
pub async fn ack_session_exit(
    app: AppHandle,
    session_id: String,
) -> Result<AckResult, WorkbenchError> {
    let reg = registry(&app);
    let mut g = reg.lock()?;
    match g.get(&session_id) {
        None => Ok(AckResult::AlreadyAcknowledged),
        Some(en) if en.exit.is_some() => {
            g.remove(&session_id);
            sweep_terminal_entries(&mut g);
            Ok(AckResult::Acknowledged)
        }
        Some(_) => Err(session_failed("session is not in a terminal state")),
    }
}

/// Phase-1 close plan computed under the registry lock (03 §2.3.3-4):
/// - `Gone`: nothing to close.
/// - `Terminal`: cached exit returned and entry dropped (03 §3.3.4).
/// - `Run`: caller owns the close (session may be `None` for a Reserved entry
///   whose spawn is still in flight).
/// - `Wait`: a close is already in flight; share its completion.
enum ClosePlan {
    Terminal(SessionExit),
    Run {
        session: Option<PtySession>,
        signal: ExitSignal,
        close: Arc<ExitSignal>,
        runtime_id: String,
        workspace: String,
    },
    Wait(Arc<ExitSignal>),
    Gone,
}

fn plan_close(
    g: &mut HashMap<String, SessionEntry>,
    session_id: &str,
) -> ClosePlan {
    match g.get_mut(session_id) {
        None => ClosePlan::Gone,
        Some(en) if en.state == SessionState::Closing => {
            let close = en.close.clone().unwrap_or_else(|| {
                let c = Arc::new(ExitSignal::new());
                en.close = Some(Arc::clone(&c));
                c
            });
            ClosePlan::Wait(close)
        }
        Some(en) => {
            if let Some(exit) = en.exit.clone() {
                // Cached terminal exit: return it and drop the entry; a later
                // ack stays idempotent (03 §3.3.4).
                g.remove(session_id);
                ClosePlan::Terminal(exit)
            } else {
                en.state = SessionState::Closing;
                let close = Arc::new(ExitSignal::new());
                en.close = Some(Arc::clone(&close));
                ClosePlan::Run {
                    session: en.session.take(),
                    signal: en.signal.clone(),
                    close,
                    runtime_id: en.runtime_id.clone(),
                    workspace: en.workspace.clone(),
                }
            }
        }
    }
}

#[tauri::command]
pub async fn close_session(
    app: AppHandle,
    session_id: String,
) -> Result<SessionExit, WorkbenchError> {
    let reg = registry(&app);

    let slot = {
        let mut g = reg.lock()?;
        plan_close(&mut g, &session_id)
    };

    match slot {
        ClosePlan::Gone => Err(WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND")),
        ClosePlan::Terminal(exit) => Ok(exit),
        ClosePlan::Wait(close) => {
            // Concurrent close: await the shared completion, no second
            // terminate (03 §2.3.4).
            let deadline = CLOSE_WAIT + CLOSE_FORCE_WAIT + Duration::from_secs(1);
            close.wait_timeout(deadline).await.ok_or_else(|| {
                session_failed("close timed out while another close was in flight")
            })
        }
        ClosePlan::Run { session, signal, close, runtime_id, workspace } => {
            let exit = if let Some(session) = session {
                // §3.1: terminate (kill container agent) -> wait/reap local
                // child. cancel() sets the exit reason to user_close.
                session.cancel();
                let pin = resolve_pin(&app)?;
                let _ = run_control(
                    &pin,
                    session_terminate_argv(&runtime_id, &session_id, &workspace),
                    TERMINATE_TIMEOUT,
                    CancellationToken::new(),
                )
                .await; // best-effort; terminate is idempotent

                match signal.wait_timeout(CLOSE_WAIT).await {
                    Some(exit) => exit,
                    None => {
                        // Child didn't exit after terminate: force-kill + reap.
                        session.force_kill();
                        signal
                            .wait_timeout(CLOSE_FORCE_WAIT)
                            .await
                            .unwrap_or(SessionExit {
                                exit_code: None,
                                reason: REASON_TRANSPORT_ERROR.into(),
                                finished_at_ms: now_ms(),
                            })
                    }
                }
            } else {
                // Reserved entry: the spawn-in-flight path kills and reaps on
                // commit (03 §2.3.2); we wait for the shared completion.
                close.wait_timeout(CLOSE_WAIT).await.unwrap_or(SessionExit {
                    exit_code: None,
                    reason: REASON_USER_CLOSE.into(),
                    finished_at_ms: now_ms(),
                })
            };
            let mut g = reg.lock()?;
            if let Some(en) = g.get_mut(&session_id) {
                en.state = if exit.reason == REASON_TRANSPORT_ERROR {
                    SessionState::Disconnected
                } else {
                    SessionState::Exited
                };
                en.exit = Some(exit.clone());
            }
            close.set(exit.clone());
            sweep_terminal_entries(&mut g);
            Ok(exit)
        }
    }
}

/// Unified shutdown coordinator (03 §4.3): reject new sessions, close every
/// Reserved/Running/Closing session (shared completions), force-reap leftovers,
/// flush settings, and report what happened. Budgets are tightened in G-07
/// (Step 2); here every step is bounded by the per-close constants.
#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "snake_case")]
pub struct ShutdownReport {
    pub graceful_closed: usize,
    pub force_reaped: usize,
    pub terminate_timed_out: usize,
    pub reap_timed_out: usize,
    pub unreaped_session_ids: Vec<String>,
    pub flush_errors: Vec<String>,
}

#[tauri::command]
pub async fn shutdown_workbench(
    app: AppHandle,
    stop_runtime: bool,
) -> Result<ShutdownReport, WorkbenchError> {
    let reg = registry(&app);
    reg.reject_new();

    let ids: Vec<String> = {
        let g = reg.lock()?;
        g.keys().cloned().collect()
    };

    // Concurrent bounded close; each close_session path owns reap/force-kill.
    let mut handles = Vec::new();
    for id in &ids {
        let app = app.clone();
        let id = id.clone();
        handles.push(tokio::spawn(async move { close_session(app, id).await }));
    }
    let mut report = ShutdownReport::default();
    for h in handles {
        match h.await {
            Ok(Ok(_)) => report.graceful_closed += 1,
            Ok(Err(_)) => report.terminate_timed_out += 1,
            Err(_) => report.terminate_timed_out += 1,
        }
    }

    // Force-reap any leftover live children (03 §4.3: force-reap leftovers).
    let mut leftover: Vec<String> = {
        let g = reg.lock()?;
        g.iter()
            .filter(|(_, e)| e.session.is_some() && e.exit.is_none())
            .map(|(k, _)| k.clone())
            .collect()
    };
    for id in &leftover {
        {
            let mut g = reg.lock()?;
            if let Some(en) = g.get_mut(id) {
                if let Some(s) = en.session.take() {
                    s.force_kill();
                }
            }
        }
        let _ = tokio::time::timeout(CLOSE_FORCE_WAIT, async {
            let reg = reg.clone();
            loop {
                let done = {
                    let g = reg.lock()?;
                    g.get(id).map(|e| e.exit.is_some()).unwrap_or(true)
                };
                if done {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Ok::<(), WorkbenchError>(())
        })
        .await;
    }
    // Reap wait is the force path; anything still alive is unreaped.
    let still_alive: Vec<String> = {
        let g = reg.lock()?;
        g.iter()
            .filter(|(_, e)| e.session.is_some() || !is_terminal(e.state))
            .map(|(k, _)| k.clone())
            .collect()
    };
    if still_alive.is_empty() {
        report.force_reaped = leftover.len();
    } else {
        report.reap_timed_out = still_alive.len();
        report.unreaped_session_ids = still_alive;
    }

    // Flush settings (pin) so no dirty state is left behind (03 §4.3).
    if let Ok(dir) = config_dir(&app) {
        match Settings::load(&dir).and_then(|s| s.save(&dir)) {
            Ok(()) => {}
            Err(e) => report.flush_errors.push(e.to_string()),
        }
    }

    let _ = stop_runtime; // runtime stop lands in G-07 (Step 2)
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pty::REASON_PROCESS_EXIT;
    use tempfile::tempdir;

    #[test]
    fn uuid_v4_validation() {
        assert!(is_uuid_v4("0e7b7e3b-5c97-4d20-9292-bca647cc940a"));
        assert!(!is_uuid_v4("0e7b7e3b-5c97-3d20-9292-bca647cc940a")); // v3
        assert!(!is_uuid_v4("0e7b7e3b-5c97-4d20-9292-bca647cc940")); // short
        assert!(!is_uuid_v4("0e7b7e3b5c974d209292bca647cc940a")); // no dashes
        assert!(!is_uuid_v4("0e7b7e3b-5c97-4d20-9292-bca647cc940g")); // non-hex
        assert!(!is_uuid_v4("0e7b7e3b-5c97-4d20-c292-bca647cc940a")); // bad variant
    }

    #[test]
    fn agent_validation() {
        for a in ["claude", "codex", "bash", "cc-switch"] {
            assert!(AGENTS.contains(&a));
        }
        assert!(!AGENTS.contains(&"python"));
    }

    #[test]
    fn open_argv_is_text_only_no_format() {
        let argv = session_open_argv("rid", "sid", "bash", "/ws");
        assert_eq!(argv[0], "session");
        assert_eq!(argv[1], "open");
        assert!(argv.contains(&"--agent".into()));
        assert!(!argv.iter().any(|a| a == "--format"));
    }

    #[test]
    fn open_argv_includes_canonical_workspace() {
        let argv = session_open_argv("rid", "sid", "bash", "C:/ws");
        let i = argv.iter().position(|a| a == "--workspace").unwrap();
        assert_eq!(argv[i + 1], "C:/ws");
    }

    #[test]
    fn terminate_argv_includes_format_json_workspace_and_grace3() {
        let argv = session_terminate_argv("rid", "sid", "/ws");
        assert_eq!(argv[1], "terminate");
        assert!(argv.contains(&"--format".into()));
        assert!(argv.contains(&"json".into()));
        let i = argv.iter().position(|a| a == "--workspace").unwrap();
        assert_eq!(argv[i + 1], "/ws");
        // Workbench fast path always uses --grace 3 (03 §4.1 / 05 §4.2).
        let g = argv.iter().position(|a| a == "--grace").unwrap();
        assert_eq!(argv[g + 1], "3");
    }

    #[test]
    fn g07_budgets_match_contract() {
        // 03 §4.1: terminate budget 5s, close wait 4s, force reap 2s.
        assert_eq!(TERMINATE_TIMEOUT, Duration::from_secs(5));
        assert_eq!(CLOSE_WAIT, Duration::from_secs(4));
        assert_eq!(CLOSE_FORCE_WAIT, Duration::from_secs(2));
    }

    #[test]
    fn canonical_workspace_resolves_absolute_path() {
        let dir = tempdir().unwrap();
        let ws = canonical_workspace(dir.path().to_str().unwrap()).unwrap();
        assert_eq!(ws, std::fs::canonicalize(dir.path()).unwrap().to_string_lossy());
    }

    #[test]
    fn canonical_workspace_rejects_missing_path() {
        let err = canonical_workspace("Z:/definitely/not/a/real/workspace-9f3a").unwrap_err();
        assert_eq!(err.code, "AISC_ERR_WORKSPACE_INVALID");
    }

    fn terminal_entry(runtime_id: &str, finished_at_ms: i64) -> SessionEntry {
        SessionEntry {
            session: None,
            signal: ExitSignal::new(),
            state: SessionState::Exited,
            exit: Some(SessionExit {
                exit_code: Some(0),
                reason: REASON_PROCESS_EXIT.into(),
                finished_at_ms,
            }),
            runtime_id: runtime_id.into(),
            agent: "bash".into(),
            workspace: "/ws".into(),
            generation: 0,
            close: None,
        }
    }

    fn live_entry(runtime_id: &str, workspace: &str) -> SessionEntry {
        SessionEntry {
            session: None,
            signal: ExitSignal::new(),
            state: SessionState::Running,
            exit: None,
            runtime_id: runtime_id.into(),
            agent: "bash".into(),
            workspace: workspace.into(),
            generation: 0,
            close: None,
        }
    }

    #[test]
    fn sweep_removes_expired_terminal_entries() {
        let mut map = HashMap::new();
        map.insert("old".into(), terminal_entry("r1", now_ms() - 61_000));
        map.insert("fresh".into(), terminal_entry("r1", now_ms() - 1_000));
        map.insert("live".into(), live_entry("r1", "/ws"));
        sweep_terminal_entries(&mut map);
        assert!(!map.contains_key("old"));
        assert!(map.contains_key("fresh"));
        assert!(map.contains_key("live"));
    }

    #[test]
    fn sweep_caps_terminal_entries_per_runtime() {
        let mut map = HashMap::new();
        for i in 0..(MAX_TERMINAL_ENTRIES_PER_RUNTIME + 5) {
            map.insert(
                format!("s{i}"),
                terminal_entry("r1", now_ms() - 10_000 + i as i64),
            );
        }
        map.insert("other".into(), terminal_entry("r2", now_ms() - 5));
        sweep_terminal_entries(&mut map);
        let r1_count = map.values().filter(|e| e.runtime_id == "r1").count();
        assert_eq!(r1_count, MAX_TERMINAL_ENTRIES_PER_RUNTIME);
        assert!(map.contains_key("other"));
        // Oldest entries were evicted.
        assert!(!map.contains_key("s0"));
        assert!(!map.contains_key("s4"));
    }

    #[test]
    fn close_plan_missing_is_gone() {
        let mut map = HashMap::new();
        assert!(matches!(plan_close(&mut map, "ghost"), ClosePlan::Gone));
    }

    #[test]
    fn close_plan_terminal_returns_cached_exit_and_removes_entry() {
        let mut map = HashMap::new();
        map.insert("s1".into(), terminal_entry("r1", now_ms()));
        let plan = plan_close(&mut map, "s1");
        match plan {
            ClosePlan::Terminal(exit) => assert_eq!(exit.exit_code, Some(0)),
            _ => panic!("expected Terminal"),
        }
        assert!(!map.contains_key("s1"));
    }

    #[test]
    fn close_plan_running_takes_session_and_marks_closing() {
        let mut map = HashMap::new();
        map.insert("s1".into(), live_entry("r1", "/ws"));
        let plan = plan_close(&mut map, "s1");
        match plan {
            ClosePlan::Run { session, workspace, .. } => {
                assert!(session.is_none()); // live_entry has no PtySession
                assert_eq!(workspace, "/ws");
            }
            _ => panic!("expected Run"),
        }
        let en = map.get("s1").unwrap();
        assert_eq!(en.state, SessionState::Closing);
        assert!(en.session.is_none());
        assert!(en.close.is_some());
    }

    #[test]
    fn close_plan_concurrent_close_shares_completion() {
        let mut map = HashMap::new();
        map.insert("s1".into(), live_entry("r1", "/ws"));
        // First close takes the Run slot and installs a completion.
        let first = plan_close(&mut map, "s1");
        let first_close = match &first {
            ClosePlan::Run { close, .. } => Arc::clone(close),
            _ => panic!("expected Run"),
        };
        // Second close on the same entry must Wait on the SAME completion.
        let second = plan_close(&mut map, "s1");
        match second {
            ClosePlan::Wait(close) => {
                assert!(Arc::ptr_eq(&first_close, &close));
            }
            _ => panic!("expected Wait"),
        }
    }

    #[test]
    fn close_plan_reserved_entry_is_run_without_session() {
        let mut map = HashMap::new();
        map.insert(
            "s1".into(),
            SessionEntry {
                session: None,
                signal: ExitSignal::new(),
                state: SessionState::Starting,
                exit: None,
                runtime_id: "r1".into(),
                agent: "bash".into(),
                workspace: "/ws".into(),
                generation: 1,
                close: None,
            },
        );
        let plan = plan_close(&mut map, "s1");
        match plan {
            ClosePlan::Run { session, .. } => assert!(session.is_none()),
            _ => panic!("expected Run"),
        }
        assert_eq!(map.get("s1").unwrap().state, SessionState::Closing);
    }

    #[test]
    fn registry_generation_is_monotonic() {
        let reg = SessionRegistry::default();
        let a = reg.next_generation();
        let b = reg.next_generation();
        assert_eq!(b, a + 1);
    }

    #[test]
    fn registry_reject_new_gates_accepting() {
        let reg = SessionRegistry::default();
        assert!(reg.accepting());
        reg.reject_new();
        assert!(!reg.accepting());
    }

    #[test]
    fn snapshot_serializes_camel_case() {
        let s = SessionSnapshot {
            session_id: "sid".into(),
            runtime_id: "rid".into(),
            agent: "bash".into(),
            state: SessionState::Running,
            generation: 3,
        };
        let json = serde_json::to_string(&s).unwrap();
        assert!(json.contains(r#""sessionId":"sid""#));
        assert!(json.contains(r#""runtimeId":"rid""#));
        assert!(json.contains(r#""state":"running""#));
        assert!(json.contains(r#""generation":3"#));
    }
}
