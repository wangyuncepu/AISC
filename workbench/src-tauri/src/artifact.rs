//! Agent Artifact index (Stage 3, ART-04/06, R3-07, R3-10).
//!
//! The Workbench-side projection of the CLI's session-scoped registries. The
//! CLI (`aisc artifact record`) is the authoritative fact writer; this module
//! imports the CLI's JSONL registries (same host data root / workspace hash),
//! validates each record against `aisc.artifact/v1`, and persists a merged,
//! schema-versioned index with revision + cross-process lock + atomic replace
//! + corrupt isolation.
//!
//! Deliberately separate from packaging artifacts (R3-10): distinct schema,
//! module, and namespaces.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use fs4::fs_std::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::AppHandle;

use crate::error::WorkbenchError;
use crate::session::config_dir;
use crate::storage;

pub const ARTIFACT_SCHEMA_VERSION: u64 = 1;
pub const INDEX_SCHEMA_VERSION: u64 = 1;

const INDEX_FILE: &str = "artifacts.json";
const LOCK_FILE: &str = "artifacts.lock";
const LOCK_TIMEOUT: Duration = Duration::from_secs(5);
const LOCK_POLL: Duration = Duration::from_millis(50);

// ---------------------------------------------------------------------------
// Schema (aisc.artifact/v1) — mirror of the CLI record
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactRecord {
    pub schema_version: u64,
    pub artifact_id: String,
    pub workspace_relative_path: String,
    pub action: String,
    pub kind: String,
    pub media_type: Option<String>,
    pub label: String,
    pub open_with: String,
    pub producer: serde_json::Value,
    pub state: String,
    pub provenance: String,
    pub recorded_at: String,
    pub previous_path: Option<String>,
    pub extra: serde_json::Value,
}

const KNOWN_FIELDS: &[&str] = &[
    "schema_version",
    "artifact_id",
    "workspace_relative_path",
    "action",
    "kind",
    "media_type",
    "label",
    "open_with",
    "producer",
    "state",
    "provenance",
    "recorded_at",
    "previous_path",
    "extra",
];

/// Deserialize preserving unknown top-level fields into `extra` (A-ART01-1:
/// the schema v1 fixture must round-trip through Python, Rust, and TS without
/// dropping unknown fields).
impl<'de> Deserialize<'de> for ArtifactRecord {
    fn deserialize<D>(d: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value: serde_json::Value = serde_json::Value::deserialize(d)?;
        let obj = value
            .as_object()
            .ok_or_else(|| serde::de::Error::custom("artifact record must be an object"))?;
        let get = |k: &str| obj.get(k).cloned();
        let mut extra: serde_json::Map<String, serde_json::Value> = get("extra")
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        for (k, v) in obj {
            if !KNOWN_FIELDS.contains(&k.as_str()) {
                extra.insert(k.clone(), v.clone());
            }
        }
        Ok(ArtifactRecord {
            schema_version: get("schema_version").and_then(|v| v.as_u64()).unwrap_or(0),
            artifact_id: get("artifact_id")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_default(),
            workspace_relative_path: get("workspace_relative_path")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_default(),
            action: get("action")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_else(|| "created".to_string()),
            kind: get("kind")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_else(|| "deliverable".to_string()),
            media_type: get("media_type").and_then(|v| v.as_str().map(str::to_string)),
            label: get("label")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_default(),
            open_with: get("open_with")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_else(|| "preview".to_string()),
            producer: get("producer").unwrap_or(serde_json::Value::Null),
            state: get("state")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_else(|| "present".to_string()),
            provenance: get("provenance")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_default(),
            recorded_at: get("recorded_at")
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_default(),
            previous_path: get("previous_path").and_then(|v| v.as_str().map(str::to_string)),
            extra: serde_json::Value::Object(extra),
        })
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ArtifactIndex {
    pub schema_version: u64,
    pub revision: u64,
    #[serde(default)]
    pub artifacts: Vec<ArtifactRecord>,
}

// ---------------------------------------------------------------------------
// Data root / workspace hash (must match the Python CLI)
// ---------------------------------------------------------------------------

/// Host data root for artifact registries (never inside a workspace, R3-05).
/// Same convention as `src/aisc/application/artifact.py::data_root()`.
pub fn resolve_data_root() -> PathBuf {
    if let Ok(root) = std::env::var("AISC_ARTIFACT_DATA_ROOT") {
        if !root.is_empty() {
            return PathBuf::from(root);
        }
    }
    #[cfg(windows)]
    {
        let base = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| ".".to_string());
        return PathBuf::from(base).join("aisc").join("artifacts");
    }
    #[cfg(not(windows))]
    {
        if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
            if !xdg.is_empty() {
                return PathBuf::from(xdg).join("aisc").join("artifacts");
            }
        }
        if let Some(home) = dirs::home_dir() {
            return home.join(".local").join("share").join("aisc").join("artifacts");
        }
        PathBuf::from(".aisc-artifacts")
    }
}

/// Irreversible short hash of a canonical workspace path (matches the CLI).
///
/// On Windows, `fs::canonicalize` returns a `\\?\`-prefixed verbatim path,
/// while Python's `Path.resolve()` does not — strip the prefix so the hashes
/// agree and the Workbench reads the same registry the CLI wrote.
pub fn workspace_hash(workspace: &Path) -> String {
    let canon = fs::canonicalize(workspace).unwrap_or_else(|_| workspace.to_path_buf());
    let mut s = canon.to_string_lossy().into_owned();
    #[cfg(windows)]
    {
        if let Some(stripped) = s.strip_prefix(r"\\?\UNC\") {
            s = format!(r"\\{}", stripped);
        } else if let Some(stripped) = s.strip_prefix(r"\\?\") {
            s = stripped.to_string();
        }
    }
    let mut hasher = Sha256::new();
    hasher.update(s.as_bytes());
    let digest = hasher.finalize();
    digest[..8]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Directory holding one workspace's session registries (written by the CLI).
pub fn registry_dir(data_root: &Path, workspace: &Path) -> PathBuf {
    data_root.join(workspace_hash(workspace))
}

// ---------------------------------------------------------------------------
// CLI registry import
// ---------------------------------------------------------------------------

/// Parse one JSONL line into a validated record; returns None for a corrupt /
/// unsupported line (isolated, never truncates the file — A-ART01-2).
fn parse_record_line(line: &str) -> Option<ArtifactRecord> {
    let value: serde_json::Value = serde_json::from_str(line).ok()?;
    let sv = value.get("schema_version").and_then(|v| v.as_u64()).unwrap_or(0);
    if sv != ARTIFACT_SCHEMA_VERSION {
        return None; // unsupported schema: fail closed, do not import
    }
    let rec: ArtifactRecord = serde_json::from_value(value).ok()?;
    if rec.artifact_id.is_empty() || rec.workspace_relative_path.is_empty() {
        return None;
    }
    Some(rec)
}

/// Read all CLI session registries for a workspace into a merged record list.
/// Corrupt lines are skipped; a missing registry dir yields an empty list.
pub fn read_cli_registries(workspace: &Path) -> Vec<ArtifactRecord> {
    let root = resolve_data_root();
    let dir = registry_dir(&root, workspace);
    let mut out = Vec::new();
    let entries = match fs::read_dir(&dir) {
        Ok(e) => e,
        Err(_) => return out,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("jsonl") {
            continue;
        }
        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        for line in content.lines() {
            if let Some(rec) = parse_record_line(line) {
                out.push(rec);
            }
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Index persistence (revision + lock + atomic + corrupt isolation)
// ---------------------------------------------------------------------------

/// Index file location under the app config dir.
fn index_path(dir: &Path) -> PathBuf {
    dir.join(INDEX_FILE)
}

/// Load the merged index. Corrupt index is isolated (renamed .corrupt) and a
/// fresh index is returned so the app keeps working (A-ART01-2 / R3-07).
pub fn load_index(dir: &Path) -> ArtifactIndex {
    let path = index_path(dir);
    match fs::read_to_string(&path) {
        Ok(raw) => match serde_json::from_str::<ArtifactIndex>(&raw) {
            Ok(idx) if idx.schema_version == INDEX_SCHEMA_VERSION => idx,
            Ok(_) | Err(_) => {
                let _ = fs::rename(&path, path.with_extension("json.corrupt"));
                ArtifactIndex {
                    schema_version: INDEX_SCHEMA_VERSION,
                    revision: 0,
                    artifacts: Vec::new(),
                }
            }
        },
        Err(_) => ArtifactIndex {
            schema_version: INDEX_SCHEMA_VERSION,
            revision: 0,
            artifacts: Vec::new(),
        },
    }
}

fn acquire_lock(dir: &Path) -> Result<fs::File, WorkbenchError> {
    fs::create_dir_all(dir)
        .map_err(|e| WorkbenchError::history_error().with_detail(format!("mkdir: {e}")))?;
    let lock_path = dir.join(LOCK_FILE);
    let lock_file = fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|e| WorkbenchError::history_error().with_detail(format!("lock open: {e}")))?;
    let deadline = Instant::now() + LOCK_TIMEOUT;
    loop {
        match lock_file.try_lock_exclusive() {
            Ok(true) => break,
            Ok(false) => {
                if Instant::now() >= deadline {
                    return Err(WorkbenchError::history_error()
                        .with_detail("artifact index lock timeout"));
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(e) => {
                return Err(WorkbenchError::history_error()
                    .with_detail(format!("lock error: {e}")));
            }
        }
    }
    Ok(lock_file)
}

/// Import the CLI registries and persist a fresh merged index (revision bump).
/// Returns the new index.
pub fn import_registries(app: &AppHandle, workspace: &Path) -> Result<ArtifactIndex, WorkbenchError> {
    let dir = config_dir(app)?;
    let lock = acquire_lock(&dir)?;
    let result = import_locked(&dir, workspace);
    let _ = lock.unlock();
    result
}

fn import_locked(dir: &Path, workspace: &Path) -> Result<ArtifactIndex, WorkbenchError> {
    let records = read_cli_registries(workspace);
    let mut index = load_index(dir);
    // Deterministic merge: dedupe by artifact_id (latest line wins), sort by path.
    let mut by_id: std::collections::BTreeMap<String, ArtifactRecord> = std::collections::BTreeMap::new();
    for rec in records {
        by_id.insert(rec.artifact_id.clone(), rec);
    }
    let mut artifacts: Vec<ArtifactRecord> = by_id.into_values().collect();
    artifacts.sort_by(|a, b| a.workspace_relative_path.cmp(&b.workspace_relative_path));
    index.artifacts = artifacts;
    index.revision = index.revision.wrapping_add(1);
    let bytes = serde_json::to_vec(&index)
        .map_err(|e| WorkbenchError::history_error().with_detail(format!("serialize: {e}")))?;
    storage::atomic_replace(&dir.join(INDEX_FILE), &bytes)
        .map_err(|e| WorkbenchError::history_error().with_detail(format!("write: {e}")))?;
    Ok(index)
}

// ---------------------------------------------------------------------------
// IPC command payloads
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactListResult {
    pub schema_version: u64,
    pub artifacts: Vec<ArtifactRecord>,
    pub next_cursor: Option<usize>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactInspectResult {
    pub artifact: ArtifactRecord,
}

/// List artifacts from the merged index, filtered by kind, paginated.
pub fn list_artifacts(app: &AppHandle, kind: Option<String>, cursor: Option<usize>) -> ArtifactListResult {
    let dir = match config_dir(app) {
        Ok(d) => d,
        Err(_) => return empty_list(),
    };
    let index = load_index(&dir);
    let mut filtered: Vec<ArtifactRecord> = index
        .artifacts
        .into_iter()
        .filter(|a| kind.as_deref().map(|k| a.kind == k).unwrap_or(true))
        .collect();
    let start = cursor.unwrap_or(0).min(filtered.len());
    let page: Vec<ArtifactRecord> = filtered.drain(start..).take(200).collect();
    let next = if start + page.len() < filtered.len() + start {
        Some(start + page.len())
    } else {
        None
    };
    ArtifactListResult {
        schema_version: INDEX_SCHEMA_VERSION,
        artifacts: page,
        next_cursor: next,
    }
}

fn empty_list() -> ArtifactListResult {
    ArtifactListResult {
        schema_version: INDEX_SCHEMA_VERSION,
        artifacts: Vec::new(),
        next_cursor: None,
    }
}

pub fn inspect_artifact(app: &AppHandle, artifact_id: &str) -> Result<ArtifactInspectResult, WorkbenchError> {
    let dir = config_dir(app)?;
    let index = load_index(&dir);
    index
        .artifacts
        .iter()
        .find(|a| a.artifact_id == artifact_id)
        .cloned()
        .map(|artifact| ArtifactInspectResult { artifact })
        .ok_or_else(|| {
            WorkbenchError::cli_protocol()
                .with_detail(format!("artifact not found: {artifact_id}"))
        })
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn artifact_list(
    app: AppHandle,
    kind: Option<String>,
    cursor: Option<usize>,
) -> Result<ArtifactListResult, WorkbenchError> {
    Ok(list_artifacts(&app, kind, cursor))
}

#[tauri::command]
pub async fn artifact_inspect(
    app: AppHandle,
    artifact_id: String,
) -> Result<ArtifactInspectResult, WorkbenchError> {
    inspect_artifact(&app, &artifact_id)
}

#[tauri::command]
pub async fn artifact_refresh(
    app: AppHandle,
    workspace: String,
) -> Result<ArtifactIndex, WorkbenchError> {
    import_registries(&app, Path::new(&workspace))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn parse_valid_record_line() {
        let line = r#"{"schema_version":1,"artifact_id":"aaaaaaaa-0000-4000-8000-000000000001","workspace_relative_path":"reports/result.md","action":"created","kind":"deliverable","media_type":"text/markdown","label":"报告","open_with":"preview","producer":{"agent":"claude","session_id":"22222222-2222-4222-8222-222222222222","runtime_id":"11111111-1111-4111-8111-111111111111"},"state":"present","provenance":"manifest","recorded_at":"2026-08-15T00:00:00Z","extra":{}}"#;
        let rec = parse_record_line(line).expect("valid line");
        assert_eq!(rec.workspace_relative_path, "reports/result.md");
        assert_eq!(rec.kind, "deliverable");
        assert_eq!(rec.provenance, "manifest");
        assert_eq!(rec.extra, serde_json::json!({}));
    }

    #[test]
    fn unsupported_schema_line_fails_closed() {
        let line = r#"{"schema_version":99,"artifact_id":"x","workspace_relative_path":"a.md"}"#;
        assert!(parse_record_line(line).is_none());
    }

    #[test]
    fn corrupt_line_is_isolated() {
        assert!(parse_record_line("not json at all").is_none());
        assert!(parse_record_line(r#"{"schema_version":1,"artifact_id":""}"#).is_none());
    }

    #[test]
    fn unknown_fields_survive_round_trip() {
        let line = r#"{"schema_version":1,"artifact_id":"aaaaaaaa-0000-4000-8000-000000000001","workspace_relative_path":"a.md","x_future":{"kept":true}}"#;
        let rec = parse_record_line(line).expect("parses");
        assert_eq!(rec.extra, serde_json::json!({"x_future": {"kept": true}}));
    }

    #[test]
    fn index_corrupt_is_isolated_and_recovers() {
        let dir = tempdir().unwrap();
        let idx_path = index_path(dir.path());
        fs::write(&idx_path, "this is not json").unwrap();
        let index = load_index(dir.path());
        assert_eq!(index.schema_version, INDEX_SCHEMA_VERSION);
        assert!(index.artifacts.is_empty());
        // The corrupt file is renamed, not deleted.
        assert!(idx_path.with_extension("json.corrupt").exists());
    }

    #[test]
    fn workspace_hash_is_stable_and_short() {
        let dir = tempdir().unwrap();
        let h1 = workspace_hash(dir.path());
        let h2 = workspace_hash(dir.path());
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 16);
    }
}
