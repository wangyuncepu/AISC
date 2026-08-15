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

use std::fs;
use std::path::{Component, Path, PathBuf};

use serde::Serialize;

use crate::error::WorkbenchError;

/// Directories skipped by default in the Explorer (dependency/cache/build —
/// R3-04: a 100k-file fixture must not scan these eagerly).
const DEFAULT_IGNORE: &[&str] = &[
    ".git",
    ".aisc",
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
];

/// Per-entry preview budget (bytes) for `workspace_preview`.
const PREVIEW_BUDGET: u64 = 512 * 1024;

/// A single Explorer tree node (lazy: children fetched on demand).
#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceNode {
    pub relative_path: String,
    pub name: String,
    pub kind: String, // "dir" | "file"
    pub expandable: bool,
    pub artifact_badges: Vec<String>,
    pub change_state: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceListResult {
    pub schema_version: u64,
    pub nodes: Vec<WorkspaceNode>,
    pub next_cursor: Option<String>,
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspacePreviewResult {
    pub relative_path: String,
    pub media_type: String,
    pub size: u64,
    pub text: Option<String>,
    pub base64: Option<String>,
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceCopyResult {
    pub relative_path: String,
    pub absolute_path: String,
}

const LIST_PAGE: usize = 200;

fn is_ignored(name: &str) -> bool {
    DEFAULT_IGNORE.contains(&name)
}

/// Best-effort media type from the extension (text vs binary).
fn media_type_for(path: &Path) -> &'static str {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match ext.as_str() {
        "md" | "markdown" | "txt" | "log" => "text/markdown",
        "json" => "application/json",
        "py" | "rs" | "ts" | "js" | "toml" | "yaml" | "yml" | "sh" | "css" | "html"
        | "vue" | "go" | "c" | "h" | "cpp" => "text/plain",
        "png" | "jpg" | "jpeg" | "gif" | "webp" | "svg" | "ico" => "image/*",
        "pdf" => "application/pdf",
        _ => "application/octet-stream",
    }
}

/// Lazy directory listing: one directory at a time, dirs first, stable sort,
/// paginated, ignoring common dependency/build dirs. Never recurses (R3-04).
pub fn list_workspace(
    workspace: &Path,
    relative_dir: &str,
    cursor: usize,
    include_ignored: bool,
) -> Result<WorkspaceListResult, WorkbenchError> {
    let dir = resolve_contained(workspace, relative_dir)?;
    if !dir.is_dir() {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("not a directory")
        );
    }
    let entries = fs::read_dir(&dir)
        .map_err(|e| WorkbenchError::workspace_invalid().with_detail(format!("read_dir: {e}")))?;

    let mut nodes: Vec<WorkspaceNode> = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if !include_ignored && is_ignored(&name) {
            continue;
        }
        let path = entry.path();
        let is_dir = path.is_dir();
        let rel = if relative_dir.is_empty() {
            name.clone()
        } else {
            format!("{relative_dir}/{name}")
        };
        nodes.push(WorkspaceNode {
            relative_path: rel,
            name,
            kind: if is_dir { "dir".into() } else { "file".into() },
            expandable: is_dir,
            artifact_badges: Vec::new(),
            change_state: "unknown".into(),
        });
    }
    // Dirs first, then files; stable locale-ish sort (case-insensitive).
    nodes.sort_by(|a, b| {
        let a_dir = a.kind == "dir";
        let b_dir = b.kind == "dir";
        b_dir
            .cmp(&a_dir)
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
            .then_with(|| a.name.cmp(&b.name))
    });

    let total = nodes.len();
    let page: Vec<WorkspaceNode> = nodes.into_iter().skip(cursor).take(LIST_PAGE).collect();
    let next_cursor = if cursor + page.len() < total {
        Some((cursor + page.len()).to_string())
    } else {
        None
    };
    Ok(WorkspaceListResult {
        schema_version: 1,
        nodes: page,
        next_cursor,
        truncated: total > LIST_PAGE,
    })
}

/// Resolve a contained target, requiring it to exist (file or dir).
fn resolve_existing(workspace: &Path, relative: &str) -> Result<PathBuf, WorkbenchError> {
    let target = resolve_contained(workspace, relative)?;
    if !target.exists() {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("target does not exist")
        );
    }
    Ok(target)
}

/// Open a file/dir with the system default app (after containment).
pub fn open_path(workspace: &Path, relative: &str) -> Result<(), WorkbenchError> {
    let target = resolve_existing(workspace, relative)?;
    #[cfg(target_os = "windows")]
    let status = std::process::Command::new("cmd")
        .args(["/C", "start", "", &target.to_string_lossy()])
        .status();
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").arg(&target).status();
    #[cfg(all(unix, not(target_os = "macos")))]
    let status = std::process::Command::new("xdg-open").arg(&target).status();
    match status {
        Ok(s) if s.success() => Ok(()),
        Ok(_) => Err(
            WorkbenchError::workspace_invalid().with_detail("system open failed")
        ),
        Err(e) => Err(
            WorkbenchError::workspace_invalid().with_detail(format!("open: {e}"))
        ),
    }
}

/// Reveal a file/dir in the OS file manager (after containment).
pub fn reveal_path(workspace: &Path, relative: &str) -> Result<(), WorkbenchError> {
    let target = resolve_existing(workspace, relative)?;
    #[cfg(target_os = "windows")]
    let status = std::process::Command::new("explorer")
        .arg("/select,")
        .arg(&target)
        .status();
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").args(["-R", &target.to_string_lossy()]).status();
    #[cfg(all(unix, not(target_os = "macos")))]
    let status = std::process::Command::new("xdg-open")
        .arg(target.parent().unwrap_or(&target))
        .status();
    match status {
        Ok(_) => Ok(()),
        Err(e) => Err(
            WorkbenchError::workspace_invalid().with_detail(format!("reveal: {e}"))
        ),
    }
}

/// Read a file for preview, bounded by PREVIEW_BUDGET (R3-11).
pub fn preview_path(workspace: &Path, relative: &str) -> Result<WorkspacePreviewResult, WorkbenchError> {
    let target = resolve_contained(workspace, relative)?;
    if !target.is_file() {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("preview requires a file")
        );
    }
    let metadata = fs::metadata(&target)
        .map_err(|e| WorkbenchError::workspace_invalid().with_detail(format!("stat: {e}")))?;
    let size = metadata.len();
    let truncated = size > PREVIEW_BUDGET;
    let mut buf = Vec::new();
    if !truncated {
        buf = fs::read(&target)
            .map_err(|e| WorkbenchError::workspace_invalid().with_detail(format!("read: {e}")))?;
    } else {
        let mut f = fs::File::open(&target)
            .map_err(|e| WorkbenchError::workspace_invalid().with_detail(format!("open: {e}")))?;
        use std::io::Read;
        let mut limited = f.take(PREVIEW_BUDGET);
        limited
            .read_to_end(&mut buf)
            .map_err(|e| WorkbenchError::workspace_invalid().with_detail(format!("read: {e}")))?;
    }
    let media_type = media_type_for(&target);
    let (text, base64) = if media_type.starts_with("text/")
        || matches!(media_type, "application/json" | "application/octet-stream")
    {
        (Some(String::from_utf8_lossy(&buf).into_owned()), None)
    } else {
        use base64::Engine;
        (None, Some(base64::engine::general_purpose::STANDARD.encode(&buf)))
    };
    Ok(WorkspacePreviewResult {
        relative_path: relative.to_string(),
        media_type: media_type.to_string(),
        size,
        text,
        base64,
        truncated,
    })
}

/// Return the absolute path for copy (contained).
pub fn copy_path(workspace: &Path, relative: &str) -> Result<WorkspaceCopyResult, WorkbenchError> {
    let target = resolve_contained(workspace, relative)?;
    Ok(WorkspaceCopyResult {
        relative_path: relative.to_string(),
        absolute_path: target.to_string_lossy().into_owned(),
    })
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn workspace_list(
    workspace: String,
    relative_dir: String,
    cursor: Option<usize>,
    include_ignored: Option<bool>,
) -> Result<WorkspaceListResult, WorkbenchError> {
    list_workspace(
        Path::new(&workspace),
        &relative_dir,
        cursor.unwrap_or(0),
        include_ignored.unwrap_or(false),
    )
}

#[tauri::command]
pub async fn workspace_open(
    workspace: String,
    relative_path: String,
) -> Result<(), WorkbenchError> {
    open_path(Path::new(&workspace), &relative_path)
}

#[tauri::command]
pub async fn workspace_preview(
    workspace: String,
    relative_path: String,
) -> Result<WorkspacePreviewResult, WorkbenchError> {
    preview_path(Path::new(&workspace), &relative_path)
}

#[tauri::command]
pub async fn workspace_reveal(
    workspace: String,
    relative_path: String,
) -> Result<(), WorkbenchError> {
    reveal_path(Path::new(&workspace), &relative_path)
}

#[tauri::command]
pub async fn workspace_copy_path(
    workspace: String,
    relative_path: String,
) -> Result<WorkspaceCopyResult, WorkbenchError> {
    copy_path(Path::new(&workspace), &relative_path)
}

#[cfg(test)]
mod explorer_tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn listing_is_lazy_ignores_and_sorts() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("node_modules")).unwrap();
        fs::create_dir_all(dir.path().join("src")).unwrap();
        fs::create_dir_all(dir.path().join(".git")).unwrap();
        fs::write(dir.path().join("z_file.txt"), "z").unwrap();
        fs::write(dir.path().join("a_file.txt"), "a").unwrap();

        let res = list_workspace(dir.path(), "", 0, false).unwrap();
        let names: Vec<&str> = res.nodes.iter().map(|n| n.name.as_str()).collect();
        // dirs first (src), then files sorted; .git and node_modules ignored.
        assert_eq!(names, vec!["src", "a_file.txt", "z_file.txt"]);
        assert_eq!(res.nodes[0].kind, "dir");
        assert_eq!(res.nodes[0].expandable, true);
    }

    #[test]
    fn listing_root_does_not_recurse() {
        // A-WX01-1: listing the root must only read the root directory; deeply
        // nested children are NOT scanned until their parent is listed.
        let dir = tempdir().unwrap();
        for i in 0..200 {
            let path = dir.path().join(format!("d{i:03}"));
            fs::create_dir_all(path.join("a/b/c/deep")).unwrap();
            for j in 0..50 {
                fs::write(path.join("a/b/c/deep").join(format!("f{j:02}.txt")), "x").unwrap();
            }
        }
        let res = list_workspace(dir.path(), "", 0, false).unwrap();
        assert_eq!(res.nodes.len(), 200); // exactly the top-level dirs
        assert!(res.nodes.iter().all(|n| n.kind == "dir"));
        // No child of any top-level dir appears.
        assert!(res.nodes.iter().all(|n| !n.relative_path.contains('/')));
    }

    #[test]
    fn listing_paginates() {
        let dir = tempdir().unwrap();
        for i in 0..250 {
            fs::write(dir.path().join(format!("f{i:03}.txt")), "x").unwrap();
        }
        let page1 = list_workspace(dir.path(), "", 0, false).unwrap();
        assert_eq!(page1.nodes.len(), 200);
        assert!(page1.next_cursor.is_some());
        let page2 = list_workspace(dir.path(), "", page1.next_cursor.unwrap().parse().unwrap(), false).unwrap();
        assert_eq!(page2.nodes.len(), 50);
        assert!(page2.next_cursor.is_none());
    }

    #[test]
    fn subdir_listing_uses_relative() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("src/sub")).unwrap();
        fs::write(dir.path().join("src/sub/out.txt"), "x").unwrap();
        let res = list_workspace(dir.path(), "src/sub", 0, false).unwrap();
        assert_eq!(res.nodes.len(), 1);
        assert_eq!(res.nodes[0].relative_path, "src/sub/out.txt");
    }

    #[test]
    fn preview_respects_budget_and_media_type() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("doc.md"), "# hello\nworld\n").unwrap();
        let p = preview_path(dir.path(), "doc.md").unwrap();
        assert_eq!(p.media_type, "text/markdown");
        assert!(p.text.as_deref().unwrap().contains("hello"));
        assert!(p.base64.is_none());
        assert!(!p.truncated);

        fs::write(dir.path().join("big.txt"), "x".repeat((PREVIEW_BUDGET + 10) as usize)).unwrap();
        let big = preview_path(dir.path(), "big.txt").unwrap();
        assert!(big.truncated);
    }

    #[test]
    fn copy_path_returns_contained_absolute() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("a.md"), "x").unwrap();
        let c = copy_path(dir.path(), "a.md").unwrap();
        assert!(c.absolute_path.ends_with("a.md"));
        assert!(copy_path(dir.path(), "../escape").is_err());
    }
}

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
    let ws = canonicalize_lenient(workspace)?;
    if relative.is_empty() {
        // Empty relative means the workspace root itself (e.g. listing it).
        return Ok(ws);
    }
    let rel = validate_relative(relative)?;
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
