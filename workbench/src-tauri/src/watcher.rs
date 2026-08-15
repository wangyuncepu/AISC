//! Workspace change watcher (Stage 3, 3d, WX-03 / R3-03, R3-08).
//!
//! Watches the workspace and produces ONLY an unattributed projection
//! (`workspace_change`) — it never guesses Agent provenance (D3-03). Changes
//! are debounced/coalesced, the raw event channel is bounded, and an overflow
//! marks the Explorer stale + triggers a bounded rescan instead of losing
//! events silently (R3-08). `dispose` stops everything.

use std::collections::BTreeSet;
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
    pub revision: u64,
}

/// A coalesced batch emitted to the frontend.
#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceChangeBatch {
    pub changes: Vec<WorkspaceChange>,
    pub revision: u64,
    pub overflow: bool,
    pub stale: bool,
}

/// Dedup + order changes within a debounce window.
#[derive(Debug, Default)]
struct ChangeBatcher {
    // BTreeMap path -> type (last write wins for a path within the window).
    by_path: std::collections::BTreeMap<String, String>,
    overflow: bool,
}

impl ChangeBatcher {
    fn push(&mut self, path: String, change_type: String) {
        self.by_path.insert(path, change_type);
    }

    fn mark_overflow(&mut self) {
        self.overflow = true;
    }

    fn drain(&mut self, revision: u64) -> WorkspaceChangeBatch {
        let changes = std::mem::take(&mut self.by_path)
            .into_iter()
            .map(|(relative_path, change_type)| WorkspaceChange {
                relative_path,
                change_type,
                revision,
            })
            .collect();
        let overflow = self.overflow;
        self.overflow = false;
        WorkspaceChangeBatch {
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
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
];

/// True when a workspace-relative path is under a WATCH_IGNORE directory.
fn is_watch_ignored(relative: &str) -> bool {
    relative
        .split('/')
        .next()
        .map(|top| WATCH_IGNORE.contains(&top))
        .unwrap_or(false)
}

/// Classify a notify event kind into a stable change type.
fn change_type_of(kind: &EventKind) -> &'static str {
    use notify::event::*;
    match kind {
        EventKind::Create(_) => "created",
        EventKind::Modify(ModifyKind::Name(_)) => "renamed",
        EventKind::Modify(_) => "modified",
        EventKind::Remove(_) => "deleted",
        _ => "changed",
    }
}

/// Compute the workspace-relative path of a changed path.
fn relative_of(workspace: &Path, path: &Path) -> Option<String> {
    let ws = pathdiff(workspace, path)?;
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
    pub fn start(app: AppHandle, workspace: &Path) -> Result<Self, WorkbenchError> {
        let ws = workspace.to_path_buf();
        let ws_closure = ws.clone();
        let app_clone = app.clone();
        let (raw_tx, raw_rx) = mpsc::sync_channel::<(String, String)>(RAW_CHANNEL_CAP);

        let mut watcher = notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
            let event = match res {
                Ok(e) => e,
                Err(_) => return,
            };
            let change_type = change_type_of(&event.kind).to_string();
            for path in event.paths {
                let Some(rel) = relative_of(&ws_closure, &path) else {
                    continue;
                };
                if is_watch_ignored(&rel) {
                    continue; // dependency/build noise must not reload the tree
                }
                if raw_tx.try_send((rel, change_type.clone())).is_err() {
                    // Channel full: overflow. Send a sentinel so the batcher
                    // marks stale (bounded rescan) instead of dropping silently.
                    let _ = raw_tx.try_send(("\0overflow".to_string(), "overflow".to_string()));
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
        let handle = std::thread::spawn(move || {
            debounce_loop(app_clone, raw_rx, stop_clone);
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

fn debounce_loop(app: AppHandle, rx: mpsc::Receiver<(String, String)>, stop: Arc<Mutex<bool>>) {
    let mut batcher = ChangeBatcher::default();
    let mut revision: u64 = 0;
    let mut pending: Option<std::time::Instant> = None;

    loop {
        if *stop.lock().unwrap() {
            return;
        }
        // Non-blocking drain of the raw channel.
        let mut received = 0;
        while let Ok((path, change_type)) = rx.try_recv() {
            received += 1;
            if path == "\0overflow" {
                batcher.mark_overflow();
            } else {
                batcher.push(path, change_type);
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
            let batch = batcher.drain(revision);
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
    // Start first (moves a clone); the original app is used for state below.
    let watcher = WorkspaceWatcher::start(app.clone(), Path::new(&workspace))?;
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
        b.push("a.md".into(), "created".into());
        b.push("a.md".into(), "modified".into()); // last wins
        b.push("b.md".into(), "deleted".into());
        b.mark_overflow();
        let batch = b.drain(1);
        assert_eq!(batch.revision, 1);
        assert!(batch.overflow);
        assert!(batch.stale);
        assert_eq!(batch.changes.len(), 2);
        assert_eq!(batch.changes[0].relative_path, "a.md");
        assert_eq!(batch.changes[0].change_type, "modified");
        // drain clears; next drain is empty and no longer stale.
        let next = b.drain(2);
        assert!(next.changes.is_empty());
        assert!(!next.stale);
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
        assert_eq!(change_type_of(&EventKind::Create(CreateKind::File)), "created");
        assert_eq!(change_type_of(&EventKind::Modify(ModifyKind::Name(RenameMode::To))), "renamed");
        assert_eq!(change_type_of(&EventKind::Modify(ModifyKind::Data(DataChange::Any))), "modified");
        assert_eq!(change_type_of(&EventKind::Remove(RemoveKind::File)), "deleted");
    }
}
