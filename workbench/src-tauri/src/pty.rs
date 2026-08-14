//! PTY supervisor core: spawn a child under a portable-pty, stream bytes,
//! and reap on exit. No Tauri dependency - testable with any local child.
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §9.2 (per-Session reader/writer/child/cancel,
//!   byte chunks + monotonic seq + EOF/error terminal event, paste cap)
//! - 03-lifecycle-contract.md §五 (Session state machine + SessionExit),
//!   §七.1 (close: terminate -> close PTY -> wait/reap -> single exit)

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
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

/// Handle to a live session (PTY or pipe). Cheap to clone for the writer
/// sender; the master/kill are shared via `Arc`.
pub struct PtySession {
    writer_tx: mpsc::Sender<Vec<u8>>,
    master: Option<Arc<Mutex<Box<dyn MasterPty + Send>>>>,
    resize_file: Option<PathBuf>,
    kill_fn: Arc<dyn Fn() + Send + Sync>,
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

    // kill_fn wraps the portable-pty killer for force_kill().
    let killer_for_fn = Arc::clone(&killer);
    let kill_fn: Arc<dyn Fn() + Send + Sync> = Arc::new(move || {
        if let Ok(mut k) = killer_for_fn.lock() {
            let _ = k.kill();
        }
    });

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
        master: Some(master),
        resize_file: None,
        kill_fn,
        cancel,
    };
    Ok((session, signal))
}

/// Spawn `executable argv` with **pipes** (no ConPTY). Used for interactive
/// sessions where the sidecar relays container pty I/O. The container's
/// raw UTF-8 / VT sequences pass through directly to xterm.js with zero
/// console processing - no codepage translation, no Unicode width tables,
/// no VT regeneration. This fixes the encoding/alignment/performance/
/// refresh issues inherent to the ConPTY layer on zh-CN Windows.
///
/// Resize is file-based: the frontend resizes the xterm, Rust writes
/// `<cols> <rows>\n` to a temp file, and the sidecar polls it (100ms) and
/// calls `exec_resize`. The file path is passed via the `AISC_RESIZE_FILE`
/// env var.
pub fn spawn_pipe_session(
    executable: &Path,
    argv: Vec<String>,
    cols: u16,
    rows: u16,
    event_tx: mpsc::Sender<PtyEvent>,
) -> Result<(PtySession, ExitSignal), WorkbenchError> {
    use std::process::{Command, Stdio};

    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let resize_file = std::env::temp_dir().join(format!(
        "aisc-resize-{}-{}.txt",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    std::fs::write(&resize_file, format!("{} {}\n", cols, rows))
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("resize file: {e}")))?;

    let mut cmd = Command::new(executable);
    cmd.args(&argv)
        .env("AISC_RESIZE_FILE", &resize_file)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());

    // Windows: prevent a console window from flashing. The sidecar is a
    // console subsystem app; without this flag a brief window appears.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("pipe spawn: {e}")))?;
    let pid = child.id();
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("no stdin"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("no stdout"))?;

    let cancel = CancellationToken::new();
    let reader_errored = Arc::new(AtomicBool::new(false));
    let signal = ExitSignal::new();
    let (writer_tx, mut writer_rx) = mpsc::channel::<Vec<u8>>(WRITE_CHANNEL_CAP);

    // kill_fn: taskkill /PID /T /F on Windows, kill -9 on Unix.
    let kill_fn: Arc<dyn Fn() + Send + Sync> = Arc::new(move || {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt as _;
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x08000000)
                .output();
        }
        #[cfg(unix)]
        {
            unsafe {
                libc::kill(pid as i32, libc::SIGKILL);
            }
        }
        #[cfg(not(any(windows, unix)))]
        {
            let _ = pid;
        }
    });

    // write task: drain mpsc -> stdin pipe.
    tokio::task::spawn_blocking(move || {
        let mut stdin = stdin;
        while let Some(bytes) = writer_rx.blocking_recv() {
            if stdin.write_all(&bytes).is_err() {
                break;
            }
            let _ = stdin.flush();
        }
        // writer_rx closed -> drop stdin -> EOF to child
    });

    // reader task: stdout pipe -> base64 -> PtyEvent::Output.
    let event_tx_r = event_tx.clone();
    let killer_r = Arc::clone(&kill_fn);
    let reader_errored_r = Arc::clone(&reader_errored);
    tokio::task::spawn_blocking(move || {
        let mut stdout = stdout;
        let mut buf = vec![0u8; READ_BUF];
        let mut seq = 0u64;
        loop {
            match stdout.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    seq += 1;
                    let b64 = base64::engine::general_purpose::STANDARD.encode(&buf[..n]);
                    if event_tx_r
                        .blocking_send(PtyEvent::Output { seq, bytes: b64 })
                        .is_err()
                    {
                        break;
                    }
                }
                Err(e) => {
                    #[cfg(unix)]
                    let is_eof = e.raw_os_error() == Some(libc::EIO);
                    #[cfg(not(unix))]
                    let is_eof = false;
                    if is_eof {
                        break;
                    }
                    reader_errored_r.store(true, Ordering::SeqCst);
                    // Can't call kill_fn (moved into closure). Use taskkill/kill directly.
                    (killer_r)();
                    break;
                }
            }
        }
    });

    // wait task: own the child, block on wait(), set exit signal.
    let event_tx_w = event_tx.clone();
    let cancel_w = cancel.clone();
    let reader_errored_w = Arc::clone(&reader_errored);
    let signal_w = signal.clone();
    let resize_file_w = resize_file.clone();
    tokio::task::spawn_blocking(move || {
        let mut child = child;
        let status = child.wait();
        // Clean up the resize file (best-effort).
        let _ = std::fs::remove_file(&resize_file_w);
        let exit = SessionExit {
            exit_code: match &status {
                Ok(s) => s.code(),
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
        master: None,
        resize_file: Some(resize_file),
        kill_fn,
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
        // Pipe mode: write size to the resize file (sidecar polls it).
        if let Some(path) = &self.resize_file {
            std::fs::write(path, format!("{} {}\n", cols, rows))
                .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("resize file: {e}")))?;
            return Ok(());
        }
        // PTY mode: resize the ConPTY directly.
        let master = self
            .master
            .as_ref()
            .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("no master"))?
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
        (self.kill_fn)();
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

    // --- Stage 1 (S1.2, F-R02/F-R03): PTY lifecycle / backpressure ---

    #[test]
    fn spawn_missing_command_returns_error() {
        // Failure path must produce a structured error and no child survives.
        let (tx, _rx) = mpsc::channel(8);
        let result = spawn_pty_session(
            Path::new("__aisc_missing_command_xyz__"),
            vec![],
            80,
            24,
            tx,
        );
        let err = match result {
            Ok(_) => panic!("missing executable must fail spawn"),
            Err(e) => e,
        };
        assert!(
            err.code.starts_with("WB_ERR_CLI_"),
            "unexpected error code: {}",
            err.code
        );
    }

    #[test]
    fn write_channel_capacity_is_bounded() {
        // F-R03: the session writer channel must never grow unbounded; the
        // cap is a hard backpressure limit (send beyond it is refused).
        let (tx, _rx) = mpsc::channel::<Vec<u8>>(WRITE_CHANNEL_CAP);
        for _ in 0..WRITE_CHANNEL_CAP {
            assert!(tx.try_send(vec![0u8]).is_ok());
        }
        assert!(
            tx.try_send(vec![0u8]).is_err(),
            "channel must refuse writes beyond WRITE_CHANNEL_CAP={WRITE_CHANNEL_CAP}"
        );
    }
}
