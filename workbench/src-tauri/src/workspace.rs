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

use std::collections::HashMap;
use std::fs;
use std::path::{Component, Path, PathBuf};

use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::error::WorkbenchError;

/// Directories skipped by default in the Explorer (dependency/cache/build +
/// container-injected state — R3-04: a 100k-file fixture must not scan these
/// eagerly). Stage 7 note: fresh workspaces no longer gain
/// `.aisc`/`.claude`/`.codex`/`.cc-switch`/`.local` (they live in the data
/// root), but PRE-migration workspaces still have them and they must not
/// flood the tree or the unattributed projection.
const DEFAULT_IGNORE: &[&str] = &[
    ".git",
    ".aisc",
    ".claude",
    ".codex",
    ".cc-switch",
    ".local",
    // F1 (D-10): AISC-managed sync-workspace files — the metadata we write
    // and the container's project-level MCP registration (it lands in the
    // shadow dir via the /root/app mount). Never user content; never shown.
    ".aisc-ssh-workspace.json",
    ".mcp.json",
    "node_modules",
    "target",
    "build",
    "dist",
    "tmp",
    "temp",
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

/// True when a name is in the default ignore set OR a user-configured extra
/// ignore set (the `ui.explorer_ignore` setting). The user set complements the
/// built-ins: e.g. a workspace that keeps `vendor/` or a scratch dir hidden.
fn is_ignored(name: &str, extra_ignore: &[String]) -> bool {
    is_temp_file(name)
        || DEFAULT_IGNORE.contains(&name)
        || extra_ignore.iter().any(|n| n == name)
}

/// Detect atomic-write / editor temp files (`report.md.tmp.1234`, `foo.tmp`,
/// `foo.temp`, `file~`, `.swp`, `.#file`, `~$lock`). These are transient
/// writes that tools rename over the real file; they must not pollute the tree
/// or the unattributed projection. Mirrors the watcher's `is_temp_file`.
fn is_temp_file(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    let lower = name.to_ascii_lowercase();
    if lower.contains(".tmp.") || lower.ends_with(".tmp") || lower.ends_with(".temp") {
        return true;
    }
    name.ends_with('~')
        || name.ends_with(".swp")
        || name.ends_with(".swo")
        || name.starts_with(".#")
        || name.starts_with("~$")
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
/// `extra_ignore` is the user-configured `ui.explorer_ignore` set, merged with
/// the built-in defaults so both hide a path at any depth.
pub fn list_workspace(
    workspace: &Path,
    relative_dir: &str,
    cursor: usize,
    include_ignored: bool,
    extra_ignore: &[String],
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
        if !include_ignored && is_ignored(&name, extra_ignore) {
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

// --- v2.1.7 S2: workspace "forget" (history entry + AISC data-root state) ---
//
// Plan docs/plans/2.1.7-dev-plans 02 §A: ONE backend command performs the
// whole destructive transaction — the frontend never chains removals or
// builds deletion paths itself. Identity is the canonical workspace path →
// workspace key → data-root resolver; the only deletable target is the
// resolver-returned `<data-root>/workspaces/<key>/` subtree. The user's
// on-disk workspace files are NEVER touched. Docker named toolchain volumes
// are NEVER deleted (D12): they are detected, listed, and left for the user.

/// Lease heartbeat freshness bound: 45s TTL (3 × 15s) + slack. A lease file
/// whose mtime is younger counts as a LIVE cross-instance owner and blocks
/// the forget (fail-closed; plan A-21728).
const FORGET_LEASE_FRESH_MS: u64 = 60_000;

/// Known per-workspace state categories under workspaces/<key>/. The preview
/// lists NAMES ONLY — never contents; secrets stay on disk until the purge.
const FORGET_CATEGORIES: &[&str] = &["claude", "codex", "cc-switch", "runtime", "toolchain"];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ForgetPreview {
    pub workspace_path: String,
    pub workspace_key: String,
    /// Some(reason) when the workspace cannot be forgotten right now:
    /// "open-here" (this window holds it) | "lease-active" (another live
    /// instance). None = clear to proceed after user confirmation.
    pub blocked_reason: Option<String>,
    pub data_present: bool,
    pub categories: Vec<String>,
    /// Named toolchain volumes that would be KEPT (D12) — listed so the user
    /// can clean them manually; empty when none exist or the check was
    /// skipped (see warnings).
    pub named_volumes: Vec<String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ForgetResult {
    pub workspace_key: String,
    pub history_removed: bool,
    pub data_removed: bool,
    /// Quarantine dir left behind when the purge failed. The history entry is
    /// already gone at that point, so the state is recoverable manually.
    pub quarantine_left: Option<String>,
    pub named_volumes_kept: Vec<String>,
    pub warnings: Vec<String>,
}

/// Shared gather: identity, target subtree, liveness, state categories.
struct ForgetGather {
    key: String,
    ws_dir: PathBuf,
    root: PathBuf,
    blocked_reason: Option<String>,
    data_present: bool,
    categories: Vec<String>,
    warnings: Vec<String>,
}

fn forget_gather(
    active_in_this_instance: &[String],
    path: &str,
    dirs_override: Option<(PathBuf, PathBuf)>,
) -> Result<ForgetGather, WorkbenchError> {
    let ws_path = Path::new(path);
    let canonical = crate::data_root::canonical_workspace_path(ws_path);
    let key = crate::data_root::workspace_hash_v1(ws_path);
    let (root, ws_dir) = match dirs_override {
        Some(pair) => pair,
        None => {
            let resolved = crate::data_root::resolve_data_root(ws_path)
                .map_err(|e| WorkbenchError::workspace_io().with_detail(e.message()))?;
            let ws_dir = resolved.workspace_dir();
            (resolved.root, ws_dir)
        }
    };

    // Liveness, fail-closed (plan §A.6): this instance's heartbeat beats…
    let mut blocked_reason = None;
    if active_in_this_instance
        .iter()
        .any(|a| a == path || a == &canonical || a == &key)
    {
        blocked_reason = Some("open-here".to_string());
    }
    let mut warnings = Vec::new();
    let lease_file = ws_dir.join("runtime-lease.json");
    if blocked_reason.is_none() && lease_file.exists() {
        let fresh = fs::metadata(&lease_file)
            .and_then(|m| m.modified())
            .map(|mtime| {
                // A future mtime (clock skew) reads as age 0 = fresh.
                mtime
                    .elapsed()
                    .map(|d| d.as_millis() as u64)
                    .unwrap_or(0)
            })
            .map(|age| age < FORGET_LEASE_FRESH_MS)
            .unwrap_or(true); // unreadable lease file: fail-closed
        if fresh {
            blocked_reason = Some("lease-active".to_string());
        } else {
            warnings.push("stale-lease-file-removed-with-state".to_string());
        }
    }

    let data_present = ws_dir.is_dir();
    let mut categories = Vec::new();
    if data_present {
        if let Ok(rd) = fs::read_dir(&ws_dir) {
            let mut others = 0u32;
            for entry in rd.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if FORGET_CATEGORIES.contains(&name.as_str()) {
                    categories.push(name);
                } else if name != "runtime-lease.json" {
                    others += 1;
                }
            }
            if others > 0 {
                categories.push(format!("other:{others}"));
            }
        }
        categories.sort();
    }

    Ok(ForgetGather {
        key,
        ws_dir,
        root,
        blocked_reason,
        data_present,
        categories,
        warnings,
    })
}

/// Best-effort list of the workspace's named toolchain volumes (read-only;
/// D12 keeps them). Failure maps to Err so callers can surface a warning
/// instead of silently claiming "none".
fn named_toolchain_volumes(key: &str) -> Result<Vec<String>, String> {
    let mut cmd = std::process::Command::new("docker");
    cmd.args([
        "volume",
        "ls",
        "--filter",
        &format!("label=io.aisc.workspace-key={key}"),
        "--format",
        "{{.Name}}",
    ]);
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::null());
    cmd.stdin(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(format!("docker volume ls exited {:?}", out.status.code()));
    }
    Ok(String::from_utf8_lossy(&out.stdout)
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect())
}

fn forget_now_ms() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// The transaction core, isolated from Tauri so tests drive it directly.
/// Order (plan §A.3-4): containment symlink check → quarantine rename
/// (same-volume, atomic) → history removal under its cross-process lock
/// (rollback the rename on ANY history failure) → purge the quarantine.
fn forget_execute(
    ws_dir: &Path,
    root: &Path,
    history_dir: &Path,
    path: &str,
    expected_revision: u64,
) -> Result<(ForgetResult, bool), WorkbenchError> {
    let io_err = |e: std::io::Error| WorkbenchError::workspace_io().with_detail(e.to_string());

    if fs::symlink_metadata(ws_dir)
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false)
    {
        // Reparse point at the subtree root: fail-closed (plan §A.2).
        return Err(WorkbenchError::workspace_invalid()
            .with_detail("workspace state dir is a symlink/reparse point — refusing"));
    }

    let mut warnings = Vec::new();
    let mut quarantine_left = None;
    let mut data_removed = false;

    let quarantine_target = if ws_dir.is_dir() {
        let q_dir = root.join(".quarantine");
        fs::create_dir_all(&q_dir).map_err(io_err)?;
        let name = ws_dir
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "workspace".to_string());
        let target = q_dir.join(format!("{name}-{}", forget_now_ms()));
        // 2026-08-27 manual test ("bb"): closing a workspace and forgetting it
        // immediately can race the bind-mount handle teardown — Windows
        // returns a sharing violation on the rename for a few hundred ms.
        // Bounded retry instead of failing the whole transaction.
        let mut renamed = false;
        let mut last_err: Option<std::io::Error> = None;
        for attempt in 0..3 {
            match fs::rename(ws_dir, &target) {
                Ok(()) => {
                    renamed = true;
                    break;
                }
                Err(e) => {
                    if attempt == 2 {
                        last_err = Some(e);
                    } else {
                        std::thread::sleep(std::time::Duration::from_millis(300));
                    }
                }
            }
        }
        if !renamed {
            return Err(WorkbenchError::workspace_io().with_detail(format!(
                "quarantine rename failed: {}",
                last_err.map(|e| e.to_string()).unwrap_or_default()
            )));
        }
        Some(target)
    } else {
        None
    };

    match crate::history::remove_workspace(history_dir, expected_revision, path) {
        Ok((_rev, history_removed)) => {
            if let Some(q) = &quarantine_target {
                match fs::remove_dir_all(q) {
                    Ok(()) => data_removed = true,
                    Err(e) => {
                        quarantine_left =
                            Some(q.to_string_lossy().to_string());
                        warnings.push(format!("quarantine purge failed: {e}"));
                    }
                }
            }
            Ok((
                ForgetResult {
                    workspace_key: String::new(), // filled by the caller
                    history_removed,
                    data_removed,
                    quarantine_left,
                    named_volumes_kept: Vec::new(),
                    warnings,
                },
                quarantine_target.is_some(),
            ))
        }
        Err(e) => {
            // Half-failure semantics: roll the quarantine back so the disk
            // returns to the pre-transaction state (plan §A.4). If even the
            // rollback fails the state stays safe in .quarantine — surface it.
            let rollback_note = match &quarantine_target {
                Some(q) if fs::rename(q, ws_dir).is_err() => format!(
                    " | quarantine rollback failed, state preserved at {}",
                    q.display()
                ),
                _ => String::new(),
            };
            Err(WorkbenchError::workspace_conflict()
                .with_detail(format!("{e}{rollback_note}")))
        }
    }
}

/// Stop+remove AISC-OWNED containers bound to this workspace key before the
/// state-dir rename. Ownership labels (io.aisc.managed + owner=workbench +
/// workspace-key) prove they are ours, and the lease-fresh check earlier
/// already blocks LIVE other instances — their heartbeats keep
/// runtime-lease.json fresh. What reaches here is an ORPHANED session: the
/// app died (e.g. a dev restart) so the lease went stale while the container
/// kept running, holding bind-mount handles that make the rename fail with
/// ACCESS_DENIED (2026-08-27 "bb", os error 5). The label value is the BARE
/// hex key (no sha256-v1: prefix — see the inspect evidence).
fn forget_stop_owned_containers(key: &str) -> Result<u32, String> {
    let bare = key.strip_prefix("sha256-v1:").unwrap_or(key);
    let run = |args: Vec<String>| -> Result<std::process::Output, String> {
        let mut cmd = std::process::Command::new("docker");
        cmd.args(&args);
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::null());
        cmd.stdin(std::process::Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);
        }
        cmd.output().map_err(|e| e.to_string())
    };
    let out = run(vec![
        "ps".into(),
        "-aq".into(),
        "--filter".into(),
        "label=io.aisc.managed=true".into(),
        "--filter".into(),
        format!("label=io.aisc.workspace-key={bare}"),
    ])?;
    if !out.status.success() {
        return Err(format!("docker ps exited {:?}", out.status.code()));
    }
    let ids: Vec<String> = String::from_utf8_lossy(&out.stdout)
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect();
    let mut stopped = 0u32;
    for id in &ids {
        // Best-effort per container; a survivor surfaces via the rename's
        // own io error detail rather than aborting the whole transaction.
        let stop_ok = run(vec!["stop".into(), id.clone()])
            .map(|o| o.status.success())
            .unwrap_or(false);
        let rm_ok = run(vec!["rm".into(), id.clone()])
            .map(|o| o.status.success())
            .unwrap_or(false);
        if stop_ok && rm_ok {
            stopped += 1;
        }
    }
    Ok(stopped)
}

/// Read-only preview for the confirm dialog: what WOULD be deleted, what is
/// kept, and whether anything blocks the operation right now.
#[tauri::command]
pub async fn workspace_forget_preview(
    app: AppHandle,
    path: String,
) -> Result<ForgetPreview, WorkbenchError> {
    let active = {
        let supervisor = app.state::<crate::lease::LeaseSupervisor>();
        supervisor.active_workspaces()
    };
    let g = forget_gather(&active, &path, None)?;
    let mut warnings = g.warnings;
    let named_volumes = match named_toolchain_volumes(&g.key) {
        Ok(v) => v,
        Err(e) => {
            warnings.push(format!("named-volume check skipped: {e}"));
            Vec::new()
        }
    };
    Ok(ForgetPreview {
        workspace_path: path,
        workspace_key: g.key,
        blocked_reason: g.blocked_reason,
        data_present: g.data_present,
        categories: g.categories,
        named_volumes,
        warnings,
    })
}

/// The destructive transaction. ONE command, structured result, idempotent.
#[tauri::command]
pub async fn workspace_forget(
    app: AppHandle,
    path: String,
    expected_history_revision: u64,
) -> Result<ForgetResult, WorkbenchError> {
    let active = {
        let supervisor = app.state::<crate::lease::LeaseSupervisor>();
        supervisor.active_workspaces()
    };
    let g = forget_gather(&active, &path, None)?;
    if let Some(reason) = &g.blocked_reason {
        return Err(WorkbenchError::workspace_conflict().with_detail(reason.clone()));
    }
    // Orphaned-session cleanup (see forget_stop_owned_containers): the live
    // instances are already excluded by the blocked check above.
    let mut orphan_note: Option<String> = None;
    if g.data_present {
        match forget_stop_owned_containers(&g.key) {
            Ok(n) if n > 0 => orphan_note = Some(format!("orphaned-containers-stopped:{n}")),
            Ok(_) => {}
            Err(e) => orphan_note = Some(format!("orphan-container-check-failed:{e}")),
        }
    }
    let history_dir = crate::session::config_dir(&app)?;
    // Bounded auto-retry (2026-08-27 manual test "bb"): a concurrent history
    // save can bump the disk revision between the store's capture and this
    // transaction. forget_execute already rolled the quarantine back on the
    // conflict, so re-running once with the fresh disk revision is safe.
    let mut revision = expected_history_revision;
    let outcome = {
        let mut attempts = 0;
        loop {
            match forget_execute(&g.ws_dir, &g.root, &history_dir, &path, revision) {
                Ok(pair) => break Ok(pair),
                Err(e) if e.code == "WB_ERR_WORKSPACE_CONFLICT" && attempts < 3 => {
                    attempts += 1;
                    let fresh = crate::history::load(&history_dir)
                        .map(|(h, _)| h.revision)
                        .unwrap_or(revision);
                    if fresh == revision {
                        break Err(e); // nothing moved — a real conflict, surface it
                    }
                    revision = fresh;
                }
                Err(e) => break Err(e),
            }
        }
    };
    // Failed transactions land in the shared timeline with their real cause
    // (the dialog only shows the wire shape; 2026-08-27 "bb" chase).
    if let Err(e) = &outcome {
        crate::logging::append_event(
            "error",
            "app",
            "workspace_forget",
            None,
            serde_json::json!({
                "workspace_key": g.key,
                "error_code": e.code,
                "detail": e.technical_detail,
            }),
        );
    }
    let (mut result, _had_data) = outcome?;
    result.workspace_key = g.key.clone();
    // D12: named toolchain volumes are KEPT — list them for manual cleanup.
    match named_toolchain_volumes(&g.key) {
        Ok(v) => result.named_volumes_kept = v,
        Err(e) => result
            .warnings
            .push(format!("named-volume check skipped: {e}")),
    }
    if let Some(note) = orphan_note {
        result.warnings.push(note);
    }
    // Logging redline: workspace absolute paths never enter the log — the
    // key plus booleans are enough to audit the transaction.
    crate::logging::append_event(
        "info",
        "app",
        "workspace_forget",
        None,
        serde_json::json!({
            "workspace_key": g.key,
            "history_removed": result.history_removed,
            "data_removed": result.data_removed,
            "quarantine_left": result.quarantine_left.is_some(),
        }),
    );
    Ok(result)
}

/// Record-only removal (⑧ "clear the moved/deleted record"): drops the
/// history entry, touches NOTHING else.
#[tauri::command]
pub async fn workspace_history_remove(
    app: AppHandle,
    path: String,
    expected_history_revision: u64,
) -> Result<u64, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    let (rev, _removed) =
        crate::history::remove_workspace(&dir, expected_history_revision, &path)
            .map_err(|e| WorkbenchError::workspace_io().with_detail(e.to_string()))?;
    Ok(rev)
}

/// Cheap existence probe for the picker's click-guard (⑧).
#[tauri::command]
pub fn workspace_path_exists(path: String) -> bool {
    fs::metadata(&path).map(|m| m.is_dir()).unwrap_or(false)
}

/// Reveal a DATA-ROOT file (the build log the CLI named in build.start) in
/// the OS file manager. Only paths under the shared data root are accepted —
/// this is never a general-purpose explorer opener (S4 / A-21748).
#[tauri::command]
pub fn workspace_reveal_data_file(path: String) -> Result<(), WorkbenchError> {
    let root = crate::data_root::validate_data_root()
        .map_err(|e| WorkbenchError::workspace_io().with_detail(e.message()))?;
    let target = Path::new(&path);
    if !target.is_absolute() || !target.starts_with(&root) {
        return Err(WorkbenchError::workspace_invalid()
            .with_detail("path is outside the data root"));
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        std::process::Command::new("explorer")
            .arg(format!("/select,{}", target.display()))
            .creation_flags(0x08000000 /* CREATE_NO_WINDOW */)
            .spawn()
            .map_err(|e| WorkbenchError::workspace_io().with_detail(e.to_string()))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .args(["-R", &target.to_string_lossy()])
            .spawn()
            .map_err(|e| WorkbenchError::workspace_io().with_detail(e.to_string()))?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(target.parent().unwrap_or(target))
            .spawn()
            .map_err(|e| WorkbenchError::workspace_io().with_detail(e.to_string()))?;
    }
    Ok(())
}

/// Open a file/dir with the system default app (after containment).
pub fn open_path(workspace: &Path, relative: &str) -> Result<(), WorkbenchError> {
    let target = resolve_existing(workspace, relative)?;
    #[cfg(target_os = "windows")]
    let status = {
        // v2.1.7 S1 (#29): cmd is a console binary — CREATE_NO_WINDOW stops
        // the black flash when opening files from the explorer (same flag as
        // cli.rs:628 / env.rs:189).
        use std::os::windows::process::CommandExt;
        std::process::Command::new("cmd")
            .args(["/C", "start", "", &target.to_string_lossy()])
            .creation_flags(0x08000000 /* CREATE_NO_WINDOW */)
            .status()
    };
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
// Stage 11 (11b): contained filesystem mutations
//
// All four operations share the same safety model:
//   * every path arrives as workspace-relative; the frontend NEVER passes an
//     absolute target (D11-04);
//   * existing paths go through `resolve_contained` (symlink/junction/case/
//     UNC canonicalized and containment-checked);
//   * new targets resolve a CONTAINED parent + a validated single basename,
//     then re-check containment of the joined result;
//   * same-name destinations are always refused (D11-05) — no overwrite, no
//     `(1)` suffixing;
//   * directory copies are bounded and staged into a temp entry that is
//     cleaned up on failure (D11-18).
// ---------------------------------------------------------------------------

/// Result envelope for every Explorer mutation command (02 §2).
#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceMutationResult {
    pub schema_version: u64,
    /// create_file | create_dir | copy | rename
    pub operation: String,
    /// Resulting workspace-relative path.
    pub relative_path: String,
    /// "dir" | "file"
    pub kind: String,
}

/// Bounded recursive copy (D11-18): at most this many entries (files +
/// directories) are copied per operation; exceeding it fails with
/// `workspace_io` and the staged temp target is removed.
const COPY_ENTRY_LIMIT: usize = 10_000;

/// Windows reserved device names — invalid as a file/dir stem in any
/// extension form (`CON`, `CON.txt`, …). Enforced on every platform so a
/// workspace stays portable (D11-22).
const WINDOWS_RESERVED_STEMS: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

fn is_windows_reserved_stem(stem: &str) -> bool {
    WINDOWS_RESERVED_STEMS.contains(&stem.to_ascii_uppercase().as_str())
}

/// Validate a single basename for create/rename (D11-22). Only a basename is
/// accepted: empty/whitespace, `.`/`..`, separators, control chars, Windows
/// reserved stems (with or without extension) and Windows-illegal trailing
/// dots/spaces are rejected. Non-ASCII (e.g. Chinese) is accepted as-is; no
/// unicode normalization is applied.
fn validate_basename(name: &str) -> Result<String, WorkbenchError> {
    let invalid = |detail: &str| {
        Err(WorkbenchError::workspace_invalid().with_detail(detail.to_string()))
    };
    if name.is_empty() || name.trim().is_empty() {
        return invalid("empty name");
    }
    if name == "." || name == ".." {
        return invalid("dot name");
    }
    if name.contains('/') || name.contains('\\') {
        return invalid("path separator in name");
    }
    if name.contains('\0') || name.chars().any(|c| c.is_control()) {
        return invalid("control character in name");
    }
    // Windows filesystems reject names ending in a dot or space; enforcing
    // everywhere keeps the workspace Windows-portable.
    if name.ends_with('.') || name.ends_with(' ') {
        return invalid("trailing dot or space");
    }
    let stem = name.split('.').next().unwrap_or("");
    if is_windows_reserved_stem(stem) {
        return invalid("reserved device name");
    }
    Ok(name.to_string())
}

/// Resolve an existing contained directory (`""` = the workspace root).
/// Symlinked dirs resolving outside the workspace fail inside
/// `resolve_contained` (existing containment policy).
fn resolve_contained_dir(workspace: &Path, relative_dir: &str) -> Result<PathBuf, WorkbenchError> {
    if relative_dir.is_empty() {
        let ws = canonicalize_lenient(workspace)?;
        if !ws.is_dir() {
            return Err(WorkbenchError::workspace_not_found().with_detail("workspace missing"));
        }
        return Ok(ws);
    }
    let dir = resolve_contained(workspace, relative_dir)?;
    if !dir.is_dir() {
        return Err(
            WorkbenchError::workspace_not_found().with_detail("parent is not a directory")
        );
    }
    Ok(dir)
}

/// Map a raw I/O error to a stable mutation error code (D11-20).
fn map_io_err(e: std::io::Error) -> WorkbenchError {
    use std::io::ErrorKind;
    match e.kind() {
        ErrorKind::AlreadyExists => WorkbenchError::workspace_conflict(),
        ErrorKind::NotFound => WorkbenchError::workspace_not_found().with_detail(e.to_string()),
        ErrorKind::PermissionDenied => {
            WorkbenchError::workspace_read_only().with_detail(e.to_string())
        }
        _ => WorkbenchError::workspace_io().with_detail(e.to_string()),
    }
}

/// Exists-check that does NOT follow the final symlink: a dangling or
/// escaping link at the destination must read as "occupied", never be
/// silently clobbered by create/copy.
fn exists_nofollow(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
}

/// Resolve a contained NEW target: `relative_dir` must be an existing
/// contained directory, `name` a validated basename. Returns the joined
/// absolute target (re-canonicalized and containment-checked) plus the
/// resulting workspace-relative display path.
fn resolve_new_target(
    workspace: &Path,
    relative_dir: &str,
    name: &str,
) -> Result<(PathBuf, String), WorkbenchError> {
    let clean = validate_basename(name)?;
    let dir = resolve_contained_dir(workspace, relative_dir)?;
    let target = dir.join(&clean);
    // The joined target may traverse a symlinked parent that escapes the
    // workspace: canonicalize and re-check containment before any write.
    let canon = canonicalize_lenient(&target)?;
    let ws = canonicalize_lenient(workspace)?;
    if !is_inside(&ws, &canon) || path_eq(&canon, &ws) {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("target escapes workspace")
        );
    }
    let relative = if relative_dir.is_empty() {
        clean.clone()
    } else {
        format!("{relative_dir}/{clean}")
    };
    Ok((canon, relative))
}

/// Create an empty file (`dir == false`) or a single directory, refusing to
/// overwrite anything already at the target (D11-05). `create_new` /
/// `create_dir` fail atomically on an occupied target.
pub fn create_entry(
    workspace: &Path,
    relative_dir: &str,
    name: &str,
    dir: bool,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    let (target, relative) = resolve_new_target(workspace, relative_dir, name)?;
    // Occupied target (file, dir, or dangling symlink) -> stable conflict
    // code. Windows reports `create_new` onto an existing DIRECTORY as
    // PermissionDenied (not AlreadyExists), so the explicit check keeps the
    // error code stable; create_new/create_dir below remain the atomic
    // no-clobber backstop for any race in between.
    if exists_nofollow(&target) {
        return Err(WorkbenchError::workspace_conflict());
    }
    if dir {
        fs::create_dir(&target).map_err(map_io_err)?;
    } else {
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(map_io_err)?;
    }
    Ok(WorkspaceMutationResult {
        schema_version: 1,
        operation: if dir { "create_dir" } else { "create_file" }.into(),
        relative_path: relative,
        kind: if dir { "dir" } else { "file" }.into(),
    })
}

/// Rename an entry inside its own parent directory (same-parent only, no
/// move), refusing to clobber an existing sibling. Case-only renames
/// (`a.md` → `A.md`) are allowed on case-insensitive filesystems.
pub fn rename_entry(
    workspace: &Path,
    relative_path: &str,
    new_name: &str,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    // The empty relative IS the workspace root (resolve_contained allows it
    // for listings); renaming/copying the root itself must never happen.
    if relative_path.is_empty() {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("cannot rename the workspace root")
        );
    }
    let source = resolve_existing(workspace, relative_path)?;
    let parent = source
        .parent()
        .ok_or_else(|| WorkbenchError::workspace_invalid().with_detail("no parent"))?
        .to_path_buf();
    let clean = validate_basename(new_name)?;
    let target = parent.join(&clean);
    let canon = canonicalize_lenient(&target)?;
    let ws = canonicalize_lenient(workspace)?;
    if !is_inside(&ws, &canon) || path_eq(&canon, &ws) {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("rename escapes workspace")
        );
    }
    let is_dir = source.is_dir();
    // Same resolved path (case-insensitive on Windows) ⇒ case-only rename;
    // otherwise an occupied destination is a conflict. `fs::rename` replaces
    // an existing target on POSIX, so the pre-check is load-bearing there.
    let same_target = path_eq(&source, &canon);
    if !same_target && exists_nofollow(&canon) {
        return Err(WorkbenchError::workspace_conflict());
    }
    fs::rename(&source, &canon).map_err(map_io_err)?;
    let parent_rel = match relative_path.rfind('/') {
        Some(idx) => relative_path[..idx].to_string(),
        None => String::new(),
    };
    let relative = if parent_rel.is_empty() {
        clean.clone()
    } else {
        format!("{parent_rel}/{clean}")
    };
    Ok(WorkspaceMutationResult {
        schema_version: 1,
        operation: "rename".into(),
        relative_path: relative,
        kind: if is_dir { "dir" } else { "file" }.into(),
    })
}

/// Monotonic suffix for staged copy temp names (best-effort uniqueness
/// within one process).
static COPY_TEMP_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Staged temp name inside the destination directory. The `.tmp` suffix keeps
/// it hidden from the Explorer listing and the watcher's unattributed
/// projection even if a change event fires mid-copy (mirrors `is_temp_file`).
fn copy_temp_name(name: &str) -> String {
    let n = COPY_TEMP_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    format!(
        ".{name}.aisc-copy-{}-{n}.tmp",
        std::process::id()
    )
}

/// Copy a file or a directory (recursively, bounded) inside the workspace.
/// The payload is staged at a temp entry in the destination directory and
/// atomically renamed into place on success; any failure removes the temp
/// entry so no half-written copy survives (R11: 复制中途失败).
///
/// While walking, symlinks/junctions/reparse points are resolved: entries
/// pointing OUTSIDE the workspace are skipped (not followed, not copied,
/// not an error — D11-18); entries pointing inside are copied as their
/// resolved target.
pub fn copy_entry(
    workspace: &Path,
    source_relative: &str,
    destination_relative_dir: &str,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    if source_relative.is_empty() {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("cannot copy the workspace root")
        );
    }
    let source = resolve_existing(workspace, source_relative)?;
    let ws = canonicalize_lenient(workspace)?;
    let dest_dir = resolve_contained_dir(workspace, destination_relative_dir)?;
    let is_dir = source.is_dir();
    // A directory must not be copied into itself (or any descendant).
    if is_dir && (path_eq(&dest_dir, &source) || is_inside(&source, &dest_dir)) {
        return Err(
            WorkbenchError::workspace_invalid().with_detail("cannot copy a directory into itself")
        );
    }
    let name = source
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| WorkbenchError::workspace_invalid().with_detail("unreadable name"))?
        .to_string();
    let final_target = dest_dir.join(&name);
    if exists_nofollow(&final_target) {
        return Err(WorkbenchError::workspace_conflict());
    }
    let temp = dest_dir.join(copy_temp_name(&name));
    let result = if is_dir {
        let mut budget: usize = 0;
        fs::create_dir(&temp).map_err(map_io_err)?;
        copy_dir_recursive(&source, &temp, &ws, &mut budget)
    } else {
        fs::copy(&source, &temp).map(|_| ()).map_err(map_io_err)
    };
    if let Err(e) = result {
        // Failure cleanup: remove the staged temp entry, keep the destination
        // exactly as it was.
        if temp.is_dir() {
            let _ = fs::remove_dir_all(&temp);
        } else {
            let _ = fs::remove_file(&temp);
        }
        return Err(e);
    }
    if let Err(e) = fs::rename(&temp, &final_target) {
        if temp.is_dir() {
            let _ = fs::remove_dir_all(&temp);
        } else {
            let _ = fs::remove_file(&temp);
        }
        return Err(map_io_err(e));
    }
    let relative = if destination_relative_dir.is_empty() {
        name.clone()
    } else {
        format!("{destination_relative_dir}/{name}")
    };
    Ok(WorkspaceMutationResult {
        schema_version: 1,
        operation: "copy".into(),
        relative_path: relative,
        kind: if is_dir { "dir" } else { "file" }.into(),
    })
}

/// Bounded recursive directory copy. Plain dirs/files copy directly; symlink
/// and reparse entries resolve first — outside-workspace targets are skipped,
/// inside-workspace targets copy as their resolved kind.
fn copy_dir_recursive(
    src: &Path,
    dst: &Path,
    ws: &Path,
    budget: &mut usize,
) -> Result<(), WorkbenchError> {
    for entry in fs::read_dir(src).map_err(map_io_err)?.flatten() {
        let ftype = entry.file_type().map_err(map_io_err)?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if ftype.is_dir() {
            *budget += 1;
            check_copy_budget(*budget)?;
            fs::create_dir(&to).map_err(map_io_err)?;
            copy_dir_recursive(&from, &to, ws, budget)?;
        } else if ftype.is_file() {
            *budget += 1;
            check_copy_budget(*budget)?;
            fs::copy(&from, &to).map_err(map_io_err)?;
        } else {
            // Symlink / junction / other reparse point: resolve; a dangling
            // link (canonicalize fails) is skipped like an outside target.
            match fs::canonicalize(&from) {
                Ok(canon) if is_inside(ws, &canon) => {
                    *budget += 1;
                    check_copy_budget(*budget)?;
                    if canon.is_dir() {
                        fs::create_dir(&to).map_err(map_io_err)?;
                        copy_dir_recursive(&canon, &to, ws, budget)?;
                    } else {
                        fs::copy(&canon, &to).map_err(map_io_err)?;
                    }
                }
                _ => {
                    // Outside the workspace or dangling: skip (D11-18).
                    continue;
                }
            }
        }
    }
    Ok(())
}

fn check_copy_budget(used: usize) -> Result<(), WorkbenchError> {
    if used > COPY_ENTRY_LIMIT {
        return Err(WorkbenchError::workspace_io()
            .with_detail(format!("copy exceeds entry budget {COPY_ENTRY_LIMIT}")));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// User-configured explorer ignores from the persisted settings document
/// (`ui.explorer_ignore`). Missing/corrupt settings fall back to empty so the
/// listing still works; the built-in dependency/build ignore always applies.
fn explorer_extra_ignore(app: &AppHandle) -> Vec<String> {
    let Ok(dir) = crate::session::config_dir(app) else {
        return Vec::new();
    };
    match crate::settings::load_settings_document(&dir) {
        Ok(doc) => doc.ui.explorer_ignore,
        Err(_) => Vec::new(),
    }
}

#[tauri::command]
pub async fn workspace_list(
    app: AppHandle,
    workspace: String,
    relative_dir: String,
    cursor: Option<usize>,
    include_ignored: Option<bool>,
) -> Result<WorkspaceListResult, WorkbenchError> {
    // User-configured explorer ignores (`ui.explorer_ignore`) complement the
    // built-in dependency/build list; read from the persisted settings.
    let extra_ignore = explorer_extra_ignore(&app);
    let mut result = list_workspace(
        Path::new(&workspace),
        &relative_dir,
        cursor.unwrap_or(0),
        include_ignored.unwrap_or(false),
        &extra_ignore,
    )?;

    // Annotate listed nodes with manifest artifact badges (Stage 3, WX-01):
    // the Explorer tree shows which files are known Agent deliverables /
    // source changes / generated outputs. This is only a display projection;
    // the CLI registry remains the authoritative fact.
    if let Ok(dir) = crate::session::config_dir(&app) {
        let index = crate::artifact::load_index(&dir);
        let present: HashMap<&str, &crate::artifact::ArtifactRecord> = index
            .artifacts
            .iter()
            .filter(|a| a.state == "present")
            .map(|a| (a.workspace_relative_path.as_str(), a))
            .collect();
        for node in &mut result.nodes {
            if let Some(rec) = present.get(node.relative_path.as_str()) {
                if !node.artifact_badges.iter().any(|b| b.as_str() == rec.kind.as_str()) {
                    node.artifact_badges.push(rec.kind.clone());
                }
                node.change_state = "artifact".to_string();
            }
        }
    }

    Ok(result)
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

// --- Stage 11 (11b): Explorer mutation commands ------------------------------
// The frontend only ever passes workspace-relative paths + a single basename;
// containment and basename validation happen again here regardless of what
// the UI already checked (06 §2).

#[tauri::command]
pub async fn workspace_create_file(
    workspace: String,
    relative_dir: String,
    name: String,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    create_entry(Path::new(&workspace), &relative_dir, &name, false)
}

#[tauri::command]
pub async fn workspace_create_dir(
    workspace: String,
    relative_dir: String,
    name: String,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    create_entry(Path::new(&workspace), &relative_dir, &name, true)
}

#[tauri::command]
pub async fn workspace_copy_entry(
    workspace: String,
    source_relative_path: String,
    destination_relative_dir: String,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    copy_entry(
        Path::new(&workspace),
        &source_relative_path,
        &destination_relative_dir,
    )
}

#[tauri::command]
pub async fn workspace_rename(
    workspace: String,
    relative_path: String,
    new_name: String,
) -> Result<WorkspaceMutationResult, WorkbenchError> {
    rename_entry(Path::new(&workspace), &relative_path, &new_name)
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

        let res = list_workspace(dir.path(), "", 0, false, &[]).unwrap();
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
        let res = list_workspace(dir.path(), "", 0, false, &[]).unwrap();
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
        let page1 = list_workspace(dir.path(), "", 0, false, &[]).unwrap();
        assert_eq!(page1.nodes.len(), 200);
        assert!(page1.next_cursor.is_some());
        let page2 = list_workspace(dir.path(), "", page1.next_cursor.unwrap().parse().unwrap(), false, &[]).unwrap();
        assert_eq!(page2.nodes.len(), 50);
        assert!(page2.next_cursor.is_none());
    }

    #[test]
    fn subdir_listing_uses_relative() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("src/sub")).unwrap();
        fs::write(dir.path().join("src/sub/out.txt"), "x").unwrap();
        let res = list_workspace(dir.path(), "src/sub", 0, false, &[]).unwrap();
        assert_eq!(res.nodes.len(), 1);
        assert_eq!(res.nodes[0].relative_path, "src/sub/out.txt");
    }

    #[test]
    fn listing_hides_transient_temp_files() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("report.md"), "x").unwrap();
        fs::write(dir.path().join("report.md.tmp.1234"), "x").unwrap();
        fs::write(dir.path().join("report.md.tmp"), "x").unwrap();
        fs::write(dir.path().join("notes.md~"), "x").unwrap();
        let res = list_workspace(dir.path(), "", 0, false, &[]).unwrap();
        let names: Vec<&str> = res.nodes.iter().map(|n| n.name.as_str()).collect();
        assert_eq!(names, vec!["report.md"]);
    }

    #[test]
    fn listing_merges_user_exclusions() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("scratch")).unwrap();
        fs::write(dir.path().join("keep.md"), "x").unwrap();
        let extra = vec!["scratch".to_string()];
        let res = list_workspace(dir.path(), "", 0, false, &extra).unwrap();
        assert_eq!(res.nodes.len(), 1);
        assert_eq!(res.nodes[0].name, "keep.md");
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

/// Stage 11 (11b): contained mutation helpers — success, conflict, containment
/// and cleanup paths. All fixtures use tempdirs, never a real user directory.
#[cfg(test)]
mod mutation_tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    fn code_of(r: Result<WorkspaceMutationResult, WorkbenchError>) -> String {
        match r {
            Ok(_) => "OK".into(),
            Err(e) => e.code.clone(),
        }
    }

    #[test]
    fn create_file_and_dir_succeed() {
        let dir = tempdir().unwrap();
        let r = create_entry(dir.path(), "", "notes.md", false).unwrap();
        assert_eq!(r.operation, "create_file");
        assert_eq!(r.relative_path, "notes.md");
        assert_eq!(r.kind, "file");
        assert_eq!(fs::read(dir.path().join("notes.md")).unwrap(), b"");

        let sub = create_entry(dir.path(), "src", "lib", true);
        // Parent "src" does not exist yet -> not_found, no dir created.
        assert_eq!(code_of(sub), "WB_ERR_WORKSPACE_NOT_FOUND");
        assert!(!dir.path().join("src/lib").exists());

        fs::create_dir_all(dir.path().join("src")).unwrap();
        let r2 = create_entry(dir.path(), "src", "lib", true).unwrap();
        assert_eq!(r2.operation, "create_dir");
        assert_eq!(r2.relative_path, "src/lib");
        assert_eq!(r2.kind, "dir");
    }

    #[test]
    fn create_conflict_refuses_overwrite_and_keeps_original() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("a.md"), "original").unwrap();
        let err = create_entry(dir.path(), "", "a.md", false).unwrap_err();
        assert_eq!(err.code, "WB_ERR_WORKSPACE_CONFLICT");
        // The existing file is untouched.
        assert_eq!(fs::read(dir.path().join("a.md")).unwrap(), b"original");

        fs::create_dir(dir.path().join("d")).unwrap();
        let err2 = create_entry(dir.path(), "", "d", true).unwrap_err();
        assert_eq!(err2.code, "WB_ERR_WORKSPACE_CONFLICT");
        // Dir-over-file and file-over-dir also refuse.
        assert_eq!(
            code_of(create_entry(dir.path(), "", "d", false)),
            "WB_ERR_WORKSPACE_CONFLICT"
        );
        assert_eq!(
            code_of(create_entry(dir.path(), "", "a.md", true)),
            "WB_ERR_WORKSPACE_CONFLICT"
        );
    }

    #[test]
    fn invalid_basename_is_rejected() {
        let dir = tempdir().unwrap();
        for bad in [
            "", " ", ".", "..", "a/b", "a\\b", "a\u{0}b", "a\u{7}b", "CON", "con",
            "CON.txt", "NUL.bin", "com1", "LPT9.log", "name.", "name ",
        ] {
            let r = create_entry(dir.path(), "", bad, false);
            assert!(
                r.is_err(),
                "basename {bad:?} must be rejected"
            );
            assert_eq!(code_of(r), "WB_ERR_WORKSPACE_INVALID", "basename {bad:?}");
        }
        // No file was created by any rejected attempt.
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
    }

    #[test]
    fn unicode_and_special_basenames_round_trip() {
        let dir = tempdir().unwrap();
        for name in ["报告 (终稿).md", "文件 名 字.txt", "a(b)c.rs", "日本語メモ.md"] {
            let r = create_entry(dir.path(), "", name, false)
                .unwrap_or_else(|e| panic!("{name} must be creatable: {}", e.code));
            assert_eq!(r.relative_path, name);
        }
        fs::create_dir(dir.path().join("archive")).unwrap();
        fs::write(dir.path().join("报告 (终稿).md"), "x").unwrap();
        let c = copy_entry(dir.path(), "报告 (终稿).md", "archive").unwrap();
        assert_eq!(c.operation, "copy");
        assert_eq!(c.relative_path, "archive/报告 (终稿).md");
        assert!(dir.path().join("archive/报告 (终稿).md").exists());
        let r = rename_entry(dir.path(), "报告 (终稿).md", "新名字 (v2).md").unwrap();
        assert_eq!(r.relative_path, "新名字 (v2).md");
    }

    #[test]
    fn rename_file_and_dir_succeed() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("old.md"), "content").unwrap();
        let r = rename_entry(dir.path(), "old.md", "new.md").unwrap();
        assert_eq!(r.operation, "rename");
        assert_eq!(r.kind, "file");
        assert!(!dir.path().join("old.md").exists());
        assert_eq!(fs::read(dir.path().join("new.md")).unwrap(), b"content");

        fs::create_dir_all(dir.path().join("d/inner")).unwrap();
        fs::write(dir.path().join("d/inner/f.txt"), "x").unwrap();
        let r2 = rename_entry(dir.path(), "d", "renamed").unwrap();
        assert_eq!(r2.kind, "dir");
        assert!(dir.path().join("renamed/inner/f.txt").exists());
        // Resulting relative path keeps the parent prefix.
        let r3 = rename_entry(dir.path(), "renamed/inner/f.txt", "g.txt").unwrap();
        assert_eq!(r3.relative_path, "renamed/inner/g.txt");
    }

    #[test]
    fn rename_conflicts_and_invalid_targets() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("a.md"), "a").unwrap();
        fs::write(dir.path().join("b.md"), "b").unwrap();
        // Occupied sibling destination: refuse, keep both.
        assert_eq!(
            code_of(rename_entry(dir.path(), "a.md", "b.md")),
            "WB_ERR_WORKSPACE_CONFLICT"
        );
        assert_eq!(fs::read(dir.path().join("b.md")).unwrap(), b"b");
        // Traversal / separator / reserved names in new_name.
        assert_eq!(
            code_of(rename_entry(dir.path(), "a.md", "../escape")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(rename_entry(dir.path(), "a.md", "x/y")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(rename_entry(dir.path(), "a.md", "CON")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        // Missing source.
        assert_eq!(
            code_of(rename_entry(dir.path(), "ghost.md", "n.md")),
            "WB_ERR_WORKSPACE_INVALID"
        );
    }

    #[cfg(windows)]
    #[test]
    fn rename_case_only_is_allowed() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("readme.md"), "x").unwrap();
        let r = rename_entry(dir.path(), "readme.md", "README.md").unwrap();
        assert_eq!(r.relative_path, "README.md");
        assert!(dir.path().join("README.md").exists());
    }

    #[test]
    fn copy_file_and_dir_succeed() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("src/nested")).unwrap();
        fs::write(dir.path().join("src/a.txt"), "aaa").unwrap();
        fs::write(dir.path().join("src/nested/b.md"), "bbb").unwrap();
        fs::write(dir.path().join("src/报告 (1).md"), "ccc").unwrap();

        // File copy into a subdirectory.
        let r = copy_entry(dir.path(), "src/a.txt", "src/nested").unwrap();
        assert_eq!(r.operation, "copy");
        assert_eq!(r.relative_path, "src/nested/a.txt");
        assert_eq!(fs::read(dir.path().join("src/nested/a.txt")).unwrap(), b"aaa");

        // Directory copy: recursive, contents preserved, name preserved.
        let r2 = copy_entry(dir.path(), "src/nested", "").unwrap();
        assert_eq!(r2.relative_path, "nested");
        assert_eq!(r2.kind, "dir");
        assert!(dir.path().join("nested/b.md").exists());
        assert!(dir.path().join("nested/a.txt").exists());
        // No staged temp entry survives a successful copy.
        for e in fs::read_dir(dir.path()).unwrap().flatten() {
            let n = e.file_name().to_string_lossy().into_owned();
            assert!(!n.contains("aisc-copy"), "temp leaked: {n}");
        }
    }

    #[test]
    fn copy_conflict_and_invalid_targets() {
        let dir = tempdir().unwrap();
        fs::create_dir_all(dir.path().join("d/sub")).unwrap();
        fs::write(dir.path().join("d/x.txt"), "x").unwrap();

        // Same-name destination refuses and keeps the original.
        assert_eq!(
            code_of(copy_entry(dir.path(), "d/x.txt", "d")),
            "WB_ERR_WORKSPACE_CONFLICT"
        );
        assert_eq!(fs::read(dir.path().join("d/x.txt")).unwrap(), b"x");

        // Copying a directory into itself / a descendant is refused.
        assert_eq!(
            code_of(copy_entry(dir.path(), "d", "d")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(copy_entry(dir.path(), "d", "d/sub")),
            "WB_ERR_WORKSPACE_INVALID"
        );

        // Missing source / missing destination parent.
        assert_eq!(
            code_of(copy_entry(dir.path(), "ghost.txt", "")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(copy_entry(dir.path(), "d/x.txt", "nope")),
            "WB_ERR_WORKSPACE_NOT_FOUND"
        );

        // Traversal in the relative forms is rejected by validate_relative.
        assert_eq!(
            code_of(copy_entry(dir.path(), "../outside.txt", "")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(copy_entry(dir.path(), "d/x.txt", "../other")),
            "WB_ERR_WORKSPACE_INVALID"
        );
    }

    #[test]
    fn copy_cannot_cross_workspaces() {
        // Two distinct temp workspaces: copying from A into B must fail
        // containment before any byte is written — a relative destination can
        // only address A (traversal rejected), so B is unreachable by design.
        let a = tempdir().unwrap();
        let b = tempdir().unwrap();
        fs::write(a.path().join("secret.txt"), "x").unwrap();
        assert_eq!(
            code_of(copy_entry(a.path(), "secret.txt", "../../")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            fs::read_dir(b.path()).unwrap().count(),
            0,
            "nothing may be written into another workspace"
        );
        assert!(a.path().join("secret.txt").exists());
    }

    #[test]
    fn copy_budget_exceeded_cleans_temp() {
        let dir = tempdir().unwrap();
        let big = dir.path().join("big");
        fs::create_dir_all(&big).unwrap();
        fs::create_dir_all(dir.path().join("dest")).unwrap();
        // COPY_ENTRY_LIMIT + 1 files guarantees the budget trips mid-copy.
        for i in 0..=(COPY_ENTRY_LIMIT as u64) {
            fs::write(big.join(format!("f{i:05}.txt")), "x").unwrap();
        }
        let err = copy_entry(dir.path(), "big", "dest").unwrap_err();
        assert_eq!(err.code, "WB_ERR_WORKSPACE_IO");
        // The staged temp entry is removed: the destination stays empty.
        let leftovers: Vec<String> = fs::read_dir(dir.path().join("dest"))
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        assert!(leftovers.is_empty(), "copy left artifacts: {leftovers:?}");
        // The source is untouched.
        assert!(big.join("f00000.txt").exists());
    }

    #[cfg(unix)]
    #[test]
    fn copy_skips_symlinks_escaping_workspace() {
        use std::os::unix::fs::symlink;
        let dir = tempdir().unwrap();
        let outside = tempdir().unwrap();
        // NOTE: the destination must be a SIBLING of the source, never a
        // descendant — copying a dir into its own subtree is (correctly)
        // refused by the into-itself guard. This test only runs on Unix
        // (symlink creation), i.e. on the Linux CI runners — it is invisible
        // to a local Windows `cargo test`.
        fs::create_dir_all(dir.path().join("dup")).unwrap();
        fs::create_dir_all(dir.path().join("proj")).unwrap();
        fs::write(dir.path().join("proj/inside.txt"), "x").unwrap();
        fs::write(outside.path().join("secret.txt"), "top secret").unwrap();
        symlink(outside.path().join("secret.txt"), dir.path().join("proj/escape.txt")).unwrap();
        symlink(dir.path().join("proj/inside.txt"), dir.path().join("proj/alias.txt")).unwrap();

        let r = copy_entry(dir.path(), "proj", "dup").unwrap();
        assert_eq!(r.relative_path, "dup/proj");
        // The outside link was skipped; the inside link copied its target.
        assert!(!dir.path().join("dup/proj/escape.txt").exists());
        assert!(dir.path().join("dup/proj/inside.txt").exists());
        assert_eq!(
            fs::read(dir.path().join("dup/proj/inside.txt")).unwrap(),
            b"x"
        );
        // The secret never landed inside the workspace.
        assert!(!dir.path().join("dup/proj/secret.txt").exists());
        // Copying the escaping symlink itself resolves outside -> invalid.
        assert_eq!(
            code_of(copy_entry(dir.path(), "proj/escape.txt", "dup")),
            "WB_ERR_WORKSPACE_INVALID"
        );
    }

    #[cfg(unix)]
    #[test]
    fn create_and_rename_through_escaping_dir_symlink_fail() {
        use std::os::unix::fs::symlink;
        let dir = tempdir().unwrap();
        let outside = tempdir().unwrap();
        fs::create_dir_all(outside.path().join("victim")).unwrap();
        symlink(outside.path().join("victim"), dir.path().join("linked")).unwrap();
        // A dir symlink resolving outside the workspace is rejected by
        // resolve_contained, so create/rename/copy cannot write through it.
        assert_eq!(
            code_of(create_entry(dir.path(), "linked", "x.txt", false)),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert_eq!(
            code_of(copy_entry(dir.path(), "linked", "")),
            "WB_ERR_WORKSPACE_INVALID"
        );
        assert!(!outside.path().join("victim/x.txt").exists());
    }
}

#[cfg(test)]
mod s2_forget_tests {
    use super::*;
    use std::time::{Duration, SystemTime};

    fn setup(root: &Path, ws_path: &str) -> (PathBuf, PathBuf) {
        let key = crate::data_root::workspace_hash_v1(Path::new(ws_path));
        let dir_name = crate::data_root::workspace_dir_name(&key);
        let ws_dir = root.join("workspaces").join(&dir_name);
        fs::create_dir_all(ws_dir.join("claude")).unwrap();
        fs::write(ws_dir.join("runtime-lease.json"), "{}").unwrap();
        let history_dir = root.join("state");
        fs::create_dir_all(&history_dir).unwrap();
        let history_json = serde_json::json!({
            "schema_version": 2,
            "revision": 0,
            "workspaces": [{ "path": ws_path, "last_used_at": "t", "last_agent": "claude" }]
        });
        fs::write(
            history_dir.join("history.json"),
            serde_json::to_vec_pretty(&history_json).unwrap(),
        )
        .unwrap();
        (ws_dir, history_dir)
    }

    fn quarantine_is_empty(root: &Path) -> bool {
        root.join(".quarantine")
            .read_dir()
            .map(|mut d| d.next().is_none())
            .unwrap_or(true)
    }

    #[test]
    fn forget_removes_state_and_history() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, history_dir) = setup(tmp.path(), "/ws/a");
        let (result, _) = forget_execute(&ws_dir, tmp.path(), &history_dir, "/ws/a", 0).unwrap();
        assert!(result.history_removed);
        assert!(result.data_removed);
        assert!(!ws_dir.exists(), "the AISC state subtree must be gone");
        let h = crate::history::load(&history_dir).unwrap().0;
        assert!(h.workspaces.iter().all(|w| w.path != "/ws/a"));
        assert_eq!(h.revision, 1);
        assert!(quarantine_is_empty(tmp.path()));
    }

    #[test]
    fn forget_is_idempotent_when_nothing_remains() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, history_dir) = setup(tmp.path(), "/ws/b");
        forget_execute(&ws_dir, tmp.path(), &history_dir, "/ws/b", 0).unwrap();
        let (result, _) = forget_execute(&ws_dir, tmp.path(), &history_dir, "/ws/b", 1).unwrap();
        assert!(!result.history_removed);
        assert!(!result.data_removed);
    }

    #[test]
    fn forget_history_conflict_rolls_back_the_rename() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, history_dir) = setup(tmp.path(), "/ws/c");
        // Wrong expected revision -> Conflict, and the quarantine rename must
        // roll back so the disk returns to the pre-transaction state (§A.4).
        let err = forget_execute(&ws_dir, tmp.path(), &history_dir, "/ws/c", 7).unwrap_err();
        assert_eq!(err.code, "WB_ERR_WORKSPACE_CONFLICT");
        assert!(ws_dir.join("claude").exists(), "state subtree must be back");
        assert!(quarantine_is_empty(tmp.path()));
        // The history entry survived untouched.
        let h = crate::history::load(&history_dir).unwrap().0;
        assert!(h.workspaces.iter().any(|w| w.path == "/ws/c"));
        assert_eq!(h.revision, 0);
    }

    #[test]
    fn gather_blocks_on_fresh_lease_and_passes_when_stale() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, _hist) = setup(tmp.path(), "/ws/d");
        let root = tmp.path().to_path_buf();
        let fresh = forget_gather(&[], "/ws/d", Some((root.clone(), ws_dir.clone()))).unwrap();
        assert_eq!(fresh.blocked_reason.as_deref(), Some("lease-active"));

        // Age the lease file past the freshness bound (FileTimes; when the
        // platform refuses, the stale half of the test degrades to a skip).
        let lease = ws_dir.join("runtime-lease.json");
        if let Ok(f) = fs::File::options().write(true).open(&lease) {
            let old = SystemTime::now()
                .checked_sub(Duration::from_secs(FORGET_LEASE_FRESH_MS + 60))
                .unwrap_or(SystemTime::UNIX_EPOCH);
            if f.set_modified(old).is_ok() {
                let stale = forget_gather(&[], "/ws/d", Some((root, ws_dir))).unwrap();
                assert!(stale.blocked_reason.is_none());
                assert!(stale
                    .warnings
                    .iter()
                    .any(|w| w.contains("stale-lease")));
                return;
            }
        }
        eprintln!("skipped stale-lease half: set_modified unavailable");
    }

    #[test]
    fn gather_blocks_when_open_in_this_instance() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, _hist) = setup(tmp.path(), "/ws/e");
        let g = forget_gather(
            &["/ws/e".to_string()],
            "/ws/e",
            Some((tmp.path().to_path_buf(), ws_dir)),
        )
        .unwrap();
        assert_eq!(g.blocked_reason.as_deref(), Some("open-here"));
    }

    #[test]
    fn gather_lists_state_categories_without_contents() {
        let tmp = tempfile::tempdir().unwrap();
        let (ws_dir, _hist) = setup(tmp.path(), "/ws/f");
        fs::create_dir_all(ws_dir.join("toolchain")).unwrap();
        fs::write(ws_dir.join("notes.txt"), "x").unwrap();
        let g = forget_gather(
            &[],
            "/ws/f",
            Some((tmp.path().to_path_buf(), ws_dir)),
        )
        .unwrap();
        // Lease file freshly written -> blocked, but categories still gathered.
        assert!(g.categories.contains(&"claude".to_string()));
        assert!(g.categories.contains(&"toolchain".to_string()));
        assert!(g.categories.iter().any(|c| c.starts_with("other:")));
    }
}
