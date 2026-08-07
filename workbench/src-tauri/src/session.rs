//! Session data-plane Tauri commands + registry. Wraps `pty.rs` core with
//! AISC session semantics (runtime_id/session_id/agent, terminate-on-close).
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §6.1 (session open argv, text-only TTY),
//!   §9.2 (per-Session handles, byte chunks + seq, paste cap)
//! - 03-lifecycle-contract.md §五 (state machine), §七.1 (close order),
//!   §十 (domain API: open/write/resize/close_session)

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{ipc::Channel, AppHandle, Manager};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::cli::run_control;
use crate::error::WorkbenchError;
use crate::pty::{
    spawn_pty_session, now_ms, ExitSignal, PtyEvent, PtySession, SessionExit, SessionState,
    REASON_TRANSPORT_ERROR,
};
use crate::settings::Settings;

const DEFAULT_COLS: u16 = 80;
const DEFAULT_ROWS: u16 = 24;
const MAX_WRITE_BYTES: usize = 1024 * 1024; // 1 MB paste cap (05 §9.2)
const TERMINATE_TIMEOUT: Duration = Duration::from_secs(15);
const CLOSE_WAIT: Duration = Duration::from_secs(10);
const CLOSE_FORCE_WAIT: Duration = Duration::from_secs(2);
const EVENT_CHANNEL_CAP: usize = 256;

const AGENTS: &[&str] = &["claude", "codex", "bash", "cc-switch"];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionSnapshot {
    pub session_id: String,
    pub runtime_id: String,
    pub agent: String,
    pub state: SessionState,
}

pub struct SessionEntry {
    pub session: PtySession,
    pub signal: ExitSignal,
    pub state: SessionState,
    pub exit: Option<SessionExit>,
    pub runtime_id: String,
    pub agent: String,
}

/// Managed Tauri state: `session_id -> SessionEntry`.
pub type SessionRegistry = Arc<Mutex<HashMap<String, SessionEntry>>>;

fn registry(app: &AppHandle) -> Arc<Mutex<HashMap<String, SessionEntry>>> {
    app.state::<SessionRegistry>().inner().clone()
}

fn config_dir(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    app.path()
        .app_config_dir()
        .map_err(|e| WorkbenchError::settings_error().with_detail(format!("config dir: {e}")))
}

fn resolve_pin(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
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

fn session_open_argv(runtime_id: &str, session_id: &str, agent: &str) -> Vec<String> {
    vec![
        "session".into(),
        "open".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--session-id".into(),
        session_id.into(),
        "--agent".into(),
        agent.into(),
    ]
}

fn session_terminate_argv(runtime_id: &str, session_id: &str) -> Vec<String> {
    vec![
        "session".into(),
        "terminate".into(),
        "--runtime-id".into(),
        runtime_id.into(),
        "--session-id".into(),
        session_id.into(),
        "--format".into(),
        "json".into(),
    ]
}

#[tauri::command]
pub async fn open_session(
    app: AppHandle,
    runtime_id: String,
    session_id: String,
    agent: String,
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

    let pin = resolve_pin(&app)?;
    let argv = session_open_argv(&runtime_id, &session_id, &agent);

    let (event_tx, event_rx) = mpsc::channel::<PtyEvent>(EVENT_CHANNEL_CAP);
    let (session, signal) = spawn_pty_session(&pin, argv, DEFAULT_COLS, DEFAULT_ROWS, event_tx)?;

    let reg = registry(&app);
    {
        let mut g = reg.lock().map_err(|_| WorkbenchError::cli_protocol().with_detail("registry lock"))?;
        if g.contains_key(&session_id) {
            return Err(WorkbenchError::map_aisc("AISC_ERR_SESSION_FAILED")
                .with_detail("session_id already open"));
        }
        g.insert(
            session_id.clone(),
            SessionEntry {
                session,
                signal: signal.clone(),
                state: SessionState::Running,
                exit: None,
                runtime_id: runtime_id.clone(),
                agent: agent.clone(),
            },
        );
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
    let reg_obs = Arc::clone(&reg);
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
        let g = reg.lock().map_err(|_| WorkbenchError::cli_protocol().with_detail("registry lock"))?;
        let entry = g
            .get(&session_id)
            .ok_or_else(|| WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND"))?;
        if entry.state != SessionState::Running {
            return Err(WorkbenchError::map_aisc("AISC_ERR_SESSION_FAILED")
                .with_detail(format!("session state: {:?}", entry.state)));
        }
        entry.session.writer_sender()
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
    let g = reg.lock().map_err(|_| WorkbenchError::cli_protocol().with_detail("registry lock"))?;
    let entry = g
        .get(&session_id)
        .ok_or_else(|| WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND"))?;
    entry.session.resize(cols, rows)
}

#[tauri::command]
pub async fn close_session(
    app: AppHandle,
    session_id: String,
) -> Result<SessionExit, WorkbenchError> {
    let entry = {
        let reg = registry(&app);
        let mut g = reg.lock().map_err(|_| WorkbenchError::cli_protocol().with_detail("registry lock"))?;
        g.remove(&session_id)
            .ok_or_else(|| WorkbenchError::map_aisc("AISC_ERR_SESSION_NOT_FOUND"))?
    };

    // Already exited (observer cached the exit): return it.
    if let Some(exit) = entry.exit {
        return Ok(exit);
    }

    let session = entry.session;
    let signal = entry.signal;
    let runtime_id = entry.runtime_id;

    // §七.1: terminate (kill container agent) -> wait/reap local child.
    // cancel() sets the exit reason to user_close.
    session.cancel();
    let pin = resolve_pin(&app)?;
    let _ = run_control(
        &pin,
        session_terminate_argv(&runtime_id, &session_id),
        TERMINATE_TIMEOUT,
        CancellationToken::new(),
    )
    .await; // best-effort; terminate is idempotent

    let exit = match signal.wait_timeout(CLOSE_WAIT).await {
        Some(exit) => exit,
        None => {
            // Child didn't exit after terminate: force-kill + brief reap wait.
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
    };
    // `session` dropped here -> closes PTY master/writer (cleanup).
    Ok(exit)
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let argv = session_open_argv("rid", "sid", "bash");
        assert_eq!(argv[0], "session");
        assert_eq!(argv[1], "open");
        assert!(argv.contains(&"--agent".into()));
        assert!(!argv.iter().any(|a| a == "--format"));
    }

    #[test]
    fn terminate_argv_includes_format_json() {
        let argv = session_terminate_argv("rid", "sid");
        assert_eq!(argv[1], "terminate");
        assert!(argv.contains(&"--format".into()));
        assert!(argv.contains(&"json".into()));
    }

    #[test]
    fn snapshot_serializes_camel_case() {
        let s = SessionSnapshot {
            session_id: "sid".into(),
            runtime_id: "rid".into(),
            agent: "bash".into(),
            state: SessionState::Running,
        };
        let json = serde_json::to_string(&s).unwrap();
        assert!(json.contains(r#""sessionId":"sid""#));
        assert!(json.contains(r#""runtimeId":"rid""#));
        assert!(json.contains(r#""state":"running""#));
    }
}
