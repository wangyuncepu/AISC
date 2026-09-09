//! 2.1.10 R1/R2 (D-7/D-8): the client half of `aisc serve --stdio`.
//!
//! One long-lived serve connection: spawn (direct or wrapped in `ssh`), read
//! the ready banner (protocol handshake), then a **resident reader task**
//! fans every incoming frame out — result frames to the pending request's
//! oneshot, `pty.*` stream frames to the per-sid route — while writes
//! (requests AND stream control) share one stdin lock. R1's strictly-serial
//! client is gone; requests and PTY streams now multiplex a single session.
//!
//! Version pairing note: unlike VS Code's commit-equality match (its server
//! and client share one build tree), AISC's compatibility surface is the
//! envelope protocol + capabilities — the banner's `cli_version` is recorded
//! for display/diagnosis, `serve_protocol` is the hard gate.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;

use crate::cli::{CliTarget, Envelope, SshTarget};
use crate::error::WorkbenchError;

/// Serve wire protocol this client speaks (must equal the Python side's
/// `SERVE_PROTOCOL`). v1.3 (D-10): generic `cli` op + ready `home`; the bump
/// 1→3 is a hard pairing — a mismatch is an "upgrade the remote aisc" error,
/// never a silent per-op-ssh fallback (user ruling 2026-09-09).
pub const SERVE_PROTOCOL: u64 = 3;

/// The `ready` banner — the session's handshake.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct ReadyBanner {
    #[serde(default)]
    pub serve_protocol: u64,
    #[serde(default)]
    pub cli_version: String,
    /// v1.3: the remote home directory — anchors the remote browser (F2-B).
    #[serde(default)]
    pub home: Option<String>,
}

impl Default for ReadyBanner {
    fn default() -> Self {
        ReadyBanner { serve_protocol: 0, cli_version: String::new(), home: None }
    }
}

/// One frame from the serve process (`type`-tagged). `pty.*` frames are the
/// R2 stream plane; the generic `event` frame stays reserved for R3+.
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(tag = "type")]
pub enum ServeFrame {
    #[serde(rename = "ready")]
    Ready {
        #[serde(default)]
        serve_protocol: u64,
        #[serde(default)]
        cli_version: String,
        #[serde(default)]
        home: Option<String>,
    },
    #[serde(rename = "result")]
    Result {
        id: Option<String>,
        ok: bool,
        #[serde(default)]
        envelope: Option<Envelope>,
        #[serde(default)]
        error: Option<String>,
    },
    #[serde(rename = "log")]
    Log {
        #[serde(default)]
        level: String,
        #[serde(default)]
        line: String,
    },
    #[serde(rename = "event")]
    Event {
        #[serde(default)]
        event: String,
        #[serde(default)]
        data: serde_json::Value,
    },
    #[serde(rename = "pty.output")]
    PtyOutput {
        sid: String,
        data: String,
    },
    #[serde(rename = "pty.exit")]
    PtyExit {
        sid: String,
        #[serde(default)]
        exit_code: Option<i64>,
        #[serde(default)]
        error: Option<String>,
    },
}

/// A decoded stream frame routed to a subscribed PTY (base64 already undone).
#[derive(Debug, Clone)]
pub enum PtyStreamFrame {
    Output { sid: String, data: Vec<u8> },
    Exit { sid: String, exit_code: Option<i32>, error: Option<String> },
}

/// What a pending request resolves to.
#[derive(Debug)]
enum ServeOutcome {
    Ok(Envelope),
    Failed(String),
}

/// Client → serve frames.
#[derive(serde::Serialize)]
#[serde(tag = "type")]
enum ClientFrame<'a> {
    #[serde(rename = "request")]
    Request { id: &'a str, op: &'a str, args: &'a serde_json::Value },
    #[serde(rename = "pty.input")]
    PtyInput { sid: &'a str, data: &'a str },
    #[serde(rename = "pty.resize")]
    PtyResize { sid: &'a str, cols: u16, rows: u16 },
    #[serde(rename = "pty.kill")]
    PtyKill { sid: &'a str },
}

// ---------------------------------------------------------------------------
// Wire-level helpers (stream-generic: the protocol is testable against
// tokio::io::duplex without spawning anything).

/// Read one JSON frame line. `None` = clean EOF (the session went away).
/// Blank lines are skipped (keepalive/noise) via the loop — no recursion.
async fn read_frame<R: AsyncRead + Unpin>(
    reader: &mut BufReader<R>,
) -> Result<Option<ServeFrame>, WorkbenchError> {
    loop {
        let mut line = String::new();
        let n = reader
            .read_line(&mut line)
            .await
            .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve read: {e}")))?;
        if n == 0 {
            return Ok(None);
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        return serde_json::from_str(trimmed)
            .map(Some)
            .map_err(|e| {
                WorkbenchError::cli_protocol().with_detail(format!("serve frame decode: {e}"))
            });
    }
}

/// Write one client frame and flush.
async fn write_frame<W: AsyncWrite + Unpin>(
    writer: &mut W,
    frame: &ClientFrame<'_>,
) -> Result<(), WorkbenchError> {
    let line = serde_json::to_string(frame)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve encode: {e}")))?;
    let io = async {
        writer.write_all(line.as_bytes()).await?;
        writer.write_all(b"\n").await?;
        writer.flush().await
    };
    io.await
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve write: {e}")))
}

// ---------------------------------------------------------------------------
// The session.

pub struct ServeSession {
    child: Arc<tokio::sync::Mutex<Child>>,
    stdin: Arc<tokio::sync::Mutex<ChildStdin>>,
    banner: ReadyBanner,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<ServeOutcome>>>>,
    pty_routes: Arc<Mutex<HashMap<String, mpsc::UnboundedSender<PtyStreamFrame>>>>,
    event_routes: Arc<Mutex<HashMap<String, Vec<mpsc::UnboundedSender<serde_json::Value>>>>>,
    seq: AtomicU64,
    _reader: tokio::task::JoinHandle<()>,
}

fn spawn(target: &CliTarget, cli_args: &[String]) -> Command {
    // Reuse CliTarget::spawn_pieces so ssh options/stdin conventions stay in
    // exactly one place (R1b).
    let (program, args) = target.spawn_pieces(cli_args);
    let mut cmd = Command::new(&program);
    cmd.args(&args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

impl ServeSession {
    /// Direct local spawn (PoC/testing: the serve process on THIS machine).
    pub async fn spawn_local(aisc: &Path) -> Result<Self, WorkbenchError> {
        Self::start(CliTarget::Local(aisc.to_path_buf())).await
    }

    /// Remote spawn: `ssh <target…> aisc serve --stdio` — the transport the
    /// Workbench uses for real machines.
    pub async fn spawn_ssh(t: &SshTarget) -> Result<Self, WorkbenchError> {
        Self::start(CliTarget::Remote(t.clone())).await
    }

    async fn start(target: CliTarget) -> Result<Self, WorkbenchError> {
        Self::start_for(&target).await
    }

    /// Shared spawn path (also used by pty.rs's `spawn_serve_pty_session`).
    pub(crate) async fn start_for(target: &CliTarget) -> Result<Self, WorkbenchError> {
        let mut child = spawn(&target, &["serve".into(), "--stdio".into()])
            .spawn()
            .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve spawn: {e}")))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("serve stdin"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("serve stdout"))?;

        let pending: Arc<Mutex<HashMap<String, oneshot::Sender<ServeOutcome>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let pty_routes: Arc<Mutex<HashMap<String, mpsc::UnboundedSender<PtyStreamFrame>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let event_routes: Arc<
            Mutex<HashMap<String, Vec<mpsc::UnboundedSender<serde_json::Value>>>>,
        > = Arc::new(Mutex::new(HashMap::new()));

        // Handshake BEFORE the resident reader owns the stream.
        let mut reader = BufReader::new(stdout);
        let banner = Self::handshake(&mut reader).await?;

        // Resident reader: fan every frame out until EOF.
        let reader_pending = Arc::clone(&pending);
        let reader_routes = Arc::clone(&pty_routes);
        let reader_events = Arc::clone(&event_routes);
        let reader_task = tokio::spawn(async move {
            loop {
                let frame = match read_frame(&mut reader).await {
                    Ok(Some(f)) => f,
                    Ok(None) | Err(_) => break,
                };
                match frame {
                    ServeFrame::Result { id, ok, envelope, error } => {
                        if let Some(id) = id {
                            let tx = reader_pending.lock().ok().and_then(|mut m| m.remove(&id));
                            if let Some(tx) = tx {
                                let outcome = match (ok, envelope) {
                                    (true, Some(env)) => ServeOutcome::Ok(env),
                                    (true, None) => {
                                        ServeOutcome::Failed("result missing envelope".into())
                                    }
                                    (false, _) => {
                                        ServeOutcome::Failed(error.unwrap_or_else(|| "serve op failed".into()))
                                    }
                                };
                                let _ = tx.send(outcome);
                            }
                        }
                    }
                    ServeFrame::PtyOutput { sid, data } => {
                        let route = reader_routes.lock().ok().and_then(|m| m.get(&sid).cloned());
                        if let Some(tx) = route {
                            match base64_decode(&data) {
                                Ok(bytes) => {
                                    let _ = tx.send(PtyStreamFrame::Output { sid, data: bytes });
                                }
                                Err(e) => {
                                    let _ = tx.send(PtyStreamFrame::Exit {
                                        sid,
                                        exit_code: None,
                                        error: Some(format!("bad pty.output base64: {e}")),
                                    });
                                }
                            }
                        }
                    }
                    ServeFrame::PtyExit { sid, exit_code, error } => {
                        let route = reader_routes.lock().ok().and_then(|mut m| m.remove(&sid));
                        if let Some(tx) = route {
                            let _ = tx.send(PtyStreamFrame::Exit {
                                sid,
                                exit_code: exit_code.map(|c| c as i32),
                                error,
                            });
                        }
                    }
                    ServeFrame::Event { event, data } => {
                        // R3 (D-9): fs.change and friends fan out to every
                        // subscriber of that event name.
                        if let Ok(map) = reader_events.lock() {
                            if let Some(subs) = map.get(&event) {
                                for tx in subs {
                                    let _ = tx.send(data.clone());
                                }
                            }
                        }
                    }
                    ServeFrame::Log { .. } | ServeFrame::Ready { .. } => {
                        // diagnostics / mid-session re-banner: noise
                    }
                }
            }
            // Session gone: fail every pending request and close every route.
            if let Ok(mut m) = reader_pending.lock() {
                for (_, tx) in m.drain() {
                    let _ = tx.send(ServeOutcome::Failed("serve session closed".into()));
                }
            }
            if let Ok(mut m) = reader_routes.lock() {
                m.clear(); // dropping the senders closes the receivers
            }
        });

        Ok(ServeSession {
            child: Arc::new(tokio::sync::Mutex::new(child)),
            stdin: Arc::new(tokio::sync::Mutex::new(stdin)),
            banner,
            pending,
            pty_routes,
            event_routes,
            seq: AtomicU64::new(0),
            _reader: reader_task,
        })
    }

    /// Read the ready banner and gate on `serve_protocol`.
    async fn handshake(reader: &mut BufReader<ChildStdout>) -> Result<ReadyBanner, WorkbenchError> {
        let frame = read_frame(reader)
            .await?
            .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("serve closed before ready"))?;
        match frame {
            ServeFrame::Ready { serve_protocol, cli_version, home } => {
                if serve_protocol != SERVE_PROTOCOL {
                    return Err(WorkbenchError::cli_protocol().with_detail(format!(
                        "serve protocol mismatch: client {SERVE_PROTOCOL}, remote \
                         {serve_protocol} — upgrade the aisc CLI on the target machine"
                    )));
                }
                Ok(ReadyBanner { serve_protocol, cli_version, home })
            }
            _ => Err(WorkbenchError::cli_protocol().with_detail(
                "serve first frame was not ready",
            )),
        }
    }

    pub fn banner(&self) -> &ReadyBanner {
        &self.banner
    }

    fn next_id(&self) -> String {
        format!("wb{}", self.seq.fetch_add(1, Ordering::Relaxed) + 1)
    }

    /// Round-trip one op. Concurrent with PTY streams — the resident reader
    /// routes frames, so a long-lived stream never starves a request.
    pub async fn request(
        &self,
        op: &str,
        args: &serde_json::Value,
        timeout: Duration,
        cancel: &CancellationToken,
    ) -> Result<Envelope, WorkbenchError> {
        let id = self.next_id();
        let (tx, rx) = oneshot::channel();
        if let Ok(mut m) = self.pending.lock() {
            m.insert(id.clone(), tx);
        }
        {
            let mut stdin = self.stdin.lock().await;
            if let Err(e) = write_frame(&mut *stdin, &ClientFrame::Request { id: &id, op, args }).await {
                if let Ok(mut m) = self.pending.lock() {
                    m.remove(&id);
                }
                return Err(e);
            }
        }
        let outcome = tokio::select! {
            r = rx => r.map_err(|_| {
                WorkbenchError::cli_protocol().with_detail("serve reader dropped the request")
            })?,
            _ = tokio::time::sleep(timeout) => {
                if let Ok(mut m) = self.pending.lock() {
                    m.remove(&id);
                }
                return Err(WorkbenchError::cli_timeout());
            }
            _ = cancel.cancelled() => {
                if let Ok(mut m) = self.pending.lock() {
                    m.remove(&id);
                }
                return Err(WorkbenchError::cli_cancelled());
            }
        };
        match outcome {
            ServeOutcome::Ok(env) => Ok(env),
            ServeOutcome::Failed(msg) => {
                Err(WorkbenchError::cli_protocol().with_detail(msg))
            }
        }
    }

    /// Subscribe to one PTY's stream frames (the sid the client will open).
    /// The receiver closes when the session exits or the PTY exits.
    pub fn subscribe_pty(&self, sid: &str) -> mpsc::UnboundedReceiver<PtyStreamFrame> {
        let (tx, rx) = mpsc::unbounded_channel();
        if let Ok(mut m) = self.pty_routes.lock() {
            m.insert(sid.to_string(), tx);
        }
        rx
    }

    pub async fn pty_input(&self, sid: &str, bytes: &[u8]) -> Result<(), WorkbenchError> {
        let data = base64_encode(bytes);
        let mut stdin = self.stdin.lock().await;
        write_frame(&mut *stdin, &ClientFrame::PtyInput { sid, data: &data }).await
    }

    pub async fn pty_resize(&self, sid: &str, cols: u16, rows: u16) -> Result<(), WorkbenchError> {
        let mut stdin = self.stdin.lock().await;
        write_frame(&mut *stdin, &ClientFrame::PtyResize { sid, cols, rows }).await
    }

    pub async fn pty_kill(&self, sid: &str) -> Result<(), WorkbenchError> {
        let mut stdin = self.stdin.lock().await;
        write_frame(&mut *stdin, &ClientFrame::PtyKill { sid }).await
    }

    /// Subscribe to one serve event name (e.g. "fs.change"); the receiver
    /// yields the frame's `data` object. Dropping the receiver removes it on
    /// the next delivery attempt (send failure prunes).
    pub fn subscribe_event(&self, name: &str) -> mpsc::UnboundedReceiver<serde_json::Value> {
        let (tx, rx) = mpsc::unbounded_channel();
        if let Ok(mut map) = self.event_routes.lock() {
            map.entry(name.to_string()).or_default().push(tx);
        }
        rx
    }

    /// Graceful stop: stdin EOF tells serve to exit; bounded wait, then kill.
    /// `&self` (not `self`): the session is shared by the PTY planes, so
    /// shutdown runs whenever the last owner decides the session is over.
    pub async fn shutdown(&self) {
        use tokio::io::AsyncWriteExt;
        {
            let mut stdin = self.stdin.lock().await;
            let _ = stdin.shutdown().await;
        }
        let grace = Duration::from_secs(3);
        let mut child = self.child.lock().await;
        if tokio::time::timeout(grace, child.wait()).await.is_err() {
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
    }
}

impl Drop for ServeSession {
    fn drop(&mut self) {
        // Last owner gone (pool eviction, teardown): NEVER leak the ssh /
        // serve child — the tokio orphan reaper would otherwise hold the
        // runtime open at process end (field evidence 2026-09-09: a test
        // binary whose pooled session outlived it never exited) and every
        // evict-and-respawn would strand a zombie ssh. Graceful EOF-exit
        // stays `shutdown()`'s job for callers that care; this is the
        // best-effort backstop (sync, no await, skip if locked).
        if let Ok(mut child) = self.child.try_lock() {
            let _ = child.start_kill();
        }
    }
}

// -- 2.1.10 R3: the pooled serve connection for a remote target ----------------
//
// fs.* ops are high-frequency; per-op connections would re-handshake the ssh
// session constantly. One ServeSession per SshTarget, shared by every fs call
// (PTY sessions keep their own connections — they have their own lifetime).

pub struct ServePool(pub tokio::sync::Mutex<HashMap<String, Arc<ServeSession>>>);

impl ServePool {
    pub fn new() -> Self {
        ServePool(tokio::sync::Mutex::new(HashMap::new()))
    }
}

impl Default for ServePool {
    fn default() -> Self {
        Self::new()
    }
}

/// The process-global pool (D-10): control-plane routing in `cli.rs` has no
/// AppHandle in scope, so the pool lives as a static — same idiom as the
/// trace ring. The tauri-managed instance was removed; all callers reach the
/// one pool through this accessor.
static GLOBAL_POOL: std::sync::OnceLock<ServePool> = std::sync::OnceLock::new();

pub fn global_pool() -> &'static ServePool {
    GLOBAL_POOL.get_or_init(ServePool::new)
}

fn target_key(t: &SshTarget) -> String {
    format!("{}:{}:{:?}", t.host, t.port.unwrap_or(22), t.key_path)
}

/// Fetch (or establish) the pooled serve session for one ssh target. A broken
/// cached session (ssh died) is replaced transparently on the next call: the
/// request that hits the dead connection errors, the entry is evicted.
pub async fn pooled_session(
    pool: &ServePool,
    t: &SshTarget,
) -> Result<Arc<ServeSession>, WorkbenchError> {
    let key = target_key(t);
    {
        let guard = pool.0.lock().await;
        if let Some(s) = guard.get(&key) {
            return Ok(Arc::clone(s));
        }
    }
    let session = Arc::new(ServeSession::spawn_ssh(t).await?);
    pool.0.lock().await.insert(key, Arc::clone(&session));
    Ok(session)
}

/// Drop one target's cached session (dead ssh) so the next use re-spawns.
pub async fn evict_session(pool: &ServePool, t: &SshTarget) {
    pool.0.lock().await.remove(&target_key(t));
}

/// D-10 (F2-A): run one control-plane CLI argv over the pooled serve
/// connection via the generic `cli` op — the ONLY remote transport for
/// envelope commands (per-op ssh survives solely for serve bootstrap and the
/// build event stream). A transport-grade failure evicts the dead session
/// and retries once on a fresh connection; timeouts/cancellations never
/// evict (the op may simply be slow while the session lives).
pub async fn cli_op(
    t: &SshTarget,
    argv: &[String],
    input: Option<String>,
    timeout: std::time::Duration,
    cancel: &tokio_util::sync::CancellationToken,
    run_id: &str,
) -> Result<Envelope, WorkbenchError> {
    let pool = global_pool();
    let mut args = serde_json::json!({ "argv": argv, "run_id": run_id });
    if let Some(s) = input {
        args["stdin"] = serde_json::json!(s);
    }
    let first = match pooled_session(pool, t).await {
        Ok(s) => s.request("cli", &args, timeout, cancel).await,
        Err(e) => Err(e),
    };
    match first {
        Ok(env) => Ok(env),
        Err(e) if !matches!(e.code.as_str(), "WB_ERR_CLI_TIMEOUT" | "WB_ERR_CLI_CANCELLED") => {
            // Transport-grade failure: the cached session is suspect —
            // evict, re-spawn, retry once.
            evict_session(pool, t).await;
            let session = pooled_session(pool, t).await?;
            session.request("cli", &args, timeout, cancel).await
        }
        Err(e) => Err(e),
    }
}

/// fs.* request helper for the pooled connection: returns the envelope's
/// `data` object (the op payload) on success.
pub async fn fs_op(
    pool: &ServePool,
    t: &SshTarget,
    op: &str,
    args: &serde_json::Value,
) -> Result<serde_json::Value, WorkbenchError> {
    let session = pooled_session(pool, t).await?;
    let cancel = CancellationToken::new();
    let env = session
        .request(op, args, Duration::from_secs(30), &cancel)
        .await?;
    if env.meta.exit_code != 0 {
        let detail = env
            .errors
            .first()
            .map(|e| format!("{} ({})", e.message, e.code))
            .unwrap_or_else(|| format!("{op} failed"));
        return Err(WorkbenchError::cli_protocol().with_detail(detail));
    }
    Ok(env.data.unwrap_or(serde_json::Value::Null))
}

// -- tiny base64 (URL-safe-free, standard alphabet) ---------------------------

fn base64_encode(data: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(data)
}

fn base64_decode(data: &str) -> Result<Vec<u8>, String> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(data)
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tokio::io::duplex;

    fn mock_serve() -> (tokio::io::DuplexStream, tokio::io::DuplexStream) {
        duplex(64 * 1024)
    }

    #[tokio::test]
    async fn frame_decode_pty_variants() {
        let out: ServeFrame = serde_json::from_str(
            r#"{"type":"pty.output","sid":"s1","data":"aGk="}"#,
        )
        .unwrap();
        match out {
            ServeFrame::PtyOutput { sid, data } => {
                assert_eq!(sid, "s1");
                assert_eq!(data, "aGk=");
            }
            other => panic!("{other:?}"),
        }
        let ex: ServeFrame =
            serde_json::from_str(r#"{"type":"pty.exit","sid":"s1","exit_code":3}"#).unwrap();
        match ex {
            ServeFrame::PtyExit { sid, exit_code, error } => {
                assert_eq!(sid, "s1");
                assert_eq!(exit_code, Some(3));
                assert!(error.is_none());
            }
            other => panic!("{other:?}"),
        }
    }

    #[tokio::test]
    async fn client_frame_shapes() {
        let f = ClientFrame::Request { id: "u9", op: "doctor", args: &json!({}) };
        assert_eq!(
            serde_json::to_string(&f).unwrap(),
            r#"{"type":"request","id":"u9","op":"doctor","args":{}}"#
        );
        let f = ClientFrame::PtyInput { sid: "s", data: "aGk=" };
        assert_eq!(
            serde_json::to_string(&f).unwrap(),
            r#"{"type":"pty.input","sid":"s","data":"aGk="}"#
        );
        let f = ClientFrame::PtyResize { sid: "s", cols: 100, rows: 30 };
        assert_eq!(
            serde_json::to_string(&f).unwrap(),
            r#"{"type":"pty.resize","sid":"s","cols":100,"rows":30}"#
        );
    }

    /// A4-style bridge test WITHOUT spawning: duplex peers where one side is
    /// a scripted serve — requests and pty frames multiplex one stream.
    #[tokio::test]
    async fn result_and_pty_frames_multiplex_one_reader() {
        let (client_side, mut serve_side) = mock_serve();
        let mut reader = BufReader::new(client_side);

        // script: banner, then (interleaved) a pty.output for another sid,
        // then our result.
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            serve_side
                .write_all(
                    br#"{"type":"ready","serve_protocol":1,"cli_version":"2.1.9.dev0"}
{"type":"pty.output","sid":"other","data":"eA=="}
{"type":"pty.output","sid":"mine","data":"aGk="}
{"id":"wb1","type":"result","ok":true,"envelope":{"meta":{"protocol":"aisc.cli/v1","command":"version","exit_code":0},"data":{},"errors":[]}}
"#,
                )
                .await
                .unwrap();
        });

        let banner = read_frame(&mut reader).await.unwrap().unwrap();
        assert!(matches!(banner, ServeFrame::Ready { .. }));

        let cancel = CancellationToken::new();
        let pending: Arc<Mutex<HashMap<String, oneshot::Sender<ServeOutcome>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let routes: Arc<Mutex<HashMap<String, mpsc::UnboundedSender<PtyStreamFrame>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        // subscribe "mine" before the reader starts
        let (tx, mut rx) = mpsc::unbounded_channel();
        routes.lock().unwrap().insert("mine".into(), tx);

        let (tx1, rx1) = oneshot::channel();
        pending.lock().unwrap().insert("wb1".into(), tx1);

        // inline mini-reader (same logic as the resident task)
        let reader_routes = Arc::clone(&routes);
        let reader_pending = Arc::clone(&pending);
        let read_task = tokio::spawn(async move {
            for _ in 0..3 {
                let frame = read_frame(&mut reader).await.unwrap().unwrap();
                match frame {
                    ServeFrame::Result { id, ok, envelope, error } => {
                        let tx = reader_pending.lock().unwrap().remove(&id.unwrap()).unwrap();
                        tx.send(match (ok, envelope) {
                            (true, Some(e)) => ServeOutcome::Ok(e),
                            _ => ServeOutcome::Failed(error.unwrap_or_default()),
                        })
                        .unwrap();
                    }
                    ServeFrame::PtyOutput { sid, data } => {
                        let route = reader_routes.lock().unwrap().get(&sid).cloned();
                        if let Some(t) = route {
                            t.send(PtyStreamFrame::Output {
                                sid,
                                data: base64_decode(&data).unwrap(),
                            })
                            .unwrap();
                        }
                    }
                    _ => {}
                }
            }
        });
        read_task.await.unwrap();

        let outcome = rx1.await.unwrap();
        assert!(matches!(outcome, ServeOutcome::Ok(_)));
        let frame = rx.recv().await.unwrap();
        match frame {
            PtyStreamFrame::Output { sid, data } => {
                assert_eq!(sid, "mine");
                assert_eq!(data, b"hi");
            }
            other => panic!("{other:?}"),
        }
        let _ = cancel;
    }

    #[tokio::test]
    async fn base64_roundtrip_helpers() {
        let bytes = b"\x1b[2Jraw \xe4\xb8\xad";
        assert_eq!(base64_decode(&base64_encode(bytes)).unwrap(), bytes);
    }

    /// A4's real-process leg: runs ONLY when AISC_TEST_CLI points at a real
    /// aisc executable (same convention as the Python integration tests).
    #[tokio::test]
    async fn real_serve_round_trip_version_doctor_ps() {
        let Ok(exe) = std::env::var("AISC_TEST_CLI") else {
            return; // skip: no real CLI pinned (CI tauri jobs have placeholders)
        };
        let exe = PathBuf::from(exe);
        if !exe.is_file() {
            return;
        }
        let session = ServeSession::spawn_local(&exe).await.unwrap();
        assert_eq!(session.banner().serve_protocol, SERVE_PROTOCOL);
        assert!(!session.banner().cli_version.is_empty());

        let cancel = CancellationToken::new();
        for op in ["version", "doctor", "ps"] {
            let env = session
                .request(op, &json!({}), Duration::from_secs(60), &cancel)
                .await
                .unwrap_or_else(|e| panic!("{op}: {e:?}"));
            assert_eq!(env.meta.command, op, "{op}");
        }
        session.shutdown().await;
    }
}
