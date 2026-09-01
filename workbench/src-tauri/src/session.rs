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

use serde::{Deserialize, Serialize};
use tauri::{ipc::Channel, AppHandle, Manager};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::cli::run_control;
use crate::error::WorkbenchError;
use crate::pty::{
    spawn_pipe_session, now_ms, ExitSignal, PtyEvent, PtySession, SessionExit, SessionState,
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
/// Shutdown coordinator budget (03 §4.3): graceful close 6s, force-reap 2s,
/// flush 1s, total hard deadline 12s. All internal waits read the shared
/// remaining deadline instead of stacking per-session timeouts.
const SHUTDOWN_GRACEFUL: Duration = Duration::from_secs(6);
const SHUTDOWN_FORCE: Duration = Duration::from_secs(2);
const SHUTDOWN_FLUSH: Duration = Duration::from_secs(1);
const SHUTDOWN_TOTAL: Duration = Duration::from_secs(12);
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
    // Stage 7 (DATA-04): app state lives under <data-root>/config; the
    // legacy Tauri app_config_dir is the adoption source / fallback.
    let legacy = app.path().app_config_dir().ok();
    Ok(crate::data_root::app_state_dir(legacy.as_deref()))
}

pub fn resolve_pin(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    let dir = config_dir(app)?;
    let settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    pinned_cli(&settings).ok_or_else(WorkbenchError::cli_not_found)
}

/// The saved pin, but only while its file actually exists. KI-3 round 3
/// (2026-08-18): uninstalling the installed Workbench deletes its sidecar
/// `aisc.exe` while settings survive in the shared data root — a pin pointing
/// at the deleted exe then poisons every CLI call (negotiate + commands all
/// spawn a nonexistent binary). A pin whose file is gone is treated as no pin
/// at all, so callers fall through to auto-discovery which re-pins a live
/// candidate. Existence-only check (`is_file`): cheap, no subprocess; a
/// present-but-broken pin still surfaces through the normal validate path.
pub(crate) fn pinned_cli(settings: &Settings) -> Option<PathBuf> {
    settings
        .aisc_cli_path()
        .map(PathBuf::from)
        .filter(|p| p.is_file())
}

/// Resolve the CLI for a command invocation. KI-3 round 2 (2026-08-18): the
/// pin may not exist yet — negotiate is DEFERRED during the onboarding
/// wizard, and the wizard env probe / post-wizard preflight resolved through
/// `resolve_pin`, failed with a bare cli_not_found (recovers once negotiate
/// writes the pin). This wrapper auto-selects and PERSISTS a candidate when
/// the pin is absent (same selection negotiate makes), so no CLI consumer can
/// lose that race. Round 3: `resolve_pin` now also fails on a STALE pin
/// (pinned file deleted by uninstall/upgrade), so the same fallback re-heals
/// it. Use from async commands.
pub async fn resolve_cli(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    match resolve_pin(app) {
        Ok(pin) => Ok(pin),
        Err(_) => {
            // lifecycle-logging: pre-spawn resolution failure — without this
            // line a "无法沟通 aisc CLI" state (stale pin + zero valid
            // candidates) would leave the timeline completely silent, since
            // the op logging lives inside run_control which is never reached.
            let outcome = crate::cli::auto_select_and_pin(app).await;
            match &outcome {
                Err(e) => {
                    crate::logging::append_event(
                        "error", "app", "cli_resolve_failed", None,
                        serde_json::json!({
                            "error_code": e.code,
                            "detail": e.technical_detail.as_deref().unwrap_or(""),
                        }),
                    );
                }
                Ok(path) => {
                    // The KI-3 self-heal fired: a stale/deleted pin was
                    // re-resolved. Say so on the timeline — the settings file
                    // silently changing back is otherwise indistinguishable
                    // from "nothing happened".
                    crate::logging::append_event(
                        "info", "app", "cli_pin_healed", None,
                        serde_json::json!({ "pin": path.display().to_string() }),
                    );
                }
            }
            outcome
        }
    }
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
    resume_conversation_id: Option<&str>,
) -> Vec<String> {
    let mut argv = vec![
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
    ];
    // v2.1.8 T4 (design §1f): the wrapper converts this to the provider
    // resume form (claude --resume <id> / codex resume <id>).
    if let Some(id) = resume_conversation_id {
        argv.push("--resume-id".into());
        argv.push(id.into());
    }
    argv
}

/// v2.1.8 T4: resume pre-validation (design §1c/§1f). Pure so the unit
/// tests cover it without an AppHandle. The conversation id is provider-
/// native — any RFC-4122 version is accepted (D-5: Codex ships UUIDv7).
fn validate_resume(
    agent: &str,
    resume_conversation_id: Option<&str>,
) -> Result<(), WorkbenchError> {
    if let Some(id) = resume_conversation_id {
        if !crate::conversation::is_conversation_uuid(id) {
            return Err(WorkbenchError::map_aisc("AISC_ERR_CONVERSATION_INVALID_ID"));
        }
        if agent != "claude" && agent != "codex" {
            return Err(WorkbenchError::map_aisc("AISC_ERR_CONVERSATION_INVALID_AGENT"));
        }
    }
    Ok(())
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
    resume_conversation_id: Option<String>,
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
    validate_resume(&agent, resume_conversation_id.as_deref())?;
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

    let pin = resolve_cli(&app).await?;
    let argv =
        session_open_argv(&runtime_id, &session_id, &agent, &ws, resume_conversation_id.as_deref());

    let (event_tx, event_rx) = mpsc::channel::<PtyEvent>(EVENT_CHANNEL_CAP);
    let spawned = spawn_pipe_session(&pin, argv, DEFAULT_COLS, DEFAULT_ROWS, event_tx);
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
    let agent_obs = agent.clone();
    tokio::spawn(async move {
        let exit = sig_obs.wait().await;
        // 2.1.9 hotfix (nairong #61): session open/exit used to be the ONE
        // app path with zero log trail (spawn bypasses run_control, and the
        // sidecar's stderr was nulled) — a dying session left no evidence
        // anywhere. Land every terminal transition in the app log.
        let clean = exit.reason == REASON_USER_CLOSE
            || (exit.reason == "process_exit" && exit.exit_code == Some(0));
        crate::logging::append_event(
            if clean { "info" } else { "error" },
            "app",
            "session_exit",
            None,
            serde_json::json!({
                "session_id": sid_obs.as_str(),
                "agent": agent_obs.as_str(),
                "reason": exit.reason.as_str(),
                "exit_code": exit.exit_code,
            }),
        );
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
                let pin = resolve_cli(&app).await?;
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
    /// runtime-lifecycle-ux Stage 2 (02 §4): per-runtime cleanup outcome.
    /// Empty on the legacy sessions-only path.
    #[serde(default)]
    pub runtime_cleanup: Vec<RuntimeCleanup>,
}

/// One workspace's runtime target in a structured shutdown request
/// (runtime-lifecycle-ux 02 §4). `retention` follows the registry metadata
/// policy: remove_on_close (default) | keep_stopped | keep_running.
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShutdownTarget {
    pub workspace: String,
    pub runtime_id: String,
    #[serde(default = "default_retention")]
    pub retention: String,
}

fn default_retention() -> String {
    "remove_on_close".to_string()
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShutdownRequest {
    pub workspaces: Vec<ShutdownTarget>,
    pub reason: String, // window_close | tray_exit | app_exit
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub struct RuntimeCleanup {
    pub workspace: String,
    pub runtime_id: String,
    pub action: String, // removed | kept | skipped | failed
    pub state: String,  // stopped | not_found | unknown
    pub error_code: Option<String>,
}

/// Legacy sessions-only shutdown (G-07 shape). The `stop_runtime` flag was
/// never wired (runtime stop lands in G-07 Step 2 — superseded by the
/// structured v2 below); the frontend migrates onto v2 in
/// runtime-lifecycle-ux Stage 3, after which this wrapper can go.
#[tauri::command]
pub async fn shutdown_workbench(
    app: AppHandle,
    stop_runtime: bool,
) -> Result<ShutdownReport, WorkbenchError> {
    let _ = stop_runtime;
    run_shutdown(app, None).await
}

/// Structured shutdown (runtime-lifecycle-ux 02 §4): sessions first, then
/// per-runtime stop→remove honoring each target's retention, then lease
/// release, then flush. One runtime's failure never blocks the others;
/// per-target budget caps a hung Docker CLI call.
#[tauri::command]
pub async fn shutdown_workbench_v2(
    app: AppHandle,
    request: ShutdownRequest,
) -> Result<ShutdownReport, WorkbenchError> {
    run_shutdown(app, Some(request)).await
}

/// Budget for one runtime's stop+remove during shutdown (02 §4: cleanup
/// timeout must not block exit forever; leftovers reconcile next start).
const RUNTIME_CLEANUP_TIMEOUT: Duration = Duration::from_secs(45);

async fn run_shutdown(
    app: AppHandle,
    request: Option<ShutdownRequest>,
) -> Result<ShutdownReport, WorkbenchError> {
    let reg = registry(&app);
    reg.reject_new();

    // G-07 (2026-08-09): hide the window first so the close feels instant.
    // The webview's own hide() IPC does not take effect while a close request
    // is pending on this Tauri version - hiding here is a direct win32 call
    // that works regardless; the process exits at the end of this function.
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.hide();
    }

    let ids: Vec<String> = {
        let g = reg.lock()?;
        g.keys().cloned().collect()
    };

    // Concurrent bounded close (03 §4.3): all closes share the 6s graceful
    // window; anything still running when it expires is cancelled and the
    // force-reap phase takes over. A cancelled close that was mid-terminate
    // is counted as terminate_timed_out; the child is force-reaped next.
    let mut handles = Vec::new();
    for id in &ids {
        let app = app.clone();
        let id = id.clone();
        handles.push(tokio::spawn(async move { close_session(app, id).await }));
    }
    let mut report = ShutdownReport::default();
    let mut completed = 0usize;
    let graceful_deadline = tokio::time::Instant::now() + SHUTDOWN_GRACEFUL;
    for h in &mut handles {
        let remaining = graceful_deadline.saturating_duration_since(tokio::time::Instant::now());
        match tokio::time::timeout(remaining, &mut *h).await {
            Ok(Ok(Ok(_))) => completed += 1,
            Ok(Ok(Err(_))) => report.terminate_timed_out += 1,
            // Window expired (or task panicked): cancel; child is force-reaped.
            _ => {
                h.abort();
                report.terminate_timed_out += 1;
            }
        }
    }
    report.graceful_closed = completed;

    // Force-reap any leftover live children (03 §4.3): kill everything up
    // front, then wait for the reaps inside one shared 2s window.
    let leftover: Vec<String> = {
        let g = reg.lock()?;
        g.iter()
            .filter(|(_, e)| e.session.is_some() && e.exit.is_none())
            .map(|(k, _)| k.clone())
            .collect()
    };
    for id in &leftover {
        let mut g = reg.lock()?;
        if let Some(en) = g.get_mut(id) {
            if let Some(s) = en.session.take() {
                s.force_kill();
            }
        }
    }
    let mut waiters = Vec::new();
    for id in &leftover {
        let reg = reg.clone();
        let id = id.clone();
        waiters.push(tokio::spawn(async move {
            loop {
                let done = {
                    let g = reg.lock()?;
                    g.get(&id).map(|e| e.exit.is_some()).unwrap_or(true)
                };
                if done {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Ok::<(), WorkbenchError>(())
        }));
    }
    let _ = tokio::time::timeout(SHUTDOWN_FORCE, async {
        for w in waiters {
            let _ = w.await;
        }
    })
    .await;
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

    // runtime-lifecycle-ux Stage 2 (02 §4): AFTER session cleanup, BEFORE
    // flush — per-runtime stop→remove under each target's retention, then
    // release every lease this process holds. Targets run concurrently with
    // a per-target budget; a failure or timeout lands in the report and
    // next-startup reconcile sweeps the remainder.
    if let Some(req) = &request {
        report.runtime_cleanup = runtime_cleanup_phase(&app, req).await;
        release_all_leases(&app).await;
    }

    // Flush settings (pin) so no dirty state is left behind (03 §4.3).
    if let Ok(dir) = config_dir(&app) {
        match Settings::load(&dir).and_then(|s| s.save(&dir)) {
            Ok(()) => {}
            Err(e) => report.flush_errors.push(e.to_string()),
        }
    }

    // G-07 refinement (2026-08-09): the frontend hides the window before
    // invoking this command, so the user sees an instant close while cleanup
    // continues here. Once done, exit the process - nothing may linger
    // invisibly. Sessions that refused to die within the budgets are logged
    // and dropped; the runtime container keeps running either way (by design;
    // v2 requests additionally remove containers per retention above).
    eprintln!(
        "[shutdown] closed={} force_reaped={} terminate_timed_out={} reap_timed_out={} unreaped={} flush_errors={} runtime_cleanup={}",
        report.graceful_closed,
        report.force_reaped,
        report.terminate_timed_out,
        report.reap_timed_out,
        report.unreaped_session_ids.len(),
        report.flush_errors.len(),
        report
            .runtime_cleanup
            .iter()
            .map(|c| format!("{}/{}/{}", c.runtime_id, c.action, c.state))
            .collect::<Vec<_>>()
            .join(",")
    );
    app.exit(0);
    Ok(report)
}

/// Concurrent per-target runtime cleanup (runtime-lifecycle-ux 02 §4):
/// stop → (unless keep_stopped) remove. Same-runtime serialization rides
/// the existing per-runtime op mutex inside stop/remove; cross-process
/// safety rides the CLI's workspace/maintenance locks.
async fn runtime_cleanup_phase(app: &AppHandle, request: &ShutdownRequest) -> Vec<RuntimeCleanup> {
    let mut handles = Vec::new();
    for target in &request.workspaces {
        let app = app.clone();
        let target = target.clone();
        handles.push(tokio::spawn(async move {
            match tokio::time::timeout(
                RUNTIME_CLEANUP_TIMEOUT,
                cleanup_one_runtime(&app, &target),
            )
            .await
            {
                Ok(entry) => entry,
                Err(_) => RuntimeCleanup {
                    workspace: target.workspace,
                    runtime_id: target.runtime_id,
                    action: "failed".into(),
                    state: "unknown".into(),
                    error_code: Some("AISC_ERR_RUNTIME_RECONCILE_FAILED".into()),
                },
            }
        }));
    }
    let mut out = Vec::new();
    for h in handles {
        if let Ok(entry) = h.await {
            out.push(entry);
        }
    }
    out
}

async fn cleanup_one_runtime(app: &AppHandle, target: &ShutdownTarget) -> RuntimeCleanup {
    use crate::runtime::{remove_runtime, stop_runtime};

    if target.retention == "keep_running" {
        return RuntimeCleanup {
            workspace: target.workspace.clone(),
            runtime_id: target.runtime_id.clone(),
            action: "skipped".into(),
            state: "unknown".into(),
            error_code: None,
        };
    }

    // Stop (idempotent; a not_found runtime surfaces as an error whose code
    // we keep for classification).
    let stop = stop_runtime(
        app.clone(),
        target.runtime_id.clone(),
        target.workspace.clone(),
    )
    .await;
    if target.retention == "keep_stopped" {
        return match stop {
            Ok(snap) => RuntimeCleanup {
                workspace: target.workspace.clone(),
                runtime_id: target.runtime_id.clone(),
                action: "kept".into(),
                state: normalize_state(&snap.state),
                error_code: None,
            },
            Err(e) => RuntimeCleanup {
                workspace: target.workspace.clone(),
                runtime_id: target.runtime_id.clone(),
                action: "failed".into(),
                state: "unknown".into(),
                error_code: Some(e.code),
            },
        };
    }

    let remove = remove_runtime(
        app.clone(),
        target.runtime_id.clone(),
        target.workspace.clone(),
        true, // stopped above (or already gone) — force covers a racing start
    )
    .await;
    match remove {
        Ok(snap) => RuntimeCleanup {
            workspace: target.workspace.clone(),
            runtime_id: target.runtime_id.clone(),
            action: "removed".into(),
            state: normalize_state(&snap.state),
            error_code: None,
        },
        Err(e) => RuntimeCleanup {
            workspace: target.workspace.clone(),
            runtime_id: target.runtime_id.clone(),
            action: "failed".into(),
            state: "unknown".into(),
            error_code: Some(e.code),
        },
    }
}

/// Map a CLI snapshot state onto the report's three-state vocabulary
/// (02 §4): not_found stays; stopped-ish states collapse to stopped;
/// anything else (starting/unknown/…) reports unknown.
fn normalize_state(state: &str) -> String {
    match state {
        "not_found" => "not_found".into(),
        "stopped" | "stopping" | "removing" => "stopped".into(),
        _ => "unknown".into(),
    }
}

/// Release every lease this process holds (best-effort — an un-released
/// lease expires by TTL in 45s, which is the designed safety net, so a
/// failure here never blocks exit).
async fn release_all_leases(app: &AppHandle) {
    let workspaces = app
        .state::<crate::lease::LeaseSupervisor>()
        .active_workspaces();
    for ws in workspaces {
        if let Err(e) = crate::lease::lease_release(app.clone(), ws.clone()).await {
            eprintln!("[shutdown] lease release failed for {}: {}", ws, e.code);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pty::REASON_PROCESS_EXIT;
    use tempfile::tempdir;

    #[test]
    fn pinned_cli_requires_existing_file() {
        // KI-3 round 3: a pin is only a pin while its file exists — uninstall
        // deletes the exe but the shared-data-root settings survive.
        let dir = tempdir().unwrap();
        let live = dir.path().join("aisc.exe");
        std::fs::write(&live, b"").unwrap();

        let mut present = Settings::default();
        present.set_aisc_cli_path(Some(live.to_str().unwrap()));
        assert_eq!(pinned_cli(&present), Some(live));

        let mut stale = Settings::default();
        stale.set_aisc_cli_path(Some(
            dir.path().join("uninstalled-gone.exe").to_str().unwrap(),
        ));
        assert_eq!(pinned_cli(&stale), None);

        assert_eq!(pinned_cli(&Settings::default()), None); // never pinned
    }

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
        let argv = session_open_argv("rid", "sid", "bash", "/ws", None);
        assert_eq!(argv[0], "session");
        assert_eq!(argv[1], "open");
        assert!(argv.contains(&"--agent".into()));
        assert!(!argv.iter().any(|a| a == "--format"));
        assert!(!argv.iter().any(|a| a == "--resume-id"));
    }

    #[test]
    fn open_argv_includes_canonical_workspace() {
        let argv = session_open_argv("rid", "sid", "bash", "C:/ws", None);
        let i = argv.iter().position(|a| a == "--workspace").unwrap();
        assert_eq!(argv[i + 1], "C:/ws");
    }

    #[test]
    fn open_argv_appends_resume_id() {
        // v2.1.8 T4: a resume conversation id rides at the END of the argv.
        let argv = session_open_argv(
            "rid",
            "sid",
            "claude",
            "/ws",
            Some("24b70882-2d45-4cec-a9e2-66f8c012481f"),
        );
        let i = argv.iter().position(|a| a == "--resume-id").unwrap();
        assert_eq!(argv[i + 1], "24b70882-2d45-4cec-a9e2-66f8c012481f");
        assert_eq!(argv.last().unwrap(), "24b70882-2d45-4cec-a9e2-66f8c012481f");
    }

    #[test]
    fn validate_resume_accepts_v7_codex_and_rejects_garbage() {
        // D-5: Codex ids are UUIDv7 — accepted; garbage is not.
        assert!(validate_resume("codex", Some("01a04ca9-d3f6-7021-b9e7-50d48d818c65")).is_ok());
        assert!(validate_resume("claude", Some("24b70882-2d45-4cec-a9e2-66f8c012481f")).is_ok());
        assert!(validate_resume("claude", Some("not-a-uuid")).is_err());
        assert!(validate_resume("claude", None).is_ok());
    }

    #[test]
    fn validate_resume_rejects_non_provider_agents() {
        assert!(validate_resume("bash", Some("24b70882-2d45-4cec-a9e2-66f8c012481f")).is_err());
        assert!(validate_resume("cc-switch", Some("24b70882-2d45-4cec-a9e2-66f8c012481f"))
            .is_err());
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

    // --- runtime-lifecycle-ux Stage 2: structured shutdown (02 §4) ---------

    #[test]
    fn shutdown_request_decodes_camel_case_and_defaults_retention() {
        let req: ShutdownRequest = serde_json::from_str(
            r#"{"workspaces":[{"workspace":"C:\\ws","runtimeId":"rid-1"},
                            {"workspace":"C:\w2","runtimeId":"rid-2",
                             "retention":"keep_stopped"}],
               "reason":"window_close"}"#,
        )
        .unwrap();
        assert_eq!(req.reason, "window_close");
        assert_eq!(req.workspaces.len(), 2);
        assert_eq!(req.workspaces[0].retention, "remove_on_close"); // default
        assert_eq!(req.workspaces[1].retention, "keep_stopped");
    }

    #[test]
    fn runtime_cleanup_report_serializes_snake_case() {
        let entry = RuntimeCleanup {
            workspace: "C:\\ws".into(),
            runtime_id: "rid-1".into(),
            action: "removed".into(),
            state: "not_found".into(),
            error_code: None,
        };
        let json = serde_json::to_string(&entry).unwrap();
        assert!(json.contains(r#""runtime_id":"rid-1""#));
        assert!(json.contains(r#""error_code":null"#));
        // The legacy report keeps its shape + gains the (defaulted) field.
        let report = ShutdownReport::default();
        let json = serde_json::to_string(&report).unwrap();
        assert!(json.contains(r#""runtime_cleanup":[]"#));
    }

    #[test]
    fn normalize_state_maps_the_report_vocabulary() {
        assert_eq!(normalize_state("not_found"), "not_found");
        assert_eq!(normalize_state("stopped"), "stopped");
        assert_eq!(normalize_state("stopping"), "stopped");
        assert_eq!(normalize_state("removing"), "stopped");
        assert_eq!(normalize_state("running"), "unknown");
        assert_eq!(normalize_state("starting"), "unknown");
        assert_eq!(normalize_state("unknown"), "unknown");
    }
    }
}
