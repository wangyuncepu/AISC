//! 2.1.10 R2: the serve PTY bridge over a REAL ssh link.
//!
//! Gated by `AISC_TEST_SSH` (e.g. `dev@localhost:2222`) PLUS
//! `AISC_TEST_RUNTIME_ID` (a container labeled io.aisc.runtime-id=<id> with
//! /run/aisc/runtime-context.json present). Without both, the test skips —
//! same convention as the Python `AISC_TEST_CLI` integration leg.

use std::sync::Arc;
use std::time::Duration;

use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use workbench_lib::cli::{CliTarget, SshTarget};
use workbench_lib::pty::{spawn_serve_pty_session, PtyEvent};

fn ssh_env() -> Option<(String, u16)> {
    let spec = std::env::var("AISC_TEST_SSH").ok()?;
    // "user@host:port" or "host:port"
    let (rest, port) = spec.rsplit_once(':')?;
    Some((rest.to_string(), port.parse().ok()?))
}

/// F2-A (D-10): the generic `cli` op over a REAL ssh link — the remote
/// control plane. Needs only `AISC_TEST_SSH` (a remote with the v1.3 serve
/// CLI on PATH); no runtime container.
///
/// multi_thread runtime is REQUIRED on Windows: the default current-thread
/// flavor deadlocks in tokio::process child-stdio setup (field evidence
/// 2026-09-09 — banner never consumed, remote serve parked in pipe_read).
/// The app itself rides tauri's multi-thread runtime and is unaffected.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cli_op_over_real_ssh_roundtrip() {
    let Some((host, port)) = ssh_env() else {
        eprintln!("skipping: AISC_TEST_SSH not set");
        return;
    };
    let t = SshTarget {
        host,
        port: Some(port),
        key_path: None,
        extra_args: vec!["-o".into(), "StrictHostKeyChecking=accept-new".into()],
    };

    // The pooled session's banner carries the v1.3 home anchor.
    let pool = workbench_lib::serve::global_pool();
    eprintln!("[probe] spawning pooled session…");
    let session = workbench_lib::serve::pooled_session(pool, &t)
        .await
        .expect("pooled serve session");
    eprintln!("[probe] session up, banner = {:?}", session.banner());
    assert_eq!(session.banner().serve_protocol, workbench_lib::serve::SERVE_PROTOCOL);
    let home = session.banner().home.clone().expect("v1.3 ready home");
    assert!(home.starts_with('/'), "remote home is a POSIX path: {home}");

    // Two sequential control ops ride the SAME pooled connection (no
    // per-op handshake) — the D-10 win this test pins.
    let cancel = CancellationToken::new();
    for cmd in [
        vec!["version".to_string(), "--format".into(), "json".into()],
        vec!["ps".to_string(), "--format".into(), "json".into()],
    ] {
        eprintln!("[probe] cli_op {:?}…", cmd.first());
        let env = workbench_lib::serve::cli_op(
            &t, &cmd, None, Duration::from_secs(20), &cancel, "it-cli-op",
        )
        .await
        .expect("cli op roundtrip");
        eprintln!("[probe] cli_op {:?} -> exit {}", cmd.first(), env.meta.exit_code);
        assert_eq!(env.meta.exit_code, 0, "op {:?} failed: {:?}", cmd.first(), env.errors);
    }
    // A second fetch must reuse the SAME session Arc (pool hit).
    let again = workbench_lib::serve::pooled_session(pool, &t)
        .await
        .expect("pooled again");
    assert!(Arc::ptr_eq(&session, &again), "pool must reuse the live session");

    // The global pool is process-static: evict so the session (and its ssh
    // child, killed on Drop) does not outlive the test binary — the tokio
    // orphan reaper would otherwise hold the runtime open forever.
    workbench_lib::serve::evict_session(pool, &t).await;
}

#[tokio::test]
async fn serve_pty_over_real_ssh_full_roundtrip() {
    let Some((host, port)) = ssh_env() else {
        eprintln!("skipping: AISC_TEST_SSH not set");
        return;
    };
    let Ok(runtime_id) = std::env::var("AISC_TEST_RUNTIME_ID") else {
        eprintln!("skipping: AISC_TEST_RUNTIME_ID not set");
        return;
    };

    let target = CliTarget::Remote(SshTarget {
        host,
        port: Some(port),
        key_path: None,
        extra_args: vec!["-o".into(), "StrictHostKeyChecking=accept-new".into()],
    });

    let session_id = uuid::Uuid::new_v4().to_string();
    let (tx, mut rx) = mpsc::channel::<PtyEvent>(256);

    let (session, _signal) = spawn_serve_pty_session(
        &target,
        &runtime_id,
        &session_id,
        "bash",
        "/tmp", // workspace is only registry-hint material on the remote side
        None,
        80,
        24,
        tx,
        None,
    )
    .await
    .expect("serve PTY over ssh");

    // Phase 1: wait for the bash prompt.
    let mut seen = Vec::new();
    let deadline = Duration::from_secs(45);
    let got_prompt = tokio::time::timeout(deadline, async {
        loop {
            match rx.recv().await.expect("event stream") {
                PtyEvent::Output { bytes, .. } => {
                    use base64::Engine;
                    let raw = base64::engine::general_purpose::STANDARD
                        .decode(&bytes)
                        .unwrap_or_default();
                    seen.extend_from_slice(&raw);
                    if seen.windows(2).any(|w| w == b"$ ") {
                        return true;
                    }
                }
                PtyEvent::Exit { .. } => return false,
                PtyEvent::Error { .. } => return false,
            }
        }
    })
    .await
    .unwrap_or(false);
    assert!(got_prompt, "no bash prompt; captured: {seen:?}");

    // Phase 2: type a command; expect echo + executed output.
    let mut phase2_out: Vec<u8> = Vec::new();
    session
        .write(b"echo RUST-SSH-MARKER\r".to_vec())
        .await
        .expect("write");
    // The executed output line is a CONTIGUOUS "RUST-SSH-MARKER\r\n"; the
    // interactive echo is per-character colored by readline (marker bytes
    // interleaved with escape sequences) — count only contiguous hits.
    let deadline = Duration::from_secs(30);
    let done = tokio::time::timeout(deadline, async {
        loop {
            match rx.recv().await.expect("event stream") {
                PtyEvent::Output { bytes, .. } => {
                    use base64::Engine;
                    let raw = base64::engine::general_purpose::STANDARD
                        .decode(&bytes)
                        .unwrap_or_default();
                    phase2_out.extend_from_slice(&raw);
                    if phase2_out
                        .windows(b"RUST-SSH-MARKER".len())
                        .any(|w| w == b"RUST-SSH-MARKER")
                    {
                        return true;
                    }
                }
                PtyEvent::Exit { .. } => return false,
                PtyEvent::Error { .. } => return false,
            }
        }
    })
    .await
    .unwrap_or(false);
    if !done {
        session.force_kill();
        eprintln!("phase2 dump: {}", String::from_utf8_lossy(&phase2_out));
        panic!("command output (contiguous marker line) missing");
    }

    // Phase 3: G1 verification — the in-band resize fires a real pty.resize
    // frame (a lost frame would surface as no change; any Ok here means the
    // frame path executed end to end through ssh).
    session.resize(100, 30).expect("resize");

    // Phase 4: kill → exit event.
    session.cancel();
    session.force_kill();
    let deadline = Duration::from_secs(30);
    let exited = tokio::time::timeout(deadline, async {
        loop {
            match rx.recv().await {
                Some(PtyEvent::Exit { .. }) => return true,
                Some(_) => continue,
                None => return false,
            }
        }
    })
    .await
    .unwrap_or(false);
    assert!(exited, "no exit event after kill");
}

/// F2-B: remote_browse_core over the real link — the ROOT page AND a
/// second-call descent (the field-reported "cannot go deeper" leg, proven
/// end-to-end: Rust core → pooled fs.list → filtering).
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn remote_browse_core_root_then_descent_over_real_ssh() {
    let Some((host, port)) = ssh_env() else {
        eprintln!("skipping: AISC_TEST_SSH not set");
        return;
    };
    let t = SshTarget {
        host,
        port: Some(port),
        key_path: None,
        extra_args: vec!["-o".into(), "StrictHostKeyChecking=accept-new".into()],
    };

    let root_page = workbench_lib::workspace::remote_browse_core(&t, None)
        .await
        .expect("root browse");
    assert!(root_page.cwd.starts_with('/'));
    assert_eq!(root_page.cwd, root_page.root, "first page opens at the pin root");
    // dirs only, no dotfiles
    assert!(root_page.entries.iter().all(|e| e.is_dir && !e.name.starts_with('.')));

    if let Some(first) = root_page.entries.first() {
        let child = format!("{}/{}", root_page.cwd.trim_end_matches('/'), first.name);
        let sub = workbench_lib::workspace::remote_browse_core(&t, Some(&child))
            .await
            .expect("descent browse");
        assert_eq!(sub.cwd, child, "descent resolves the requested child");
        assert_eq!(sub.root, root_page.root);
    } else {
        eprintln!("root listing empty — descent leg skipped");
    }
    workbench_lib::serve::evict_session(workbench_lib::serve::global_pool(), &t).await;
}
