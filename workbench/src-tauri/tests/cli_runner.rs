//! Runner IO integration tests. Uses `python3` as the spawned executable
//! (argv-only, no shell) to emit controlled `aisc.cli/v1` envelopes. Real
//! `aisc` coverage is gated on `AISC_TEST_CLI` so default `cargo test` does
//! not require an installed AISC.

use std::path::{Path, PathBuf};
use std::time::Duration;

use tokio_util::sync::CancellationToken;
use workbench_lib::cli::run_control;
use workbench_lib::error::WorkbenchError;

fn python3() -> Option<PathBuf> {
    for name in ["python3", "python"] {
        if let Ok(found) = which_lookup(name) {
            return Some(found);
        }
    }
    None
}

/// Minimal PATH lookup so the test does not pull in a `which` crate.
///
/// Skips 0-byte files: on Windows the Store-installed launcher aliases
/// (`%LOCALAPPDATA%\Microsoft\WindowsApps\<name>.exe`) are 0-byte reparse
/// points that emit nothing when spawned detached — picking one made these
/// tests see empty stdout on Windows while `python3` on CI (Linux) is real.
fn which_lookup(name: &str) -> Result<PathBuf, ()> {
    let path = std::env::var("PATH").map_err(|_| ())?;
    let sep = if cfg!(windows) { ';' } else { ':' };
    let cand_ext = if cfg!(windows) { ".exe" } else { "" };
    for dir in path.split(sep) {
        if dir.is_empty() {
            continue;
        }
        let p = Path::new(dir).join(format!("{name}{cand_ext}"));
        if !p.is_file() {
            continue;
        }
        let non_empty = p.metadata().map(|m| m.len() > 0).unwrap_or(true);
        if non_empty {
            return Ok(p);
        }
    }
    Err(())
}

const VALID_ENVELOPE: &str = r#"{"meta":{"protocol":"aisc.cli/v1","command":"version","exit_code":0,"timestamp":"t","version":"1.0","run_id":"r"},"data":{"cli_version":"1.0","capabilities":{"runtime":"aisc.runtime/v1","session":"aisc.session/v1","providerStatus":"aisc.provider-status/v1","buildEvents":"aisc.build-events/v2"}},"errors":[]}"#;

fn argv_for(script: &str) -> Vec<String> {
    vec!["-c".into(), script.into()]
}

#[tokio::test]
async fn run_control_parses_valid_envelope() {
    let py = match python3() {
        Some(p) => p,
        None => {
            eprintln!("skip: python3 not found");
            return;
        }
    };
    let script = format!("import sys; sys.stdout.write({VALID_ENVELOPE:?})");
    let env = run_control(&py, argv_for(&script), Duration::from_secs(5), CancellationToken::new())
        .await
        .expect("valid envelope");
    assert_eq!(env.meta.command, "version");
}

#[tokio::test]
async fn run_control_bad_json_is_protocol_error() {
    let py = match python3() {
        Some(p) => p,
        None => return,
    };
    let script = "import sys; sys.stdout.write('not json at all')";
    let err = run_control(&py, argv_for(script), Duration::from_secs(5), CancellationToken::new())
        .await
        .unwrap_err();
    assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
}

#[tokio::test]
async fn run_control_exit_code_mismatch_is_protocol_error() {
    let py = match python3() {
        Some(p) => p,
        None => return,
    };
    // Envelope claims exit_code 0 but the process exits 2.
    let script = format!("import sys; sys.stdout.write({VALID_ENVELOPE:?}); sys.exit(2)");
    let err = run_control(&py, argv_for(&script), Duration::from_secs(5), CancellationToken::new())
        .await
        .unwrap_err();
    assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    assert!(err.technical_detail.as_deref().unwrap_or("").contains("mismatch"));
}

#[tokio::test]
async fn run_control_timeout_kills_and_returns_timeout() {
    let py = match python3() {
        Some(p) => p,
        None => return,
    };
    let script = "import time; time.sleep(30)";
    let err = run_control(&py, argv_for(script), Duration::from_millis(200), CancellationToken::new())
        .await
        .unwrap_err();
    assert_eq!(err.code, "WB_ERR_CLI_TIMEOUT");
}

#[tokio::test]
async fn run_control_cancellation_kills_and_returns_cancelled() {
    let py = match python3() {
        Some(p) => p,
        None => return,
    };
    let script = "import time; time.sleep(30)";
    let cancel = CancellationToken::new();
    let cancel2 = cancel.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(150)).await;
        cancel2.cancel();
    });
    let err = run_control(&py, argv_for(script), Duration::from_secs(10), cancel)
        .await
        .unwrap_err();
    assert_eq!(err.code, "WB_ERR_CLI_CANCELLED");
}

#[tokio::test]
async fn run_control_stdout_cap_is_protocol_error() {
    let py = match python3() {
        Some(p) => p,
        None => return,
    };
    // 9 MB > 8 MB cap.
    let script = "import sys; sys.stdout.write('x' * (9 * 1024 * 1024))";
    let err = run_control(&py, argv_for(script), Duration::from_secs(15), CancellationToken::new())
        .await
        .unwrap_err();
    assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    assert!(err.technical_detail.as_deref().unwrap_or("").contains("exceeded"));
}

#[tokio::test]
async fn negotiate_real_aisc() {
    let aisc = match std::env::var("AISC_TEST_CLI") {
        Ok(v) if !v.is_empty() => PathBuf::from(v),
        _ => {
            eprintln!("skip: AISC_TEST_CLI not set");
            return;
        }
    };
    let report = workbench_lib::cli::negotiate(&aisc, CancellationToken::new()).await;
    assert!(
        report.required_ok,
        "expected required capabilities, got error: {:?}",
        report.error.map(|e: WorkbenchError| e.code)
    );
}
