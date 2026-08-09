//! Workbench history persistence (02-startup-flow.md §九).
//!
//! Schema-versioned, atomically-written `history.json` remembering workspace /
//! runtime ID / tab-layout metadata. Cross-process advisory locking (fs4) +
//! expected-revision reload/merge so two Workbench windows don't lose each
//! other's workspaces (02 §九 强制要求). History never holds session IDs, PTY
//! PIDs, scrollback, or secrets (02 §九).
//!
//! S2.4.a: persistence + recents. Startup reconciliation (runtime list) and
//! resume-layout land in S2.4.b.

use std::fs;
use std::io;
use std::path::Path;
use std::time::{Duration, Instant};

use fs4::fs_std::FileExt;
use serde::{Deserialize, Serialize};
use tauri::AppHandle;

use crate::error::WorkbenchError;
use crate::session::config_dir;
use crate::storage;

const SCHEMA_VERSION: u64 = 1;
const HISTORY_FILE: &str = "history.json";
const LOCK_FILE: &str = "history.lock";
const LOCK_TIMEOUT: Duration = Duration::from_secs(5);
const LOCK_POLL: Duration = Duration::from_millis(50);

#[derive(Debug)]
pub enum HistoryError {
    Io(String),
    /// File exists but is not valid JSON. The corrupt file is isolated
    /// (renamed to `history.json.corrupt`) so the app can still start.
    Corrupt(String),
    /// File schema_version is missing or unsupported. Left untouched.
    UnsupportedSchema { found: Option<u64> },
    /// Could not acquire the cross-process lock within the timeout. Fail-closed:
    /// no lockless write (02 §九).
    LockTimeout,
    /// `expected_revision` did not match the on-disk revision (concurrent write).
    /// Caller reloads, merges its own workspace, and retries.
    Conflict { current_revision: u64 },
}

impl std::fmt::Display for HistoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(m) => write!(f, "history io error: {m}"),
            Self::Corrupt(m) => write!(f, "history.json corrupted: {m}"),
            Self::UnsupportedSchema { found } => match found {
                Some(v) => write!(f, "unsupported history schema_version: {v}"),
                None => write!(f, "history.json missing schema_version"),
            },
            Self::LockTimeout => write!(f, "history lock timeout"),
            Self::Conflict { current_revision } => {
                write!(f, "history revision conflict (current={current_revision})")
            }
        }
    }
}

impl std::error::Error for HistoryError {}

fn map_history_error(e: HistoryError) -> WorkbenchError {
    match e {
        HistoryError::Conflict { .. } => WorkbenchError::history_conflict(),
        other => WorkbenchError::history_error().with_detail(other.to_string()),
    }
}

// --- schema (02 §九.2 subset; window geometry lands in S2.4.b) ---

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct WorkbenchHistory {
    #[serde(default)]
    pub schema_version: u64,
    #[serde(default)]
    pub revision: u64,
    #[serde(default)]
    pub workspaces: Vec<WorkspaceRecord>,
    /// Unknown root fields survive round-trips (A-INFRA-5).
    #[serde(default, flatten)]
    pub extra: serde_json::Value,
}

impl WorkbenchHistory {
    /// Empty history with the current schema version.
    pub fn empty() -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            revision: 0,
            workspaces: Vec::new(),
            extra: serde_json::Value::Object(Default::default()),
        }
    }
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct WorkspaceRecord {
    pub path: String,
    #[serde(default)]
    pub last_used_at: String,
    #[serde(default)]
    pub pinned: bool,
    #[serde(default)]
    pub last_agent: String,
    #[serde(default)]
    pub runtime: Option<RuntimeRef>,
    #[serde(default)]
    pub layout: Option<Layout>,
    /// Unknown fields survive round-trips (A-INFRA-5): never drop forward
    /// fields written by a newer Workbench.
    #[serde(default, flatten)]
    pub extra: serde_json::Value,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct RuntimeRef {
    pub runtime_id: String,
    #[serde(default)]
    pub image: String,
    #[serde(default)]
    pub network: String,
    #[serde(default)]
    pub scope: String,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct Layout {
    #[serde(default)]
    pub active_tab_id: Option<String>,
    #[serde(default)]
    pub tabs: Vec<TabRecord>,
    /// Unknown fields survive round-trips (A-INFRA-5).
    #[serde(default, flatten)]
    pub extra: serde_json::Value,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct TabRecord {
    pub tab_id: String,
    pub agent: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub position: u32,
    /// Unknown fields survive round-trips (A-INFRA-5).
    #[serde(default, flatten)]
    pub extra: serde_json::Value,
}

/// Patch a window submits to `save`. Workspaces are upserted by path; other
/// workspaces on disk are preserved (02 §九 "多窗口只 patch 自己拥有的").
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct HistoryPatch {
    #[serde(default)]
    pub workspaces: Vec<WorkspaceRecord>,
}

// --- load / save ---

/// Load `dir/history.json`. Missing -> empty. Corrupt JSON -> isolate the file
/// (rename to `.corrupt`) and return empty so the app starts. Unsupported
/// schema -> error (caller treats as no history; file left untouched).
pub fn load(dir: &Path) -> Result<WorkbenchHistory, HistoryError> {
    let path = dir.join(HISTORY_FILE);
    match fs::read(&path) {
        Ok(bytes) => match serde_json::from_slice::<WorkbenchHistory>(&bytes) {
            Ok(hist) if hist.schema_version == SCHEMA_VERSION => Ok(hist),
            Ok(hist) => Err(HistoryError::UnsupportedSchema {
                found: Some(hist.schema_version),
            }),
            Err(e) => {
                // Isolate the corrupt file so a fresh history can be written.
                let _ = fs::rename(&path, dir.join(format!("{HISTORY_FILE}.corrupt")));
                Err(HistoryError::Corrupt(e.to_string()))
            }
        },
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(WorkbenchHistory::empty()),
        Err(e) => Err(HistoryError::Io(e.to_string())),
    }
}

/// Save under the cross-process lock: reload, verify `expected_revision`, merge
/// the patch (upsert by path, preserve others), bump revision, atomic write.
/// Returns the new revision, or `Conflict` if the on-disk revision moved.
pub fn save(dir: &Path, expected_revision: u64, patch: &HistoryPatch) -> Result<u64, HistoryError> {
    fs::create_dir_all(dir).map_err(|e| HistoryError::Io(e.to_string()))?;
    let lock_path = dir.join(LOCK_FILE);
    let lock_file = fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|e| HistoryError::Io(e.to_string()))?;

    // Bounded wait for the exclusive lock (fail-closed on timeout).
    let deadline = Instant::now() + LOCK_TIMEOUT;
    loop {
        match lock_file.try_lock_exclusive() {
            Ok(true) => break,
            Ok(false) => {
                if Instant::now() >= deadline {
                    return Err(HistoryError::LockTimeout);
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(e) => return Err(HistoryError::Io(e.to_string())),
        }
    }
    let result = save_locked(dir, expected_revision, patch);
    let _ = lock_file.unlock();
    result
}

/// Deep-merge `src` into `dst` (unknown-field maps): `src` fills keys `dst`
/// lacks; `dst` wins on conflict. Used so an old window's patch never drops
/// unknown fields a newer window wrote (A-INFRA-5).
fn merge_value(dst: &mut serde_json::Value, src: &serde_json::Value) {
    if src.is_null() {
        return;
    }
    if dst.is_null() {
        *dst = src.clone();
        return;
    }
    if let (Some(d_obj), Some(s_obj)) = (dst.as_object_mut(), src.as_object()) {
        for (k, v) in s_obj {
            match d_obj.get_mut(k) {
                Some(dv) if dv.is_object() && v.is_object() => merge_value(dv, v),
                _ => {
                    d_obj.insert(k.clone(), v.clone());
                }
            }
        }
    }
}

/// Merge a freshly-loaded on-disk workspace record into the patch record so
/// omitted typed fields and unknown fields at workspace/layout/tab layers
/// survive the replace (A-INFRA-5: field-level deep merge).
fn merge_workspace(old: &WorkspaceRecord, new: &mut WorkspaceRecord) {
    merge_value(&mut new.extra, &old.extra);
    if new.layout.is_none() {
        // Patch omitted the layout entirely: keep the on-disk one.
        new.layout = old.layout.clone();
        return;
    }
    if let (Some(old_l), Some(new_l)) = (&old.layout, &mut new.layout) {
        merge_value(&mut new_l.extra, &old_l.extra);
        for old_t in &old_l.tabs {
            if let Some(new_t) = new_l.tabs.iter_mut().find(|t| t.tab_id == old_t.tab_id) {
                merge_value(&mut new_t.extra, &old_t.extra);
            }
        }
    }
}

fn save_locked(
    dir: &Path,
    expected_revision: u64,
    patch: &HistoryPatch,
) -> Result<u64, HistoryError> {
    let mut current = load(dir)?;
    if current.revision != expected_revision {
        return Err(HistoryError::Conflict {
            current_revision: current.revision,
        });
    }
    // Merge: upsert patch workspaces by path; preserve others and their
    // unknown fields.
    for ws in &patch.workspaces {
        if let Some(slot) = current.workspaces.iter_mut().find(|w| w.path == ws.path) {
            let old = slot.clone();
            *slot = ws.clone();
            merge_workspace(&old, slot);
        } else {
            current.workspaces.push(ws.clone());
        }
    }
    current.revision += 1;
    let bytes = serde_json::to_vec_pretty(&current)
        .map_err(|e| HistoryError::Corrupt(e.to_string()))?;
    atomic_write(&dir.join(HISTORY_FILE), &bytes).map_err(|e| HistoryError::Io(e.to_string()))?;
    Ok(current.revision)
}

fn atomic_write(target: &Path, bytes: &[u8]) -> io::Result<()> {
    storage::atomic_replace(target, bytes)
}

// --- Tauri commands ---

#[tauri::command]
pub async fn load_history(app: AppHandle) -> Result<WorkbenchHistory, WorkbenchError> {
    let dir = config_dir(&app)?;
    // Corrupt files are isolated by `load`; unsupported/other errors -> empty so
    // the app starts clean without overwriting a recoverable file.
    Ok(load(&dir).unwrap_or_else(|_| WorkbenchHistory::empty()))
}

#[tauri::command]
pub async fn save_history(
    app: AppHandle,
    expected_revision: u64,
    patch: HistoryPatch,
) -> Result<u64, WorkbenchError> {
    let dir = config_dir(&app)?;
    save(&dir, expected_revision, &patch).map_err(map_history_error)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn load_missing_file_is_empty() {
        let dir = tempdir().unwrap();
        let h = load(dir.path()).unwrap();
        assert_eq!(h.schema_version, SCHEMA_VERSION);
        assert_eq!(h.revision, 0);
        assert!(h.workspaces.is_empty());
    }

    #[test]
    fn save_then_load_round_trips() {
        let dir = tempdir().unwrap();
        let patch = HistoryPatch {
            workspaces: vec![WorkspaceRecord {
                path: "/ws".into(),
                last_used_at: "t".into(),
                last_agent: "claude".into(),
                runtime: Some(RuntimeRef {
                    runtime_id: "rid".into(),
                    image: "super-claude:latest".into(),
                    network: "direct".into(),
                    scope: "project".into(),
                }),
                layout: Some(Layout {
                    active_tab_id: Some("tab1".into()),
                    tabs: vec![TabRecord {
                        tab_id: "tab1".into(),
                        agent: "claude".into(),
                        title: "Claude".into(),
                        position: 0,
                        ..Default::default()
                    }],
                    ..Default::default()
                }),
                pinned: false,
                ..Default::default()
            }],
        };
        let rev = save(dir.path(), 0, &patch).unwrap();
        assert_eq!(rev, 1);
        let h = load(dir.path()).unwrap();
        assert_eq!(h.revision, 1);
        assert_eq!(h.workspaces.len(), 1);
        assert_eq!(h.workspaces[0].path, "/ws");
        assert_eq!(h.workspaces[0].runtime.as_ref().unwrap().runtime_id, "rid");
        assert_eq!(h.workspaces[0].layout.as_ref().unwrap().tabs.len(), 1);
    }

    #[test]
    fn conflict_when_revision_moved() {
        let dir = tempdir().unwrap();
        let patch = HistoryPatch {
            workspaces: vec![WorkspaceRecord {
                path: "/a".into(),
                ..Default::default()
            }],
        };
        save(dir.path(), 0, &patch).unwrap(); // rev -> 1
        // A second "window" writes in between:
        let patch2 = HistoryPatch {
            workspaces: vec![WorkspaceRecord {
                path: "/b".into(),
                ..Default::default()
            }],
        };
        save(dir.path(), 1, &patch2).unwrap(); // rev -> 2
        // Stale caller still expects rev 1 -> conflict.
        let err = save(dir.path(), 1, &patch).unwrap_err();
        assert!(matches!(
            err,
            HistoryError::Conflict {
                current_revision: 2
            }
        ));
    }

    #[test]
    fn merge_preserves_other_windows_workspaces() {
        let dir = tempdir().unwrap();
        // Window A writes /a.
        save(
            dir.path(),
            0,
            &HistoryPatch {
                workspaces: vec![WorkspaceRecord {
                    path: "/a".into(),
                    last_agent: "claude".into(),
                    ..Default::default()
                }],
            },
        )
        .unwrap();
        // Window B (reloaded, expected rev 1) writes /b; /a must survive.
        save(
            dir.path(),
            1,
            &HistoryPatch {
                workspaces: vec![WorkspaceRecord {
                    path: "/b".into(),
                    last_agent: "bash".into(),
                    ..Default::default()
                }],
            },
        )
        .unwrap();
        let h = load(dir.path()).unwrap();
        assert_eq!(h.revision, 2);
        let paths: Vec<_> = h.workspaces.iter().map(|w| w.path.as_str()).collect();
        assert!(paths.contains(&"/a"));
        assert!(paths.contains(&"/b"));
    }

    #[test]
    fn unknown_fields_round_trip_at_every_layer() {
        // A future/newer Workbench wrote unknown fields at root, workspace,
        // layout and tab layers. They must survive load -> save -> reload
        // (A-INFRA-5), never silently dropped.
        let dir = tempdir().unwrap();
        let raw = serde_json::json!({
            "schema_version": 1,
            "revision": 0,
            "root_future": {"a": 1},
            "workspaces": [{
                "path": "/ws",
                "ws_future": "keep-me",
                "layout": {
                    "active_tab_id": "t1",
                    "layout_future": true,
                    "tabs": [{
                        "tab_id": "t1",
                        "agent": "bash",
                        "position": 0,
                        "tab_future": [1, 2, 3]
                    }]
                }
            }]
        });
        fs::write(
            dir.path().join(HISTORY_FILE),
            serde_json::to_vec_pretty(&raw).unwrap(),
        )
        .unwrap();

        let h = load(dir.path()).unwrap();
        // Round-trip through save with a patch touching the same workspace.
        let rev = save(
            dir.path(),
            0,
            &HistoryPatch {
                workspaces: vec![WorkspaceRecord {
                    path: "/ws".into(),
                    last_agent: "bash".into(),
                    ..Default::default()
                }],
            },
        )
        .unwrap();
        assert_eq!(rev, 1);

        let h = load(dir.path()).unwrap();
        assert_eq!(h.extra.get("root_future").and_then(|v| v.get("a")), Some(&serde_json::json!(1)));
        let ws = &h.workspaces[0];
        assert_eq!(ws.extra.get("ws_future").and_then(|v| v.as_str()), Some("keep-me"));
        let layout = ws.layout.as_ref().unwrap();
        assert_eq!(layout.extra.get("layout_future").and_then(|v| v.as_bool()), Some(true));
        let tab = &layout.tabs[0];
        assert_eq!(tab.extra.get("tab_future").and_then(|v| v.as_array()).map(|a| a.len()), Some(3));
    }

    #[test]
    fn corrupt_json_is_isolated_and_load_is_empty() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(HISTORY_FILE), b"{not json").unwrap();
        // Corrupt -> error (the command layer maps this to empty so the app
        // still starts) and the file is isolated for diagnosis.
        let err = load(dir.path()).unwrap_err();
        assert!(matches!(err, HistoryError::Corrupt(_)));
        assert!(dir.path().join(format!("{HISTORY_FILE}.corrupt")).exists());
        // Original file no longer in place -> next load is empty.
        let h = load(dir.path()).unwrap();
        assert!(h.workspaces.is_empty());
    }

    #[test]
    fn unsupported_schema_is_error_and_not_overwritten() {
        let dir = tempdir().unwrap();
        let bad = serde_json::json!({"schema_version": 999, "revision": 0, "workspaces": []});
        fs::write(
            dir.path().join(HISTORY_FILE),
            serde_json::to_vec(&bad).unwrap(),
        )
        .unwrap();
        let err = load(dir.path()).unwrap_err();
        assert!(matches!(
            err,
            HistoryError::UnsupportedSchema { found: Some(999) }
        ));
        // File untouched.
        let on_disk: serde_json::Value =
            serde_json::from_slice(&fs::read(dir.path().join(HISTORY_FILE)).unwrap()).unwrap();
        assert_eq!(
            on_disk.get("schema_version").and_then(|v| v.as_u64()),
            Some(999)
        );
    }

    #[test]
    fn upsert_overwrites_same_path() {
        let dir = tempdir().unwrap();
        let v1 = HistoryPatch {
            workspaces: vec![WorkspaceRecord {
                path: "/ws".into(),
                last_agent: "claude".into(),
                ..Default::default()
            }],
        };
        save(dir.path(), 0, &v1).unwrap();
        let v2 = HistoryPatch {
            workspaces: vec![WorkspaceRecord {
                path: "/ws".into(),
                last_agent: "bash".into(),
                ..Default::default()
            }],
        };
        save(dir.path(), 1, &v2).unwrap();
        let h = load(dir.path()).unwrap();
        assert_eq!(h.workspaces.len(), 1);
        assert_eq!(h.workspaces[0].last_agent, "bash");
    }
}
