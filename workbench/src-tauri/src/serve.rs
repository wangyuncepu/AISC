//! 2.1.10 R1 (D-7): the client half of `aisc serve --stdio`.
//!
//! One long-lived serve session per remote target: spawn (direct or wrapped
//! in `ssh`), read the ready banner (protocol handshake), then round-trip
//! request/response frames. R1 is strictly serial — one in-flight request;
//! the wire `id` field already exists so a multiplexing executor can be
//! layered on without a protocol change.
//!
//! Version pairing note: unlike VS Code's commit-equality match (its server
//! and client share one build tree), AISC's compatibility surface is the
//! envelope protocol + capabilities — the banner's `cli_version` is recorded
//! for display/diagnosis, `serve_protocol` is the hard gate.

use std::path::{Path, PathBuf};
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio_util::sync::CancellationToken;

use crate::cli::{CliTarget, Envelope, SshTarget};
use crate::error::WorkbenchError;

/// Serve wire protocol this client speaks (must equal the Python side's
/// `SERVE_PROTOCOL`).
pub const SERVE_PROTOCOL: u64 = 1;

/// The `ready` banner — the session's handshake.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct ReadyBanner {
    #[serde(default)]
    pub serve_protocol: u64,
    #[serde(default)]
    pub cli_version: String,
}

/// One frame from the serve process (`type`-tagged).
///
/// `event` frames are R2+ (PTY push, watcher events); they are decoded here
/// so transport-level handling (skip) is already correct today.
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServeFrame {
    Ready {
        #[serde(default)]
        serve_protocol: u64,
        #[serde(default)]
        cli_version: String,
    },
    Result {
        id: Option<String>,
        ok: bool,
        #[serde(default)]
        envelope: Option<Envelope>,
        #[serde(default)]
        error: Option<String>,
    },
    Log {
        #[serde(default)]
        level: String,
        #[serde(default)]
        line: String,
    },
    Event {
        #[serde(default)]
        event: String,
        #[serde(default)]
        data: serde_json::Value,
    },
}

/// A request frame (client → serve).
#[derive(serde::Serialize)]
struct ServeRequest<'a> {
    id: &'a str,
    op: &'a str,
    args: &'a [String],
}

// ---------------------------------------------------------------------------
// Wire-level helpers (stream-generic: the whole protocol is testable against
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

/// Write one request frame and flush.
async fn write_request<W: AsyncWrite + Unpin>(
    writer: &mut W,
    id: &str,
    op: &str,
    args: &[String],
) -> Result<(), WorkbenchError> {
    let frame = serde_json::to_string(&ServeRequest { id, op, args })
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve encode: {e}")))?;
    let io = async {
        writer.write_all(frame.as_bytes()).await?;
        writer.write_all(b"\n").await?;
        writer.flush().await
    };
    io.await
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("serve write: {e}")))
}

/// Read frames until the matching result arrives (skipping log/event/foreign
/// frames), bounded by `timeout`.
async fn collect_result<R: AsyncRead + Unpin>(
    reader: &mut BufReader<R>,
    want_id: &str,
    timeout: Duration,
    cancel: &CancellationToken,
) -> Result<Envelope, WorkbenchError> {
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        let frame = tokio::select! {
            f = read_frame(reader) => f?,
            _ = tokio::time::sleep_until(deadline) => {
                return Err(WorkbenchError::cli_timeout());
            }
            _ = cancel.cancelled() => {
                return Err(WorkbenchError::cli_cancelled());
            }
        };
        let frame = frame.ok_or_else(|| {
            WorkbenchError::cli_protocol().with_detail("serve closed before the result frame")
        })?;
        match frame {
            ServeFrame::Result { id, ok, envelope, error } => {
                if id.as_deref() != Some(want_id) {
                    continue; // stale frame from an earlier timed-out request
                }
                return match (ok, envelope) {
                    (true, Some(env)) => Ok(env),
                    (true, None) => Err(WorkbenchError::cli_protocol()
                        .with_detail("serve result missing envelope")),
                    (false, _) => Err(WorkbenchError::cli_protocol().with_detail(
                        error.unwrap_or_else(|| "serve op failed".into()),
                    )),
                };
            }
            ServeFrame::Log { .. } | ServeFrame::Event { .. } => continue,
            ServeFrame::Ready { .. } => continue, // mid-session re-banner is legal noise
        }
    }
}

// ---------------------------------------------------------------------------
// The session object.

pub struct ServeSession {
    child: Child,
    stdin: ChildStdin,
    reader: BufReader<ChildStdout>,
    banner: ReadyBanner,
    seq: u64,
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
    /// Workbench will use for real machines (R2+ wires it into runtime).
    pub async fn spawn_ssh(t: &SshTarget) -> Result<Self, WorkbenchError> {
        Self::start(CliTarget::Remote(t.clone())).await
    }

    async fn start(target: CliTarget) -> Result<Self, WorkbenchError> {
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
        let mut session = ServeSession {
            child,
            stdin,
            reader: BufReader::new(stdout),
            banner: ReadyBanner::default(),
            seq: 0,
        };
        session.banner = session.handshake().await?;
        Ok(session)
    }

    /// Read the ready banner and gate on `serve_protocol`.
    async fn handshake(&mut self) -> Result<ReadyBanner, WorkbenchError> {
        let frame = read_frame(&mut self.reader)
            .await?
            .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("serve closed before ready"))?;
        match frame {
            ServeFrame::Ready { serve_protocol, cli_version } => {
                if serve_protocol != SERVE_PROTOCOL {
                    return Err(WorkbenchError::cli_protocol().with_detail(format!(
                        "serve protocol mismatch: client {SERVE_PROTOCOL}, remote {serve_protocol}"
                    )));
                }
                Ok(ReadyBanner { serve_protocol, cli_version })
            }
            _ => Err(WorkbenchError::cli_protocol().with_detail(
                "serve first frame was not ready",
            )),
        }
    }

    pub fn banner(&self) -> &ReadyBanner {
        &self.banner
    }

    /// Round-trip one op. Serial by design (R1); `timeout` bounds the wait
    /// for THIS op's result frame.
    pub async fn request(
        &mut self,
        op: &str,
        args: &[String],
        timeout: Duration,
        cancel: &CancellationToken,
    ) -> Result<Envelope, WorkbenchError> {
        self.seq += 1;
        let id = format!("wb{}", self.seq);
        write_request(&mut self.stdin, &id, op, args).await?;
        collect_result(&mut self.reader, &id, timeout, cancel).await
    }

    /// Graceful stop: stdin EOF tells serve to exit; bounded wait, then kill.
    pub async fn shutdown(mut self) {
        use tokio::io::AsyncWriteExt;
        let _ = self.stdin.shutdown().await;
        let grace = Duration::from_secs(3);
        if tokio::time::timeout(grace, self.child.wait()).await.is_err() {
            let _ = self.child.kill().await;
            let _ = self.child.wait().await;
        }
    }
}

impl Default for ReadyBanner {
    fn default() -> Self {
        ReadyBanner { serve_protocol: 0, cli_version: String::new() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::duplex;

    /// Drive the wire helpers against a duplex pair, mocking the serve side
    /// inline — no process spawn, full protocol coverage.
    fn mock_serve(script: &'static [(&'static str, &'static str)]) -> (tokio::io::DuplexStream, tokio::io::DuplexStream) {
        let _ = script; // responses are pushed by each test
        duplex(4096)
    }

    #[tokio::test]
    async fn handshake_accepts_matching_protocol() {
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        use tokio::io::AsyncWriteExt;
        serve_side
            .write_all(br#"{"type":"ready","serve_protocol":1,"cli_version":"2.1.9.dev0"}"#)
            .await
            .unwrap();
        serve_side.write_all(b"\n").await.unwrap();

        let mut reader = BufReader::new(client_side);
        let frame = read_frame(&mut reader).await.unwrap().unwrap();
        match frame {
            ServeFrame::Ready { serve_protocol, cli_version } => {
                assert_eq!(serve_protocol, 1);
                assert_eq!(cli_version, "2.1.9.dev0");
            }
            other => panic!("expected ready, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn result_round_trip_skips_log_frames() {
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        use tokio::io::AsyncWriteExt;
        tokio::spawn(async move {
            serve_side
                .write_all(
                    br#"{"type":"log","level":"info","line":"noise"}
{"type":"event","event":"x","data":{}}
{"id":"wb1","type":"result","ok":true,"envelope":{"meta":{"protocol":"aisc.cli/v1","command":"version","exit_code":0},"data":{"cli_version":"2.1.9.dev0"},"errors":[]}}
"#,
                )
                .await
                .unwrap();
        });

        let cancel = CancellationToken::new();
        let mut reader = BufReader::new(client_side);
        let env =
            collect_result(&mut reader, "wb1", Duration::from_secs(5), &cancel).await.unwrap();
        assert_eq!(env.meta.command, "version");
        assert_eq!(env.meta.exit_code, 0);
    }

    #[tokio::test]
    async fn result_error_frame_maps_to_protocol_error() {
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        use tokio::io::AsyncWriteExt;
        tokio::spawn(async move {
            serve_side
                .write_all(br#"{"id":"wb1","type":"result","ok":false,"error":"boom"}
"#)
                .await
                .unwrap();
        });
        let cancel = CancellationToken::new();
        let mut reader = BufReader::new(client_side);
        let err = collect_result(&mut reader, "wb1", Duration::from_secs(5), &cancel)
            .await
            .unwrap_err();
        assert!(err.technical_detail.as_deref().unwrap_or("").contains("boom"));
    }

    #[tokio::test]
    async fn stale_id_frames_are_skipped() {
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        use tokio::io::AsyncWriteExt;
        tokio::spawn(async move {
            serve_side
                .write_all(
                    br#"{"id":"stale","type":"result","ok":false,"error":"old"}
{"id":"wb2","type":"result","ok":true,"envelope":{"meta":{"protocol":"aisc.cli/v1","command":"ps","exit_code":0},"data":[],"errors":[]}}
"#,
                )
                .await
                .unwrap();
        });
        let cancel = CancellationToken::new();
        let mut reader = BufReader::new(client_side);
        let env =
            collect_result(&mut reader, "wb2", Duration::from_secs(5), &cancel).await.unwrap();
        assert_eq!(env.meta.command, "ps");
    }

    #[tokio::test]
    async fn eof_before_result_is_error() {
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        drop(serve_side); // serve goes away
        let cancel = CancellationToken::new();
        let mut reader = BufReader::new(client_side);
        let err = collect_result(&mut reader, "wb1", Duration::from_secs(5), &cancel)
            .await
            .unwrap_err();
        assert!(err.technical_detail.as_deref().unwrap_or("").contains("closed"));
    }

    #[tokio::test]
    async fn write_request_frame_shape() {
        // duplex streams are peer-to-peer: what the client writes is read on
        // the serve side (reading your own write would block forever).
        let (mut client_side, mut serve_side) = mock_serve(&[]);
        let args = vec!["--format".to_string(), "json".to_string()];
        write_request(&mut client_side, "u9", "doctor", &args).await.unwrap();
        let mut buf = vec![0u8; 256];
        use tokio::io::AsyncReadExt;
        let n = serve_side.read(&mut buf).await.unwrap();
        let line = String::from_utf8_lossy(&buf[..n]).to_string();
        assert_eq!(line, concat!(r#"{"id":"u9","op":"doctor","args":["--format","json"]}"#, "\n"));
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
        let mut session = ServeSession::spawn_local(&exe).await.unwrap();
        assert_eq!(session.banner().serve_protocol, SERVE_PROTOCOL);
        assert!(!session.banner().cli_version.is_empty());

        let cancel = CancellationToken::new();
        for op in ["version", "doctor", "ps"] {
            let env = session
                .request(op, &[], Duration::from_secs(60), &cancel)
                .await
                .unwrap_or_else(|e| panic!("{op}: {e:?}"));
            assert_eq!(env.meta.command, op, "{op}");
        }
        session.shutdown().await;
    }
}
