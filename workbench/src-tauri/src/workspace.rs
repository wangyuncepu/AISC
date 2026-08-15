//! Workspace path containment (Stage 3, ART-05 / R3-01, R3-12).
//!
//! The authoritative gate before any file operation: the Workbench only ever
//! touches a target that resolves inside the canonical workspace, even across
//! symlinks / junctions / case / UNC. The Vue layer never holds a raw absolute
//! path for open/preview — it passes a workspace-relative path and Rust does
//! the containment here.
//!
//! Deleted/missing targets: we canonicalize the deepest existing ancestor
//! (which must be inside the workspace) and append the remaining components,
//! so a missing file cannot smuggle `..` or a symlink escape either.

use std::path::{Component, Path, PathBuf};

use crate::error::WorkbenchError;

/// Path-identity: Windows filesystems are case-insensitive; POSIX are not.
#[allow(dead_code)] // used by is_inside on all platforms
fn path_eq(a: &Path, b: &Path) -> bool {
    #[cfg(windows)]
    {
        // Compare normalized component-wise, case-folded, ignoring any prefix
        // differences that `canonicalize` already resolved.
        let norm = |p: &Path| {
            p.components()
                .filter_map(|c| match c {
                    Component::Normal(s) => Some(s.to_string_lossy().to_lowercase()),
                    _ => None,
                })
                .collect::<Vec<_>>()
        };
        let (na, nb) = (norm(a), norm(b));
        // Both canonicalized paths share the same prefix by construction.
        na == nb
    }
    #[cfg(not(windows))]
    {
        a == b
    }
}

/// Canonicalize `p`; on failure fall back to the deepest existing ancestor so
/// missing targets still get a deterministic, checked base (R3-12 TOCTOU: we
/// re-canonicalize at open time, not trust a cached path).
fn canonicalize_lenient(p: &Path) -> Result<PathBuf, WorkbenchError> {
    if let Ok(c) = std::fs::canonicalize(p) {
        return Ok(c);
    }
    // Walk up to the nearest existing ancestor and rebuild the suffix.
    let mut suffix: Vec<std::ffi::OsString> = Vec::new();
    let mut cur = p.to_path_buf();
    loop {
        if let Ok(c) = std::fs::canonicalize(&cur) {
            let mut out = c;
            for part in suffix.iter().rev() {
                out.push(part);
            }
            return Ok(out);
        }
        match cur.file_name() {
            Some(name) => suffix.push(name.to_os_string()),
            None => break,
        }
        cur.pop();
    }
    Err(WorkbenchError::workspace_invalid().with_detail(format!(
        "cannot canonicalize: {}",
        p.display()
    )))
}

/// True when `target` is strictly inside `base` (component-aware, so
/// `/ws` does not contain `/wspace`).
fn is_inside(base: &Path, target: &Path) -> bool {
    #[cfg(windows)]
    let target_norm: Vec<String> = target
        .components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().to_lowercase()),
            _ => None,
        })
        .collect();
    #[cfg(not(windows))]
    let target_norm: Vec<String> = target
        .components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().into_owned()),
            _ => None,
        })
        .collect();
    #[cfg(windows)]
    let base_norm: Vec<String> = base
        .components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().to_lowercase()),
            _ => None,
        })
        .collect();
    #[cfg(not(windows))]
    let base_norm: Vec<String> = base
        .components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().into_owned()),
            _ => None,
        })
        .collect();

    target_norm.len() > base_norm.len() && target_norm[..base_norm.len()] == base_norm[..]
}

/// Validate a workspace-relative path string (syntax gate, mirrors the CLI).
/// Returns the normalized relative path.
fn validate_relative(raw: &str) -> Result<String, WorkbenchError> {
    if raw.is_empty() || raw.trim().is_empty() {
        return Err(WorkbenchError::workspace_invalid().with_detail("empty path"));
    }
    if raw.contains('\0') || raw.chars().any(|c| c.is_control()) {
        return Err(WorkbenchError::workspace_invalid().with_detail("control characters"));
    }
    if raw.starts_with('/') {
        return Err(WorkbenchError::workspace_invalid().with_detail("absolute path"));
    }
    #[cfg(windows)]
    if raw.contains('\\') || raw.starts_with("\\\\") || raw
        .as_bytes()
        .get(1)
        .is_some_and(|b| *b == b':')
    {
        return Err(WorkbenchError::workspace_invalid().with_detail(
            "backslash / drive / UNC not allowed in relative path",
        ));
    }
    #[cfg(not(windows))]
    if raw.contains('\\') {
        return Err(WorkbenchError::workspace_invalid().with_detail("backslash not allowed"));
    }
    // Traversal: reject `..` at any position.
    for comp in raw.split('/') {
        if comp == ".." {
            return Err(WorkbenchError::workspace_invalid().with_detail("'..' traversal"));
        }
    }
    Ok(raw.trim_matches('/').to_string())
}

/// Resolve a workspace-relative path to a canonical target guaranteed to be
/// inside the canonical workspace.
///
/// * `workspace` — the user's workspace root (not necessarily canonical).
/// * `relative` — workspace-relative path from the artifact/CLI contract.
///
/// Returns the canonical absolute target path. Errors are stable
/// `WB_ERR_WORKSPACE_INVALID` (path policy) — raw OS errors are never surfaced
/// as the primary message.
pub fn resolve_contained(workspace: &Path, relative: &str) -> Result<PathBuf, WorkbenchError> {
    let rel = validate_relative(relative)?;
    let ws = canonicalize_lenient(workspace)?;
    let target = ws.join(&rel);

    // Canonicalize leniently so a *deleted* target still yields a deterministic
    // path whose existing ancestor is checked below.
    let canon = canonicalize_lenient(&target)?;

    if !is_inside(&ws, &canon) {
        return Err(WorkbenchError::workspace_invalid().with_detail(format!(
            "path escapes workspace: {}",
            relative
        )));
    }
    if path_eq(&canon, &ws) {
        return Err(WorkbenchError::workspace_invalid().with_detail("target is the workspace root"));
    }
    Ok(canon)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[cfg(unix)]
    use std::os::unix::fs::symlink;

    #[test]
    fn accepts_simple_relative() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("a.md");
        fs::write(&f, "x").unwrap();
        let got = resolve_contained(dir.path(), "a.md").unwrap();
        assert!(got.ends_with("a.md"));
    }

    #[test]
    fn rejects_traversal_and_absolute() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("sub")).unwrap();
        for bad in ["../escape", "a/../../b", "/etc/passwd", "sub/../../etc"] {
            assert!(resolve_contained(dir.path(), bad).is_err(), "{bad} must fail");
        }
    }

    #[cfg(windows)]
    #[test]
    fn rejects_backslash_drive_unc() {
        let dir = tempdir().unwrap();
        for bad in ["a\\b", "C:/x", "C:\\x", "\\\\server\\share"] {
            assert!(resolve_contained(dir.path(), bad).is_err(), "{bad} must fail");
        }
    }

    #[cfg(unix)]
    #[test]
    fn symlink_escaping_workspace_is_rejected() {
        let dir = tempdir().unwrap();
        let outside = tempdir().unwrap();
        let secret = outside.path().join("secret.txt");
        fs::write(&secret, "top secret").unwrap();
        let link = dir.path().join("evil");
        symlink(&secret, &link).unwrap();
        let err = resolve_contained(dir.path(), "evil").unwrap_err();
        assert_eq!(err.code, "WB_ERR_WORKSPACE_INVALID");
    }

    #[cfg(unix)]
    #[test]
    fn symlink_inside_workspace_is_allowed() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("real")).unwrap();
        let target = dir.path().join("real").join("f.txt");
        fs::write(&target, "x").unwrap();
        symlink(&target, dir.path().join("alias.txt")).unwrap();
        let got = resolve_contained(dir.path(), "alias.txt").unwrap();
        assert!(got.ends_with("f.txt")); // canonical target, inside workspace
    }

    #[test]
    fn deleted_target_is_checked_against_existing_ancestor() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("sub")).unwrap();
        // Missing file inside an existing, checked ancestor.
        let got = resolve_contained(dir.path(), "sub/gone.md").unwrap();
        assert!(got.ends_with("sub/gone.md"));
        // A fully-missing path reconstructs from the canonical workspace root
        // and cannot escape (relative was validated: no '..', no absolute).
        let got2 = resolve_contained(dir.path(), "nope/deep/gone.md").unwrap();
        assert!(got2.ends_with("nope/deep/gone.md"));
    }

    #[test]
    fn component_aware_no_prefix_collision() {
        let dir = tempdir().unwrap();
        // A sibling prefix must NOT be treated as inside the workspace.
        let ws = dir.path().join("ws");
        let sibling = dir.path().join("wspace");
        fs::create_dir_all(&ws).unwrap();
        fs::create_dir_all(&sibling).unwrap();
        // Path inside the *sibling* is not in ws; but the relative form can't
        // express that without '..' (rejected). The component check is what
        // matters: joining "wspace/x" under ws gives ws/wspace/x, which stays
        // inside ws — so it must succeed, NOT prefix-collide with sibling.
        let got = resolve_contained(&ws, "wspace/x").unwrap();
        assert!(got.ends_with("ws/wspace/x"));
    }
}
