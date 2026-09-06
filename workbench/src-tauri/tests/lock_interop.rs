//! PERF P5a (D-13): cross-runtime lock interop experiment.
//!
//! Python's cross-process file lock (aisc.adapters.data_root_store.file_lock:
//! `msvcrt.locking(LK_NBLCK, 1)` — byte range [0,1) — on Windows;
//! `fcntl.flock(LOCK_EX)` on POSIX) vs Rust fs4 (LockFileEx over [0,u64::MAX)
//! on Windows; BSD `flock` on POSIX). Same byte-range manager on Windows and
//! the same flock syscall on POSIX mean both directions SHOULD exclude each
//! other — but "should" is exactly what this experiment replaces with a
//! pinned fact (POSIX flock-vs-fcntl divergence is the classic trap that
//! makes paper reasoning worthless here).
//!
//! P5b (lease heartbeat direct write, O6b) is GATED on this file: if either
//! direction fails, P5b must take the no-lock + mtime-guard fallback path.
//!
//! Skips (pass-with-note) when no python can be resolved — CI images ship
//! one, dev boxes always have one.

use fs4::fs_std::FileExt;
use std::fs;
use std::process::Command;

fn python() -> Option<std::path::PathBuf> {
    for name in ["python", "python3"] {
        if let Ok(out) = Command::new(name).arg("--version").output() {
            if out.status.success() {
                return Some(name.into());
            }
        }
    }
    None
}

/// Mirrors data_root_store.file_lock's Windows primitive exactly: lock byte
/// range [0,1) non-blocking. Exit 0 = acquired, 3 = blocked (OSError).
const PY_TRY_LOCK: &str = r#"
import os, sys
lock_path = sys.argv[1]
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
try:
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(3)
sys.exit(0)
"#;

/// Take the lock the same way, then hold it until the release marker appears.
const PY_TAKE_LOCK: &str = r#"
import os, sys, time
lock_path, hold_marker, release_wait = sys.argv[1], sys.argv[2], sys.argv[3]
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
if sys.platform == "win32":
    import msvcrt
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)
open(hold_marker, "w").close()
deadline = time.time() + 30
while not os.path.exists(release_wait) and time.time() < deadline:
    time.sleep(0.05)
"#;

#[test]
fn rust_lock_blocks_python_and_releases() {
    let Some(py) = python() else {
        eprintln!("skip: no python resolvable");
        return;
    };
    let dir = tempfile::tempdir().unwrap();
    let lock = dir.path().join("interop.lock");
    fs::File::create(&lock).unwrap();

    let f = fs::OpenOptions::new()
        .read(true).write(true).open(&lock).unwrap();
    assert!(
        f.try_lock_exclusive().unwrap(),
        "rust must acquire the fresh lock"
    );

    let out = Command::new(&py)
        .arg("-c").arg(PY_TRY_LOCK).arg(&lock)
        .output().unwrap();
    assert_eq!(
        out.status.code(),
        Some(3),
        "python must be BLOCKED by the rust-held lock (interop broken): {}",
        String::from_utf8_lossy(&out.stderr)
    );

    f.unlock().unwrap();
    let out = Command::new(&py)
        .arg("-c").arg(PY_TRY_LOCK).arg(&lock)
        .output().unwrap();
    assert_eq!(
        out.status.code(),
        Some(0),
        "python must acquire after rust releases: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn python_lock_blocks_rust_and_releases() {
    let Some(py) = python() else {
        eprintln!("skip: no python resolvable");
        return;
    };
    let dir = tempfile::tempdir().unwrap();
    let lock = dir.path().join("interop.lock");
    fs::File::create(&lock).unwrap();
    let hold = dir.path().join("held");
    let release = dir.path().join("release");

    let mut child = Command::new(&py)
        .arg("-c").arg(PY_TAKE_LOCK)
        .arg(&lock).arg(&hold).arg(&release)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn().unwrap();
    for _ in 0..200 {
        if hold.exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(25));
    }
    assert!(hold.exists(), "python child never took the lock");

    let f = fs::OpenOptions::new()
        .read(true).write(true).open(&lock).unwrap();
    assert!(
        !f.try_lock_exclusive().unwrap(),
        "rust must be BLOCKED by the python-held lock (interop broken)"
    );

    fs::write(&release, b"1").unwrap();
    child.wait().unwrap();
    assert!(
        f.try_lock_exclusive().unwrap(),
        "rust must acquire after python releases"
    );
    f.unlock().unwrap();
}
