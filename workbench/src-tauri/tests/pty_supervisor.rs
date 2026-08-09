//! PTY supervisor integration tests. Uses a local `sh` child to exercise the
//! real portable-pty plumbing (openpty, reader chunks, resize, reap, cancel)
//! without Docker. The `aisc session open` path is gated on
//! `AISC_TEST_CLI` + `AISC_TEST_RUNTIME_ID`.

use std::path::Path;
use std::time::{Duration, Instant};

use base64::Engine;
use tokio::sync::mpsc;
use workbench_lib::pty::{spawn_pty_session, PtyEvent, PtySession};

fn decode(bytes: &str) -> Vec<u8> {
    base64::engine::general_purpose::STANDARD
        .decode(bytes)
        .unwrap_or_default()
}

/// Locate a usable `sh`. On Windows the portable-pty ConPTY backend does not
/// PATH-resolve bare program names (CreateProcessW with lpApplicationName),
/// so Git Bash's `sh.exe` must be passed as an absolute path via `SH`.
fn sh_program() -> String {
    if let Ok(p) = std::env::var("SH") {
        if !p.is_empty() {
            return p;
        }
    }
    "sh".into()
}

/// A real terminal emulator answers the cursor-position report query
/// `ESC[6n` with `ESC[row;colR`; bash and msys sh emit it on startup and
/// block until answered. The test harness plays terminal emulator so the
/// child shell can proceed.
fn cursor_query_response(out: &str) -> Option<Vec<u8>> {
    out.contains("\x1b[6n").then(|| b"\x1b[1;1R".to_vec())
}

/// Drain events until an Exit is seen or timeout. Returns (outputs_concat, exit).
async fn drain_until_exit(
    rx: &mut mpsc::Receiver<PtyEvent>,
    session: &PtySession,
    d: Duration,
) -> (String, Option<(Option<i32>, String)>) {
    let deadline = Instant::now() + d;
    let mut out = String::new();
    let mut exit = None;
    while Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_millis(500), rx.recv()).await {
            Ok(Some(PtyEvent::Output { bytes, .. })) => {
                let raw = decode(&bytes);
                let text = String::from_utf8_lossy(&raw);
                if let Some(resp) = cursor_query_response(&text) {
                    let _ = session.write(resp).await;
                }
                out.push_str(&text);
            }
            Ok(Some(PtyEvent::Exit { exit_code, reason })) => {
                exit = Some((exit_code, reason));
                break;
            }
            _ => {}
        }
    }
    (out, exit)
}

#[tokio::test]
async fn echo_child_streams_output_and_exit_code() {
    let (tx, mut rx) = mpsc::channel(256);
    let (session, _signal) = spawn_pty_session(
        Path::new(&sh_program()),
        vec!["-c".into(), "echo hello; sleep 0.2; exit 7".into()],
        80,
        24,
        tx,
    )
    .expect("spawn");

    let (out, exit) = drain_until_exit(&mut rx, &session, Duration::from_secs(3)).await;
    assert!(out.contains("hello"), "output was: {out:?}");
    let (code, reason) = exit.expect("exit event");
    assert_eq!(code, Some(7));
    assert_eq!(reason, "process_exit");
    drop(session);
}

#[tokio::test]
async fn write_input_is_echoed_and_close_is_user_close() {
    let (tx, mut rx) = mpsc::channel(256);
    let (session, signal) = spawn_pty_session(
        Path::new(&sh_program()),
        vec!["-c".into(), "cat".into()],
        80,
        24,
        tx,
    )
    .expect("spawn");

    session
        .write(b"ping\n".to_vec())
        .await
        .expect("write");

    // Wait for "ping" to appear in output (PTY echo + cat stdout).
    let mut got = false;
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_millis(300), rx.recv()).await {
            Ok(Some(PtyEvent::Output { bytes, .. })) => {
                let raw = decode(&bytes);
                let text = String::from_utf8_lossy(&raw);
                if let Some(resp) = cursor_query_response(&text) {
                    let _ = session.write(resp).await;
                }
                if text.contains("ping") {
                    got = true;
                    break;
                }
            }
            Ok(Some(PtyEvent::Exit { .. })) => break,
            _ => {}
        }
    }
    assert!(got, "did not see echoed ping");

    // Close: cancel sets user_close reason; force_kill ends `cat` (no aisc
    // terminate available in this local-child test).
    session.cancel();
    session.force_kill();
    let exit = signal.wait_timeout(Duration::from_secs(3)).await.expect("exit signal");
    assert_eq!(exit.reason, "user_close");
    drop(session);
}

#[tokio::test]
async fn resize_does_not_error() {
    let (tx, mut rx) = mpsc::channel(256);
    let (session, _signal) = spawn_pty_session(
        Path::new(&sh_program()),
        vec!["-c".into(), "sleep 0.3".into()],
        80,
        24,
        tx,
    )
    .expect("spawn");

    session.resize(120, 40).expect("resize");
    // Let the child finish + drain.
    let _ = drain_until_exit(&mut rx, &session, Duration::from_secs(2)).await;
    drop(session);
}

#[tokio::test]
async fn real_aisc_session_open_bash() {
    let aisc = match std::env::var("AISC_TEST_CLI") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_CLI not set");
            return;
        }
    };
    let rid = match std::env::var("AISC_TEST_RUNTIME_ID") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_RUNTIME_ID not set");
            return;
        }
    };

    let (tx, mut rx) = mpsc::channel(256);
    let argv = vec![
        "session".into(),
        "open".into(),
        "--runtime-id".into(),
        rid,
        "--session-id".into(),
        "11111111-1111-4111-8111-111111111111".into(),
        "--agent".into(),
        "bash".into(),
    ];
    let (session, signal) = spawn_pty_session(Path::new(&aisc), argv, 80, 24, tx).expect("spawn");

    session.write(b"echo hi_aisc\n".to_vec()).await.expect("write");

    // Wait for the echo to land. 20s: first docker exec into a cold container
    // on Windows routinely exceeds 10s (observed locally).
    let mut got = false;
    let mut seen = String::new();
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_millis(500), rx.recv()).await {
            Ok(Some(PtyEvent::Output { bytes, .. })) => {
                let raw = decode(&bytes);
                let text = String::from_utf8_lossy(&raw);
                if let Some(resp) = cursor_query_response(&text) {
                    let _ = session.write(resp).await;
                }
                seen.push_str(&text);
                if text.contains("hi_aisc") {
                    got = true;
                    break;
                }
            }
            Ok(Some(PtyEvent::Exit { exit_code, reason })) => {
                seen.push_str(&format!("\n[EXIT {exit_code:?} {reason}]"));
                break;
            }
            _ => {}
        }
    }
    assert!(got, "did not see hi_aisc; output was: {seen:?}");

    session.write(b"exit\n".to_vec()).await.expect("write exit");
    let exit = signal.wait_timeout(Duration::from_secs(5)).await.expect("bash exit");
    assert_eq!(exit.reason, "process_exit");
    drop(session);
}
#[tokio::test]
async fn reopen_25_cycles_leaves_no_orphan_sessions() {
    // A-INFRA-2 (03 §3.3.5): repeated natural-exit + reopen on the same pane
    // must not leak children or session records. Gated on the real CLI +
    // runtime like real_aisc_session_open_bash; registry boundedness itself
    // is covered by the sweep unit tests (TTL 60s, max 32/runtime).
    let aisc = match std::env::var("AISC_TEST_CLI") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_CLI not set");
            return;
        }
    };
    let rid = match std::env::var("AISC_TEST_RUNTIME_ID") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_RUNTIME_ID not set");
            return;
        }
    };
    let cycles = 25u32;
    for i in 0..cycles {
        let sid = format!("{:08x}-0000-4000-8000-{:012x}", 0xA0000000 + i, i);
        let (tx, mut rx) = mpsc::channel(256);
        let argv = vec![
            "session".into(),
            "open".into(),
            "--runtime-id".into(),
            rid.clone(),
            "--session-id".into(),
            sid.clone(),
            "--agent".into(),
            "bash".into(),
        ];
        let (session, signal) = spawn_pty_session(Path::new(&aisc), argv, 80, 24, tx).expect("spawn");
        // Answer the cursor query if the container bash emits one.
        let writer = session.writer_sender();
        let answer = tokio::spawn(async move {
            loop {
                match tokio::time::timeout(Duration::from_millis(300), rx.recv()).await {
                    Ok(Some(PtyEvent::Output { bytes, .. })) => {
                        let raw = decode(&bytes);
                        let text = String::from_utf8_lossy(&raw);
                        if let Some(resp) = cursor_query_response(&text) {
                            let _ = writer.send(resp).await;
                        }
                    }
                    Ok(Some(PtyEvent::Exit { .. })) | Ok(None) => break,
                    _ => {}
                }
            }
        });
        session.write(b"exit
".to_vec()).await.expect("write exit");
        let exit = signal
            .wait_timeout(Duration::from_secs(10))
            .await
            .unwrap_or_else(|| panic!("cycle {i}: bash did not exit"));
        assert_eq!(exit.reason, "process_exit", "cycle {i} exit reason");
        answer.abort();
        drop(session);
    }
    // Final probe: a fresh session still opens and exits cleanly.
    let sid = format!("{:08x}-0000-4000-8000-{:012x}", 0xA0000000 + cycles, cycles);
    let (tx, mut rx) = mpsc::channel(256);
    let argv = vec![
        "session".into(),
        "open".into(),
        "--runtime-id".into(),
        rid,
        "--session-id".into(),
        sid,
        "--agent".into(),
        "bash".into(),
        "--workspace".into(),
        std::env::temp_dir().to_string_lossy().into_owned(),
    ];
    let (session, signal) = spawn_pty_session(Path::new(&aisc), argv, 80, 24, tx).expect("final spawn");
    let writer = session.writer_sender();
    tokio::spawn(async move {
        loop {
            match tokio::time::timeout(Duration::from_millis(300), rx.recv()).await {
                Ok(Some(PtyEvent::Output { bytes, .. })) => {
                    let raw = decode(&bytes);
                        let text = String::from_utf8_lossy(&raw);
                    if let Some(resp) = cursor_query_response(&text) {
                        let _ = writer.send(resp).await;
                    }
                }
                _ => break,
            }
        }
    });
    session.write(b"exit
".to_vec()).await.expect("final write exit");
    let exit = signal.wait_timeout(Duration::from_secs(10)).await.expect("final bash exit");
    assert_eq!(exit.reason, "process_exit");
    drop(session);
    eprintln!("reopen {cycles} cycles: PASSED");
}
#[tokio::test]
async fn perf_runtime_stop_with_eight_sessions() {
    // G-07 perf evidence (03 §4.2): runtime stop with 8 live container
    // sessions, measured via the real CLI (--grace 3). Gated on the real
    // CLI + runtime. Prints the stop duration; the P95 gate (7s for 8
    // sessions) is judged from the recorded samples.
    let aisc = match std::env::var("AISC_TEST_CLI") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_CLI not set");
            return;
        }
    };
    let rid = match std::env::var("AISC_TEST_RUNTIME_ID") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            eprintln!("skip: AISC_TEST_RUNTIME_ID not set");
            return;
        }
    };
    let ws = std::env::var("AISC_TEST_WORKSPACE")
        .unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into_owned());
    let mut sessions = Vec::new();
    for i in 0..8usize {
        let sid = format!("{:08x}-0000-4000-8000-{:012x}", 0xB0000000 + i as u32, i);
        let (tx, _rx) = mpsc::channel(256);
        let argv = vec![
            "session".into(),
            "open".into(),
            "--runtime-id".into(),
            rid.clone(),
            "--session-id".into(),
            sid,
            "--agent".into(),
            "bash".into(),
        ];
        let (session, _signal) = spawn_pty_session(Path::new(&aisc), argv, 80, 24, tx).expect("spawn");
        sessions.push(session);
    }
    tokio::time::sleep(Duration::from_millis(500)).await; // let execs settle
    let t0 = std::time::Instant::now();
    let out = std::process::Command::new(&aisc)
        .args(["runtime", "stop", "--runtime-id", &rid, "--workspace", &ws, "--grace", "3", "--format", "json"])
        .output()
        .expect("runtime stop");
    let elapsed = t0.elapsed();
    eprintln!("runtime stop with 8 sessions: {elapsed:?} (exit {})", out.status);
    drop(sessions); // PTY handles close; children already gone with the container
    assert!(out.status.success(), "runtime stop failed: {}", String::from_utf8_lossy(&out.stderr));
}
