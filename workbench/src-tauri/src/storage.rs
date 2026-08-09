//! Shared durable-file helpers: atomic replace without a delete-first window.
//!
//! Spec: 06-implementation-plan.md §0.1 — "Windows replace 使用可替换既有
//! 文件的原子 API；若平台 API 不可用，采用 `target→backup`、`tmp→target`、
//! 失败恢复 backup 的协议，禁止先删旧文件后无保护 rename。"

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

/// Atomically replace `target` with `bytes` (temp + fsync + rename).
///
/// Protocol when the target already exists (e.g. Windows `rename` refuses to
/// overwrite): `target → backup`, then `tmp → target`; if the second rename
/// fails, restore `backup → target` so there is never a missing-target window.
/// The backup file is our own artifact and is removed on success.
pub fn atomic_replace(target: &Path, bytes: &[u8]) -> io::Result<()> {
    let dir = target.parent().unwrap_or_else(|| Path::new("."));
    let name = target
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file");
    let tmp: PathBuf = dir.join(format!("{name}.tmp"));
    let backup: PathBuf = dir.join(format!("{name}.bak"));

    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }

    if target.exists() {
        // Stale backup from a crashed previous run is ours to replace.
        let _ = fs::remove_file(&backup);
        fs::rename(target, &backup)?;
    }
    match fs::rename(&tmp, target) {
        Ok(()) => {
            let _ = fs::remove_file(&backup);
            Ok(())
        }
        Err(e) => {
            // Restore the previous target; never leave a missing-target window.
            if backup.exists() {
                let _ = fs::rename(&backup, target);
            }
            Err(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn replace_creates_new_file() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("settings.json");
        atomic_replace(&target, b"{\"a\":1}").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"{\"a\":1}");
    }

    #[test]
    fn replace_overwrites_existing_file() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("history.json");
        fs::write(&target, b"old").unwrap();
        atomic_replace(&target, b"new").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"new");
        // No backup/tmp leftovers on success.
        assert!(!dir.path().join("history.json.bak").exists());
        assert!(!dir.path().join("history.json.tmp").exists());
    }

    #[test]
    fn replace_failure_leaves_original_intact() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("settings.json");
        fs::write(&target, b"original").unwrap();
        // Make the temp path uncreatable as a file (directory at tmp path) so
        // the write fails before the target is touched.
        fs::create_dir(dir.path().join("settings.json.tmp")).unwrap();
        assert!(atomic_replace(&target, b"new").is_err());
        assert_eq!(fs::read(&target).unwrap(), b"original");
    }
}
