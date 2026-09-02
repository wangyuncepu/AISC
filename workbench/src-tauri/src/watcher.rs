//! Workspace change watcher (Stage 3, 3d, WX-03 / R3-03, R3-08).
//!
//! Watches the workspace and produces ONLY an unattributed projection
//! (`workspace_change`) — it never guesses Agent provenance (D3-03). Changes
//! are debounced/coalesced, the raw event channel is bounded, and an overflow
//! marks the Explorer stale + triggers a bounded rescan instead of losing
//! events silently (R3-08). `dispose` stops everything.

use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::sync::mpsc;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use notify::{Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::error::WorkbenchError;

const DEBOUNCE: Duration = Duration::from_millis(300);
const MAX_BATCH: usize = 200;
const RAW_CHANNEL_CAP: usize = 1024;

/// One unattributed workspace change (never provenance=manifest).
#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceChange {
    pub relative_path: String,
    pub change_type: String,
    pub kind: String,
    pub revision: u64,
}

/// A coalesced batch emitted to the frontend. IDEA-3 (3e): carries the
/// WATCHED WORKSPACE path so the frontend can attribute batches correctly
/// while rapidly switching workspaces (the watcher is a single instance
/// following the ACTIVE workspace; without this field a batch emitted right
/// after a switch could be applied to the wrong tree). `#[serde(default)]`
/// keeps old payloads/tests constructing without it deserializable.
#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceChangeBatch {
    #[serde(default)]
    pub workspace: String,
    pub changes: Vec<WorkspaceChange>,
    pub revision: u64,
    pub overflow: bool,
    pub stale: bool,
}

/// Dedup + order changes within a debounce window.
#[derive(Debug, Default)]
struct ChangeBatcher {
    // BTreeMap path -> (type, kind); types MERGE within the window (see
    // merge_change_type — last-write-wins mislabeled agent-created files).
    by_path: std::collections::BTreeMap<String, (String, String)>,
    overflow: bool,
}

/// O9-反馈 #1b (2026-09-02): merge two change types for the same path inside
/// one debounce window. Codex writes a brand-new file as `Create` followed by
/// `Modify(Data)` — last-write-wins labeled it "modified". Birth is sticky:
/// a path created in this window stays "created" no matter what the writer
/// follows up with; deletions are terminal; renames outrank plain writes.
fn merge_change_type(prev: &str, next: &str) -> String {
    match (prev, next) {
        // A later birth always wins (delete-and-recreate included)…
        (_, "created") => "created".into(),
        // …but a deletion is terminal for the window (born-then-removed).
        (_, "deleted") => "deleted".into(),
        ("deleted", _) => "deleted".into(),
        // Birth is sticky: later writes/rename-To keep "created".
        ("created", _) => "created".into(),
        ("renamed", _) | (_, "renamed") => "renamed".into(),
        _ => next.to_string(),
    }
}

/// Directories outrank files when both kinds are seen for one path.
fn merge_kind(prev: &str, next: &str) -> String {
    if prev == "dir" || next == "dir" {
        "dir".into()
    } else {
        next.to_string()
    }
}

impl ChangeBatcher {
    fn push(&mut self, path: String, change_type: String, kind: String) {
        match self.by_path.get_mut(&path) {
            Some((t, k)) => {
                *t = merge_change_type(t, &change_type).to_string();
                *k = merge_kind(k, &kind).to_string();
            }
            None => {
                self.by_path.insert(path, (change_type, kind));
            }
        }
    }

    fn mark_overflow(&mut self) {
        self.overflow = true;
    }

    fn drain(&mut self, revision: u64) -> WorkspaceChangeBatch {
        let changes = std::mem::take(&mut self.by_path)
            .into_iter()
            .map(|(relative_path, (change_type, kind))| WorkspaceChange {
                relative_path,
                change_type,
                kind,
                revision,
            })
            .collect();
        let overflow = self.overflow;
        self.overflow = false;
        WorkspaceChangeBatch {
            // Stamped by the caller (debounce_loop knows the watched path).
            workspace: String::new(),
            changes,
            revision,
            overflow,
            stale: overflow,
        }
    }
}

/// Directories whose changes are NOT surfaced to the Explorer (dependency /
/// cache / build — mirrors the listing ignore; otherwise dev-server writes
/// would fire the watcher constantly and re-load the tree (observed sluggish).
const WATCH_IGNORE: &[&str] = &[
    ".git",
    ".aisc",
    ".claude",
    ".codex",
    ".cc-switch",
    ".local",
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

/// True when a workspace-relative path is under a WATCH_IGNORE directory
/// (or a user-configured `ui.explorer_ignore` name). Mirrors the Explorer
/// listing ignore: any path component may be a dependency/cache/build/state
/// directory, so nested `src/node_modules/...` is also suppressed instead of
/// reloading the tree on every dev-server write.
fn is_watch_ignored(relative: &str, extra_ignore: &[String]) -> bool {
    relative
        .split('/')
        .any(|part| WATCH_IGNORE.contains(&part) || extra_ignore.iter().any(|n| n == part))
        || is_temp_file(relative)
}

/// Detect atomic-write / editor temp files. Tools write `report.md.tmp.1234`
/// (or `report.md.tmp`, `report.md~`, `.#report.md`, `report.md.swp`) and then
/// rename over the real file; without this the watcher would surface every
/// transient temp as an unattributed change in the Artifacts panel even though
/// the file never persists in the tree. Matches the Explorer listing ignore so
/// both stay in sync.
fn is_temp_file(relative: &str) -> bool {
    let name = relative.rsplit('/').next().unwrap_or(relative);
    if name.is_empty() {
        return false;
    }
    // `foo.tmp.1234` / `foo.tmp` / `foo.temp` (and case variants).
    let lower = name.to_ascii_lowercase();
    if lower.contains(".tmp.") || lower.ends_with(".tmp") || lower.ends_with(".temp") {
        return true;
    }
    // Editor/backup artifacts: vim `file~`/`.swp`, emacs `.#file`, atomic writer
    // `.#foo`, `~$foo` (Office lock files).
    name.ends_with('~')
        || name.ends_with(".swp")
        || name.ends_with(".swo")
        || name.starts_with(".#")
        || name.starts_with("~$")
}

/// Classify ONE changed path into a stable change type.
///
/// 2026-08-28 manual test ("mv a b"): a rename arrives as TWO events —
/// `Name(From)` carrying the OLD path and `Name(To)` the NEW (or one `Both`
/// event with both paths). Classifying the old path as "renamed" is wrong:
/// it no longer exists — its honest type is "deleted". Only the NEW path is
/// "renamed".
fn change_type_of_path(kind: &EventKind, index: usize, total: usize) -> &'static str {
    use notify::event::*;
    match kind {
        EventKind::Create(_) => "created",
        EventKind::Remove(_) => "deleted",
        EventKind::Modify(ModifyKind::Name(role)) => match role {
            RenameMode::From => "deleted",
            RenameMode::To => "renamed",
            RenameMode::Both => {
                if total == 2 && index == 0 {
                    "deleted"
                } else {
                    "renamed"
                }
            }
            _ => "renamed",
        },
        EventKind::Modify(_) => "modified",
        _ => "changed",
    }
}

/// O9-反馈 #8 (2026-09-02): atomic-write (temp rename) tracker.
///
/// Agents (claude/codex) save files via `write temp -> rename over the real
/// name`. notify reports the rename-From carrying the TEMP path (which
/// `is_temp_file` filters) and the rename-To carrying the REAL path — the
/// orphan To classified as "renamed", putting a false "⇄ 移动" badge on a
/// brand-new file. Remember the filtered temp-From; a rename-To arriving
/// within the window is a file BIRTH ("created"). A real `mv a b` has its
/// From NOT filtered (no marker is set), so it stays "renamed".
#[derive(Debug, Default)]
struct TempRenameTracker {
    at: Option<std::time::Instant>,
}

impl TempRenameTracker {
    /// A rename-From whose path was dropped by the temp filter just fired.
    fn note_temp_from(&mut self) {
        self.at = Some(std::time::Instant::now());
    }

    /// Reclassify a rename-To: "created" when it completes a filtered
    /// temp-rename (consumes the marker); otherwise the raw type stands.
    fn classify_to(&mut self, raw: &'static str) -> &'static str {
        match self.at {
            Some(t) if t.elapsed() < std::time::Duration::from_millis(1000) => {
                self.at = None;
                "created"
            }
            _ => raw,
        }
    }
}

/// Best-effort target kind. We only need this reliably for newly-created
/// directories so the frontend can list their children immediately.
fn change_kind_of(kind: &EventKind) -> &'static str {
    use notify::event::*;
    match kind {
        EventKind::Create(CreateKind::Folder) => "dir",
        EventKind::Create(_) => "file",
        EventKind::Modify(ModifyKind::Name(_)) | EventKind::Modify(_) => "file",
        EventKind::Remove(_) => "file",
        _ => "unknown",
    }
}

/// Compute the workspace-relative path of a changed path.
///
/// notify may report extended-length Windows verbatim paths, or paths
/// with different case/prefixes than the workspace string. Prefer the lexical
/// component diff; if the prefixes do not match, retry with both sides
/// canonicalized (the changed target usually still exists at event time).
fn relative_of(workspace: &Path, path: &Path) -> Option<String> {
    let ws = pathdiff(workspace, path).or_else(|| {
        let cws = fs::canonicalize(workspace).ok()?;
        let cpath = fs::canonicalize(path).ok()?;
        pathdiff(&cws, &cpath)
    })?;
    if ws.is_empty() {
        return None; // the workspace root itself
    }
    Some(ws.replace('\\', "/"))
}

/// Minimal `pathdiff`: relative path from `base` to `target`, only when
/// `target` is strictly inside `base` (component-wise). Returns None for the
/// root itself and for any path outside the base.
fn pathdiff(base: &Path, target: &Path) -> Option<String> {
    let b = base.components().collect::<Vec<_>>();
    let t = target.components().collect::<Vec<_>>();
    if t.len() <= b.len() {
        return None;
    }
    if b != t[..b.len()] {
        return None; // different prefix → outside the base
    }
    Some(
        t[b.len()..]
            .iter()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect::<Vec<_>>()
            .join("/"),
    )
}

/// A running workspace watcher. Dropping it stops watching (dispose).
pub struct WorkspaceWatcher {
    _watcher: RecommendedWatcher,
    _handle: std::thread::JoinHandle<()>,
    stop: Arc<Mutex<bool>>,
    app: AppHandle,
}

impl WorkspaceWatcher {
    /// Start watching `workspace`. Change batches are emitted to the frontend
    /// as `workspace://changed`; overflow marks `workspace://stale`.
    /// `extra_ignore` is the user-configured `ui.explorer_ignore` set.
    pub fn start(app: AppHandle, workspace: &Path, extra_ignore: Vec<String>) -> Result<Self, WorkbenchError> {
        let ws = workspace.to_path_buf();
        let ws_closure = ws.clone();
        let app_clone = app.clone();
        let extra_closure = extra_ignore;
        let (raw_tx, raw_rx) = mpsc::sync_channel::<(String, String, String)>(RAW_CHANNEL_CAP);

        // O9-反馈 #8: see TempRenameTracker — temp-From/real-To pairs from
        // atomic writes must surface as "created", never "renamed".
        let mut temp_renames = TempRenameTracker::default();

        let mut watcher = notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
            let event = match res {
                Ok(e) => e,
                Err(_) => return,
            };
            use notify::event::{EventKind, ModifyKind, RenameMode};
            let change_kind = change_kind_of(&event.kind).to_string();
            let total_paths = event.paths.len();
            for (path_index, path) in event.paths.into_iter().enumerate() {
                let mut change_type =
                    change_type_of_path(&event.kind, path_index, total_paths).to_string();
                let Some(rel) = relative_of(&ws_closure, &path) else {
                    continue;
                };
                // O9-反馈 #8: classify the rename halves BEFORE the ignore
                // filter drops them — the temp half never reaches the send.
                let (from_half, to_half) = match &event.kind {
                    EventKind::Modify(ModifyKind::Name(RenameMode::From)) => (true, false),
                    EventKind::Modify(ModifyKind::Name(RenameMode::To)) => (false, true),
                    EventKind::Modify(ModifyKind::Name(RenameMode::Both)) => {
                        (path_index == 0, total_paths == 2 && path_index == 1)
                    }
                    _ => (false, false),
                };
                if from_half && is_temp_file(&rel) {
                    temp_renames.note_temp_from();
                }
                if to_half && change_type == "renamed" {
                    change_type = temp_renames.classify_to("renamed").to_string();
                }
                if is_watch_ignored(&rel, &extra_closure) {
                    continue; // dependency/build noise must not reload the tree
                }
                if raw_tx
                    .try_send((rel, change_type.clone(), change_kind.clone()))
                    .is_err()
                {
                    // Channel full: overflow. Send a sentinel so the batcher
                    // marks stale (bounded rescan) instead of dropping silently.
                    let _ = raw_tx.try_send((
                        "\0overflow".to_string(),
                        "overflow".to_string(),
                        String::new(),
                    ));
                }
            }
        })
        .map_err(|e| {
            WorkbenchError::settings_error().with_detail(format!("notify: {e}"))
        })?;
        watcher
            .watch(&ws, RecursiveMode::Recursive)
            .map_err(|e| {
                WorkbenchError::settings_error().with_detail(format!("watch: {e}"))
            })?;

        let stop = Arc::new(Mutex::new(false));
        let stop_clone = stop.clone();
        let ws_label = ws.to_string_lossy().to_string();
        let handle = std::thread::spawn(move || {
            debounce_loop(app_clone, ws_label, raw_rx, stop_clone);
        });

        Ok(WorkspaceWatcher {
            _watcher: watcher,
            _handle: handle,
            stop,
            app,
        })
    }

    /// Stop the watcher (also happens on drop).
    pub fn dispose(&self) {
        *self.stop.lock().unwrap() = true;
    }
}

fn debounce_loop(
    app: AppHandle,
    workspace: String,
    rx: mpsc::Receiver<(String, String, String)>,
    stop: Arc<Mutex<bool>>,
) {
    let mut batcher = ChangeBatcher::default();
    let mut revision: u64 = 0;
    let mut pending: Option<std::time::Instant> = None;

    loop {
        if *stop.lock().unwrap() {
            return;
        }
        // Non-blocking drain of the raw channel.
        let mut received = 0;
        while let Ok((path, change_type, change_kind)) = rx.try_recv() {
            received += 1;
            if path == "\0overflow" {
                batcher.mark_overflow();
            } else {
                batcher.push(path, change_type, change_kind);
            }
            if received >= MAX_BATCH {
                break;
            }
        }

        let should_flush = if received > 0 {
            pending = Some(std::time::Instant::now());
            false
        } else if let Some(started) = pending {
            started.elapsed() >= DEBOUNCE
        } else {
            false
        };

        if should_flush || (received >= MAX_BATCH) {
            pending = None;
            let mut batch = batcher.drain(revision);
            batch.workspace = workspace.clone();
            revision = revision.wrapping_add(1);
            if !batch.changes.is_empty() || batch.overflow {
                let _ = app.emit("workspace://changed", &batch);
                if batch.overflow {
                    let _ = app.emit("workspace://stale", &batch);
                }
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Bounded rescan: re-list the workspace root (the frontend store re-fetches).
/// Returns the fresh root listing; marks the prior state stale until then.
#[tauri::command]
pub async fn workspace_rescan(app: AppHandle, workspace: String) -> Result<(), WorkbenchError> {
    let _ = app.emit("workspace://rescanning", &workspace);
    // The frontend re-lists the root; this command exists so a watcher-triggered
    // stale state has an explicit "refresh now" path.
    Ok(())
}

/// Managed watcher lifetime so start/stop are idempotent across sessions.
#[derive(Default)]
pub struct WatcherState(pub std::sync::Mutex<Option<WorkspaceWatcher>>);

/// Start watching a workspace (replaces any prior watcher).
#[tauri::command]
pub async fn workspace_watch_start(
    app: AppHandle,
    workspace: String,
) -> Result<(), WorkbenchError> {
    // Read the user-configured explorer ignores so the watcher does not emit
    // noise under them (mirrors the Explorer listing ignore set).
    let extra_ignore = match crate::session::config_dir(&app) {
        Ok(dir) => match crate::settings::load_settings_document(&dir) {
            Ok(doc) => doc.ui.explorer_ignore,
            Err(_) => Vec::new(),
        },
        Err(_) => Vec::new(),
    };
    // Start first (moves a clone); the original app is used for state below.
    let watcher = WorkspaceWatcher::start(app.clone(), Path::new(&workspace), extra_ignore)?;
    let state = app.state::<WatcherState>();
    let mut guard = state.0.lock().unwrap();
    if let Some(old) = guard.take() {
        old.dispose();
    }
    *guard = Some(watcher);
    Ok(())
}

/// Stop watching (dispose). Idempotent.
#[tauri::command]
pub async fn workspace_watch_stop(app: AppHandle) -> Result<(), WorkbenchError> {
    let state = app.state::<WatcherState>();
    let mut guard = state.0.lock().unwrap();
    if let Some(w) = guard.take() {
        w.dispose();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn batcher_dedups_and_reports_overflow() {
        let mut b = ChangeBatcher::default();
        b.push("a.md".into(), "created".into(), "file".into());
        // O9-反馈 #1b: birth is sticky — the followup write no longer
        // overwrites "created" (last-write-wins mislabeled agent files).
        b.push("a.md".into(), "modified".into(), "file".into());
        b.push("b.md".into(), "deleted".into(), "file".into());
        b.mark_overflow();
        let batch = b.drain(1);
        assert_eq!(batch.revision, 1);
        assert!(batch.overflow);
        assert!(batch.stale);
        assert_eq!(batch.changes.len(), 2);
        assert_eq!(batch.changes[0].relative_path, "a.md");
        assert_eq!(batch.changes[0].change_type, "created");
        assert_eq!(batch.changes[0].kind, "file");
        // drain clears; next drain is empty and no longer stale.
        let next = b.drain(2);
        assert!(next.changes.is_empty());
        assert!(!next.stale);
    }

    #[test]
    fn watch_ignore_matches_nested_components() {
        let extra: Vec<String> = Vec::new();
        assert!(is_watch_ignored("node_modules/x", &extra));
        assert!(is_watch_ignored("src/node_modules/x", &extra));
        assert!(is_watch_ignored("a/b/target/c", &extra));
        assert!(is_watch_ignored(".claude/settings.json", &extra));
        assert!(is_watch_ignored("a/.codex/x", &extra));
        assert!(!is_watch_ignored("src/lib/main.ts", &extra));
    }

    #[test]
    fn watch_ignore_merges_user_exclusions() {
        let extra = vec!["scratch".to_string(), "vendor".to_string()];
        assert!(is_watch_ignored("scratch/out.bin", &extra));
        assert!(is_watch_ignored("src/vendor/lib.js", &extra));
        assert!(!is_watch_ignored("src/lib/main.ts", &extra));
        assert!(is_watch_ignored("node_modules", &extra)); // built-in applies even when extra lacks it
    }

    #[test]
    fn watch_ignores_transient_temp_files() {
        let extra: Vec<String> = Vec::new();
        // Atomic-write temps the agent renames over the real file.
        assert!(is_watch_ignored("reports/result.md.tmp.1234", &extra));
        assert!(is_watch_ignored("reports/result.md.tmp", &extra));
        assert!(is_watch_ignored("src/app.py.temp", &extra));
        // Editor/backup artifacts.
        assert!(is_watch_ignored("src/main.ts~", &extra));
        assert!(is_watch_ignored("src/main.ts.swp", &extra));
        assert!(is_watch_ignored("src/.#main.ts", &extra));
        assert!(is_watch_ignored("~$report.docx", &extra));
        // Real files are NOT ignored.
        assert!(!is_watch_ignored("reports/result.md", &extra));
        assert!(!is_watch_ignored("src/templates/main.rs", &extra)); // dir name is fine
        assert!(!is_watch_ignored("src/important.template", &extra));
    }

    #[test]
    fn pathdiff_inside_and_outside() {
        let ws = std::path::Path::new("/ws");
        assert_eq!(pathdiff(ws, std::path::Path::new("/ws/src/a.md")), Some("src/a.md".into()));
        assert_eq!(pathdiff(ws, std::path::Path::new("/ws")), None); // root itself
        assert_eq!(pathdiff(ws, std::path::Path::new("/other/x")), None); // outside
    }

    #[test]
    fn change_type_classification() {
        use notify::event::*;
        assert_eq!(
            change_type_of_path(&EventKind::Create(CreateKind::File), 0, 1),
            "created"
        );
        // Rename roles: the OLD path (From) is a deletion, the NEW (To) is a
        // rename; a Both event splits by path index (2026-08-28 "mv" test).
        assert_eq!(
            change_type_of_path(&EventKind::Modify(ModifyKind::Name(RenameMode::From)), 0, 1),
            "deleted"
        );
        assert_eq!(
            change_type_of_path(&EventKind::Modify(ModifyKind::Name(RenameMode::To)), 0, 1),
            "renamed"
        );
        assert_eq!(
            change_type_of_path(
                &EventKind::Modify(ModifyKind::Name(RenameMode::Both)),
                0,
                2
            ),
            "deleted"
        );
        assert_eq!(
            change_type_of_path(
                &EventKind::Modify(ModifyKind::Name(RenameMode::Both)),
                1,
                2
            ),
            "renamed"
        );
        assert_eq!(
            change_type_of_path(&EventKind::Modify(ModifyKind::Data(DataChange::Any)), 0, 1),
            "modified"
        );
        assert_eq!(
            change_type_of_path(&EventKind::Remove(RemoveKind::File), 0, 1),
            "deleted"
        );
    }

    #[test]
    fn change_kind_classification() {
        use notify::event::*;
        assert_eq!(change_kind_of(&EventKind::Create(CreateKind::Folder)), "dir");
        assert_eq!(change_kind_of(&EventKind::Create(CreateKind::File)), "file");
        assert_eq!(change_kind_of(&EventKind::Modify(ModifyKind::Data(DataChange::Any))), "file");
    }

    // --- O9-反馈 #8 (2026-09-02): atomic-write temp renames read as created ---

    #[test]
    fn temp_rename_tracker_turns_paired_to_into_created() {
        // claude writes `report.md.tmp.1234` then renames it over
        // `report.md`: the temp From is filtered, the real To is a BIRTH.
        let mut t = TempRenameTracker::default();
        t.note_temp_from();
        assert_eq!(t.classify_to("renamed"), "created");
        // One marker serves one rename; an unpaired later To stays renamed.
        assert_eq!(t.classify_to("renamed"), "renamed");
    }

    #[test]
    fn temp_rename_tracker_marker_expires() {
        let mut t = TempRenameTracker::default();
        t.at = std::time::Instant::now()
            .checked_sub(std::time::Duration::from_secs(5));
        assert_eq!(t.classify_to("renamed"), "renamed");
    }

    #[test]
    fn temp_rename_tracker_without_marker_is_transparent() {
        // A real `mv a b`: From is NOT temp (never filtered, no marker), so
        // the To keeps its honest "renamed" classification.
        let mut t = TempRenameTracker::default();
        assert_eq!(t.classify_to("renamed"), "renamed");
    }

    // --- O9-反馈 #1b (2026-09-02): birth is sticky within a batch ---

    #[test]
    fn batcher_keeps_created_over_followup_writes() {
        // codex writes a new file as Create -> Modify(Data): "created" must
        // survive (last-write-wins mislabeled it "modified").
        let mut b = ChangeBatcher::default();
        b.push("report.md".into(), "created".into(), "file".into());
        b.push("report.md".into(), "modified".into(), "file".into());
        let batch = b.drain(0);
        assert_eq!(batch.changes[0].change_type, "created");
    }

    #[test]
    fn batcher_merge_table() {
        let cases: &[(&str, &str, &str)] = &[
            ("modified", "created", "created"), // delete+recreate
            ("created", "deleted", "deleted"),  // born then removed
            ("modified", "deleted", "deleted"),
            ("deleted", "created", "created"),
            ("renamed", "modified", "renamed"), // rename then write
            ("modified", "renamed", "renamed"),
            ("modified", "modified", "modified"),
        ];
        for (prev, next, want) in cases {
            assert_eq!(
                merge_change_type(prev, next).as_str(),
                *want,
                "merge({prev}, {next})"
            );
        }
    }
}
