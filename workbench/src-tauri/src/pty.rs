//! PTY supervisor core: spawn a child under a portable-pty, stream bytes,
//! and reap on exit. No Tauri dependency - testable with any local child.
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §9.2 (per-Session reader/writer/child/cancel,
//!   byte chunks + monotonic seq + EOF/error terminal event, paste cap)
//! - 03-lifecycle-contract.md §五 (Session state machine + SessionExit),
//!   §七.1 (close: terminate -> close PTY -> wait/reap -> single exit)

use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use base64::Engine;
use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use tokio::sync::{mpsc, Notify};
use tokio_util::sync::CancellationToken;

use crate::error::WorkbenchError;

const READ_BUF: usize = 8192;
const WRITE_CHANNEL_CAP: usize = 16;

/// Streamed to the frontend via a Tauri Channel. `bytes` is base64-encoded.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase", rename_all_fields = "camelCase", tag = "type")]
pub enum PtyEvent {
    Output {
        seq: u64,
        bytes: String,
    },
    Exit {
        reason: String,
        exit_code: Option<i32>,
    },
    Error {
        code: String,
        message: String,
    },
}

/// Terminal result for a session (03 §五). `finished_at_ms` is epoch millis.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionExit {
    pub exit_code: Option<i32>,
    pub reason: String,
    pub finished_at_ms: i64,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SessionState {
    Starting,
    Running,
    Closing,
    Exited,
    Failed,
    Disconnected,
}

pub const REASON_PROCESS_EXIT: &str = "process_exit";
pub const REASON_USER_CLOSE: &str = "user_close";
pub const REASON_TRANSPORT_ERROR: &str = "transport_error";

/// Shared signal set once by the supervisor when the child is reaped. Close
/// and observer paths await it; `set` is idempotent (first writer wins).
#[derive(Clone)]
pub struct ExitSignal(Arc<Mutex<Option<SessionExit>>>, Arc<Notify>);

impl ExitSignal {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(None)), Arc::new(Notify::new()))
    }

    pub fn set(&self, exit: SessionExit) {
        if let Ok(mut g) = self.0.lock() {
            if g.is_none() {
                *g = Some(exit);
            }
        }
        self.1.notify_one();
    }

    pub fn get(&self) -> Option<SessionExit> {
        self.0.lock().ok().and_then(|g| g.clone())
    }

    /// Wait indefinitely until the exit is set.
    pub async fn wait(&self) -> SessionExit {
        loop {
            if let Some(e) = self.get() {
                return e;
            }
            self.1.notified().await;
        }
    }

    /// Wait up to `d`; return the exit if set in time.
    pub async fn wait_timeout(&self, d: Duration) -> Option<SessionExit> {
        if let Some(e) = self.get() {
            return Some(e);
        }
        let _ = tokio::time::timeout(d, self.1.notified()).await;
        self.get()
    }
}

/// Handle to a live PTY session. Cheap to clone for the writer sender; the
/// master/killer are shared via `Arc<Mutex<...>>`.
pub struct PtySession {
    writer_tx: mpsc::Sender<Vec<u8>>,
    master: Arc<Mutex<Box<dyn MasterPty + Send>>>,
    killer: Arc<Mutex<Box<dyn ChildKiller + Send + Sync>>>,
    cancel: CancellationToken,
}

/// Spawn `executable argv` under a PTY. Returns the session handle + an
/// `ExitSignal` that fires when the child is reaped.
///
/// Three background tasks run independently:
/// - write task: owns the PTY writer, drains a bounded mpsc (backpressure).
/// - reader task: blocking read loop, emits `Output` chunks with monotonic seq.
/// - wait task: owns the child, blocks on `child.wait()`, then sets the exit
///   signal + emits a single `Exit` event. `clone_killer()` lets close/reader
///   force-kill without waiting for `wait()` to unblock.
pub fn spawn_pty_session(
    executable: &Path,
    argv: Vec<String>,
    cols: u16,
    rows: u16,
    event_tx: mpsc::Sender<PtyEvent>,
) -> Result<(PtySession, ExitSignal), WorkbenchError> {
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("openpty: {e}")))?;
    let master = pair.master;
    let slave = pair.slave;

    let writer = master
        .take_writer()
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("take_writer: {e}")))?;
    let reader = master
        .try_clone_reader()
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("try_clone_reader: {e}")))?;

    let mut cmd = CommandBuilder::new(executable);
    cmd.args(argv);
    let child = slave
        .spawn_command(cmd)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("spawn_command: {e}")))?;
    drop(slave);

    let killer = Arc::new(Mutex::new(child.clone_killer()));
    let master = Arc::new(Mutex::new(master));
    let cancel = CancellationToken::new();
    let reader_errored = Arc::new(AtomicBool::new(false));
    let signal = ExitSignal::new();
    let (writer_tx, mut writer_rx) = mpsc::channel::<Vec<u8>>(WRITE_CHANNEL_CAP);

    // write task
    tokio::task::spawn_blocking(move || {
        let mut writer = writer;
        while let Some(bytes) = writer_rx.blocking_recv() {
            if writer.write_all(&bytes).is_err() {
                break;
            }
            let _ = writer.flush();
        }
        // writer_rx closed -> drop writer -> EOF to slave
    });

    // reader task
    let event_tx_r = event_tx.clone();
    let killer_r = Arc::clone(&killer);
    let reader_errored_r = Arc::clone(&reader_errored);
    tokio::task::spawn_blocking(move || {
        let mut reader = reader;
        let mut buf = vec![0u8; READ_BUF];
        let mut seq = 0u64;
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break, // EOF
                Ok(n) => {
                    seq += 1;
                    let b64 = base64::engine::general_purpose::STANDARD.encode(&buf[..n]);
                    if event_tx_r.blocking_send(PtyEvent::Output { seq, bytes: b64 }).is_err() {
                        break; // consumer gone
                    }
                }
                Err(e) => {
                    // On Linux the master read returns EIO when the slave
                    // closes (child exited); that is a normal EOF, not a
                    // transport failure. Other errors are transport losses.
                    #[cfg(unix)]
                    let is_eof = e.raw_os_error() == Some(libc::EIO);
                    #[cfg(not(unix))]
                    let is_eof = false;
                    if is_eof {
                        break;
                    }
                    reader_errored_r.store(true, Ordering::SeqCst);
                    if let Ok(mut k) = killer_r.lock() {
                        let _ = k.kill();
                    }
                    break;
                }
            }
        }
    });

    // wait task (owns child)
    let event_tx_w = event_tx.clone();
    let cancel_w = cancel.clone();
    let reader_errored_w = Arc::clone(&reader_errored);
    let signal_w = signal.clone();
    tokio::task::spawn_blocking(move || {
        let mut child = child;
        let status = child.wait();
        let exit = SessionExit {
            exit_code: match &status {
                Ok(s) => Some(s.exit_code() as i32),
                Err(_) => None,
            },
            reason: if cancel_w.is_cancelled() {
                REASON_USER_CLOSE
            } else if reader_errored_w.load(Ordering::SeqCst) {
                REASON_TRANSPORT_ERROR
            } else {
                REASON_PROCESS_EXIT
            }
            .to_string(),
            finished_at_ms: now_ms(),
        };
        let _ = event_tx_w.blocking_send(PtyEvent::Exit {
            reason: exit.reason.clone(),
            exit_code: exit.exit_code,
        });
        signal_w.set(exit);
    });

    let session = PtySession {
        writer_tx,
        master,
        killer,
        cancel,
    };
    Ok((session, signal))
}

impl PtySession {
    /// Cloneable sender so `write_session` can send without holding the
    /// registry lock across an await.
    pub fn writer_sender(&self) -> mpsc::Sender<Vec<u8>> {
        self.writer_tx.clone()
    }

    pub async fn write(&self, bytes: Vec<u8>) -> Result<(), WorkbenchError> {
        self.writer_tx
            .send(bytes)
            .await
            .map_err(|_| WorkbenchError::cli_protocol().with_detail("session writer closed"))
    }

    pub fn resize(&self, cols: u16, rows: u16) -> Result<(), WorkbenchError> {
        let master = self
            .master
            .lock()
            .map_err(|_| WorkbenchError::cli_protocol().with_detail("master lock poisoned"))?;
        master
            .resize(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("resize: {e}")))
    }

    /// Signal user-initiated close (sets the exit reason to user_close).
    pub fn cancel(&self) {
        self.cancel.cancel();
    }

    /// Force-kill the child; used when close times out waiting for reaping.
    pub fn force_kill(&self) {
        if let Ok(mut k) = self.killer.lock() {
            let _ = k.kill();
        }
    }
}

pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pty_event_output_serializes_base64() {
        let ev = PtyEvent::Output { seq: 3, bytes: base64::engine::general_purpose::STANDARD.encode(b"hi") };
        let s = serde_json::to_string(&ev).unwrap();
        assert!(s.contains(r#""type":"output""#));
        assert!(s.contains(r#""seq":3"#));
        assert!(s.contains("aGk=")); // base64("hi")
    }

    #[test]
    fn pty_event_exit_serializes() {
        let ev = PtyEvent::Exit { reason: "process_exit".into(), exit_code: Some(0) };
        let s = serde_json::to_string(&ev).unwrap();
        assert!(s.contains(r#""type":"exit""#));
        assert!(s.contains(r#""exitCode":0"#));
    }

    #[test]
    fn session_state_serializes_snake_case() {
        assert_eq!(
            serde_json::to_string(&SessionState::Running).unwrap(),
            r#""running""#
        );
        assert_eq!(
            serde_json::to_string(&SessionState::Disconnected).unwrap(),
            r#""disconnected""#
        );
    }

    #[test]
    fn exit_signal_set_is_idempotent_first_wins() {
        let sig = ExitSignal::new();
        sig.set(SessionExit {
            exit_code: Some(7),
            reason: REASON_PROCESS_EXIT.into(),
            finished_at_ms: 1,
        });
        sig.set(SessionExit {
            exit_code: Some(0),
            reason: REASON_USER_CLOSE.into(),
            finished_at_ms: 2,
        });
        let got = sig.get().unwrap();
        assert_eq!(got.exit_code, Some(7));
        assert_eq!(got.reason, REASON_PROCESS_EXIT);
    }

    #[tokio::test]
    async fn exit_signal_wait_returns_after_set() {
        let sig = ExitSignal::new();
        let sig2 = sig.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(20)).await;
            sig2.set(SessionExit {
                exit_code: Some(0),
                reason: REASON_PROCESS_EXIT.into(),
                finished_at_ms: 0,
            });
        });
        let exit = sig.wait().await;
        assert_eq!(exit.exit_code, Some(0));
    }

    #[tokio::test]
    async fn exit_signal_wait_timeout_returns_none_when_unset() {
        let sig = ExitSignal::new();
        assert!(sig.wait_timeout(Duration::from_millis(20)).await.is_none());
    }
}
