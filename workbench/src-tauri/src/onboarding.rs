//! Onboarding state persistence (Stage 5, ONB-01).
//!
//! Schema-versioned `onboarding.json` tracking the first-run wizard: status
//! (`not_started` → `in_progress` → `skipped|blocked|completed|abandoned`),
//! current/completed/skipped steps, last error code and the handoff source.
//! Cross-process advisory locking (fs4) + atomic replace, mirroring
//! `history.rs` (A-ONB01-1: high-version read-only, corrupt isolation, upgrade
//! keeps completion but allows flow-version re-run of verification steps).
//!
//! **Never stores secrets** (D5-05): only status + step bookkeeping.

use std::fs;
use std::io;
use std::path::Path;
use std::time::{Duration, Instant};

use fs4::fs_std::FileExt;
use serde::{Deserialize, Serialize};

use crate::error::WorkbenchError;
use crate::storage;

const SCHEMA_VERSION: u64 = 1;
const FLOW_VERSION: u64 = 1;
const ONBOARDING_FILE: &str = "onboarding.json";
const LOCK_FILE: &str = "onboarding.lock";
const CORRUPT_SUFFIX: &str = ".corrupt";
const LOCK_TIMEOUT: Duration = Duration::from_millis(1000);
const LOCK_POLL: Duration = Duration::from_millis(20);

// ---------------------------------------------------------------------------
// Domain state (onboarding.schema/state, 02-domain-contract.md)
// ---------------------------------------------------------------------------

/// Coarse wizard status.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OnboardingStatus {
    NotStarted,
    InProgress,
    Skipped,
    Blocked,
    Completed,
    Abandoned,
}

impl Default for OnboardingStatus {
    fn default() -> Self {
        Self::NotStarted
    }
}

/// The onboarding schema document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OnboardingState {
    #[serde(default)]
    pub schema_version: u64,
    #[serde(default)]
    pub flow_version: u64,
    #[serde(default)]
    pub status: OnboardingStatus,
    /// Current step when in_progress (e.g. "environment" | "workspace" | "agent"
    /// | "network" | "runtime" | "complete").
    #[serde(default)]
    pub current_step: String,
    #[serde(default)]
    pub completed_steps: Vec<String>,
    #[serde(default)]
    pub skipped_steps: Vec<String>,
    /// Last stable error code so the UI can offer retry/doctor (never secret).
    #[serde(default)]
    pub last_error_code: String,
    /// Installer handoff source (non-sensitive; never a fact — D5-07).
    #[serde(default)]
    pub source: String,
    /// Unknown root fields survive round-trips (A-INFRA-5).
    #[serde(default, flatten)]
    pub extra: serde_json::Value,
}

impl OnboardingState {
    pub fn empty() -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            flow_version: FLOW_VERSION,
            status: OnboardingStatus::NotStarted,
            current_step: String::new(),
            completed_steps: Vec::new(),
            skipped_steps: Vec::new(),
            last_error_code: String::new(),
            source: String::new(),
            extra: serde_json::Value::Object(Default::default()),
        }
    }

    /// A step is complete (for the wizard's progress display).
    pub fn is_step_complete(&self, step: &str) -> bool {
        self.completed_steps.iter().any(|s| s == step)
    }

    pub fn is_skipped(&self, step: &str) -> bool {
        self.skipped_steps.iter().any(|s| s == step)
    }

    /// Onboarding is finished (completed, or explicitly skipped/abandoned).
    pub fn is_finished(&self) -> bool {
        matches!(
            self.status,
            OnboardingStatus::Completed
                | OnboardingStatus::Skipped
                | OnboardingStatus::Abandoned
        )
    }
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub enum OnboardingError {
    Io(String),
    Corrupt(String),
    UnsupportedSchema { found: Option<u64> },
    LockTimeout,
}

impl std::fmt::Display for OnboardingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "onboarding io: {e}"),
            Self::Corrupt(e) => write!(f, "onboarding corrupt: {e}"),
            Self::UnsupportedSchema { found } => {
                write!(f, "unsupported onboarding schema_version: {found:?}")
            }
            Self::LockTimeout => write!(f, "onboarding lock timeout"),
        }
    }
}

impl std::error::Error for OnboardingError {}

fn isolate_corrupt(dir: &Path) {
    let path = dir.join(ONBOARDING_FILE);
    let _ = fs::rename(&path, dir.join(format!("{ONBOARDING_FILE}{CORRUPT_SUFFIX}")));
}

/// Load `dir/onboarding.json` and normalize to the current schema.
///
/// Missing → empty (not_started). Corrupt JSON → isolate to `.corrupt` and
/// return empty so the app starts. A file with NO schema_version at all is
/// not an onboarding document (7f gate: test/foreign junk at this path
/// deadlocked the wizard behind UnsupportedSchema) → isolate + empty.
/// Unsupported (newer) schema → error, file untouched, saves refused
/// (A-ONB01-1).
pub fn load(dir: &Path) -> Result<OnboardingState, OnboardingError> {
    let path = dir.join(ONBOARDING_FILE);
    match fs::read(&path) {
        Ok(bytes) => {
            let value: serde_json::Value = match serde_json::from_slice(&bytes) {
                Ok(v) => v,
                Err(e) => {
                    isolate_corrupt(dir);
                    return Err(OnboardingError::Corrupt(e.to_string()));
                }
            };
            let found = value.get("schema_version").and_then(|v| v.as_u64());
            match found {
                Some(v) if v == SCHEMA_VERSION => {
                    match serde_json::from_value::<OnboardingState>(value) {
                        Ok(s) => Ok(s),
                        Err(e) => {
                            isolate_corrupt(dir);
                            Err(OnboardingError::Corrupt(e.to_string()))
                        }
                    }
                }
                None => {
                    // Not an onboarding document: isolate and start fresh
                    // (bytes preserved under *.corrupt for inspection).
                    isolate_corrupt(dir);
                    Ok(OnboardingState::empty())
                }
                other => Err(OnboardingError::UnsupportedSchema { found: other }),
            }
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(OnboardingState::empty()),
        Err(e) => Err(OnboardingError::Io(e.to_string())),
    }
}

/// Acquire the cross-process exclusive lock with a bounded wait (fail-closed on
/// timeout: no lockless write, 02 §九).
fn acquire_lock(dir: &Path) -> Result<fs::File, OnboardingError> {
    let lock_path = dir.join(LOCK_FILE);
    let lock_file = fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|e| OnboardingError::Io(e.to_string()))?;
    let deadline = Instant::now() + LOCK_TIMEOUT;
    loop {
        match lock_file.try_lock_exclusive() {
            Ok(true) => break,
            Ok(false) => {
                if Instant::now() >= deadline {
                    return Err(OnboardingError::LockTimeout);
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(e) => return Err(OnboardingError::Io(e.to_string())),
        }
    }
    Ok(lock_file)
}

/// Persist `state` to `dir/onboarding.json` under the cross-process lock with
/// an atomic replace (02 §九: no lockless write; a failed write never truncates).
pub fn save(dir: &Path, state: &OnboardingState) -> Result<(), OnboardingError> {
    // Ensure the config dir exists BEFORE opening the lock file — `acquire_lock`
    // uses `create(true)` which creates the file but NOT parent directories, so
    // a fresh install (dir absent until something writes it) failed the first
    // `onboarding_update` with NotFound → WB_ERR_SETTINGS stuck the wizard on
    // the welcome screen ("Workbench 配置读取失败", manual test 2026-08-16).
    // settings.rs already mirrors this (create_dir_all before the locked write).
    fs::create_dir_all(dir).map_err(|e| OnboardingError::Io(e.to_string()))?;
    let path = dir.join(ONBOARDING_FILE);
    let lock_file = acquire_lock(dir)?;
    let bytes = serde_json::to_vec(state)
        .map_err(|e| OnboardingError::Io(e.to_string()))?;
    storage::atomic_replace(&path, &bytes)
        .map_err(|e| OnboardingError::Io(e.to_string()))?;
    let _ = lock_file.unlock();
    Ok(())
}

/// Apply a mutation to the persisted onboarding state under the lock: load →
/// mutate → save. Returns the updated state. Missing file starts empty.
pub fn update<F>(dir: &Path, f: F) -> Result<OnboardingState, OnboardingError>
where
    F: FnOnce(&mut OnboardingState),
{
    let mut state = load(dir)?;
    f(&mut state);
    save(dir, &state)?;
    Ok(state)
}

// ---------------------------------------------------------------------------
// Tauri commands (Rust keeps the authoritative state; no secrets)
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn onboarding_load(app: tauri::AppHandle) -> Result<OnboardingState, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    load(&dir).map_err(map_error)
}

#[tauri::command]
pub async fn onboarding_update(
    app: tauri::AppHandle,
    patch: OnboardingPatch,
) -> Result<OnboardingState, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    update(&dir, |s| patch.apply(s)).map_err(map_error)
}

/// A minimal, validated patch from the frontend. Every field is optional;
/// unknown/empty values are ignored. Never carries secrets.
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OnboardingPatch {
    pub status: Option<OnboardingStatus>,
    pub current_step: Option<String>,
    pub complete_step: Option<String>,
    pub skip_step: Option<String>,
    pub last_error_code: Option<String>,
    pub source: Option<String>,
}

impl OnboardingPatch {
    fn apply(&self, s: &mut OnboardingState) {
        if let Some(status) = &self.status {
            s.status = status.clone();
        }
        if let Some(step) = &self.current_step {
            if !step.is_empty() {
                s.current_step = step.clone();
            }
        }
        if let Some(step) = &self.complete_step {
            if !step.is_empty() && !s.completed_steps.iter().any(|x| x == step) {
                s.completed_steps.push(step.clone());
                s.skipped_steps.retain(|x| x != step);
            }
        }
        if let Some(step) = &self.skip_step {
            if !step.is_empty() && !s.skipped_steps.iter().any(|x| x == step) {
                s.skipped_steps.push(step.clone());
                s.completed_steps.retain(|x| x != step);
            }
        }
        if let Some(code) = &self.last_error_code {
            if !code.is_empty() {
                s.last_error_code = code.clone();
            }
        }
        if let Some(src) = &self.source {
            if !src.is_empty() {
                s.source = src.clone();
            }
        }
    }
}

fn map_error(e: OnboardingError) -> WorkbenchError {
    match e {
        OnboardingError::Io(msg) => {
            WorkbenchError::settings_error().with_detail(format!("onboarding: {msg}"))
        }
        OnboardingError::Corrupt(msg) => {
            WorkbenchError::settings_error().with_detail(format!("onboarding corrupt: {msg}"))
        }
        OnboardingError::UnsupportedSchema { found } => WorkbenchError::settings_error()
            .with_detail(format!("unsupported onboarding schema_version: {found:?}")),
        OnboardingError::LockTimeout => WorkbenchError::settings_error()
            .with_detail("onboarding lock timeout"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn save_creates_missing_config_dir() {
        // Fresh install: the config dir may not exist yet. `save` must create it
        // before opening the lock file, or the first patch bricks the wizard
        // with WB_ERR_SETTINGS (manual test 2026-08-16).
        let parent = tempdir().unwrap();
        let dir = parent.path().join("deep/nested/cn.aisc.workbench");
        let s = update(&dir, |s| {
            s.status = OnboardingStatus::InProgress;
            s.current_step = "environment".into();
        })
        .unwrap();
        assert_eq!(s.status, OnboardingStatus::InProgress);
        assert!(dir.join(ONBOARDING_FILE).exists());
        // Reloadable from the created dir.
        assert_eq!(load(&dir).unwrap().current_step, "environment");
    }

    /// REL-03: an onboarding.json written by a PREVIOUS release (same schema 1,
    /// missing newer optional fields source/last_error_code/completed_steps)
    /// loads with defaults and upgrades without losing the in-progress step.
    #[test]
    fn previous_version_onboarding_loads_with_defaults() {
        let dir = tempdir().unwrap();
        fs::write(
            dir.path().join(ONBOARDING_FILE),
            r#"{"schema_version":1,"flow_version":1,"status":"in_progress","current_step":"workspace"}"#,
        )
        .unwrap();
        let s = load(dir.path()).unwrap();
        assert_eq!(s.status, OnboardingStatus::InProgress);
        assert_eq!(s.current_step, "workspace");
        assert!(s.completed_steps.is_empty());
        assert_eq!(s.source, "");
        assert_eq!(s.last_error_code, "");

        // Upgrade path: a later patch on the previous-version file works and
        // round-trips.
        let updated = update(dir.path(), |st| st.completed_steps.push("workspace".into())).unwrap();
        assert!(updated.is_step_complete("workspace"));
        let reloaded = load(dir.path()).unwrap();
        assert!(reloaded.is_step_complete("workspace"));
    }

    /// 7f gate: a file with NO schema_version is not an onboarding document
    /// (test/foreign junk at the config path) — isolate + empty so the
    /// wizard starts instead of deadlocking behind UnsupportedSchema.
    #[test]
    fn non_onboarding_file_is_isolated_and_starts_fresh() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(ONBOARDING_FILE), r#"{"b":2}"#).unwrap();
        let s = load(dir.path()).unwrap();
        assert_eq!(s.status, OnboardingStatus::NotStarted);
        assert!(dir.path().join(format!("{ONBOARDING_FILE}{CORRUPT_SUFFIX}")).is_file());
        // The isolated bytes are preserved and a subsequent save works.
        let updated = update(dir.path(), |st| st.status = OnboardingStatus::InProgress).unwrap();
        assert_eq!(updated.status, OnboardingStatus::InProgress);
    }

    #[test]
    fn missing_file_yields_not_started() {
        let dir = tempdir().unwrap();
        let s = load(dir.path()).unwrap();
        assert_eq!(s.status, OnboardingStatus::NotStarted);
        assert!(s.completed_steps.is_empty());
    }

    #[test]
    fn roundtrip_persists_state() {
        let dir = tempdir().unwrap();
        let s = update(dir.path(), |s| {
            s.status = OnboardingStatus::InProgress;
            s.current_step = "environment".into();
            s.completed_steps.push("welcome".into());
            s.source = "installer".into();
        })
        .unwrap();
        assert_eq!(s.current_step, "environment");

        let reloaded = load(dir.path()).unwrap();
        assert_eq!(reloaded.status, OnboardingStatus::InProgress);
        assert_eq!(reloaded.current_step, "environment");
        assert!(reloaded.is_step_complete("welcome"));
        assert_eq!(reloaded.source, "installer");
    }

    #[test]
    fn corrupt_file_is_isolated_and_fails_closed() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(ONBOARDING_FILE), b"{ not json").unwrap();
        let err = load(dir.path()).unwrap_err();
        assert!(matches!(err, OnboardingError::Corrupt(_)));
        // Original file moved aside; app can start on defaults.
        assert!(dir.path().join(format!("{ONBOARDING_FILE}{CORRUPT_SUFFIX}")).exists());
    }

    #[test]
    fn unsupported_schema_fails_closed() {
        let dir = tempdir().unwrap();
        fs::write(
            dir.path().join(ONBOARDING_FILE),
            r#"{"schema_version":99,"status":"completed"}"#,
        )
        .unwrap();
        let err = load(dir.path()).unwrap_err();
        assert!(matches!(err, OnboardingError::UnsupportedSchema { .. }));
        // Original file untouched.
        assert!(!dir.path().join(format!("{ONBOARDING_FILE}{CORRUPT_SUFFIX}")).exists());
    }

    #[test]
    fn patch_applies_complete_and_skip() {
        let mut s = OnboardingState::empty();
        let p = OnboardingPatch {
            complete_step: Some("workspace".into()),
            ..Default::default()
        };
        p.apply(&mut s);
        assert!(s.is_step_complete("workspace"));

        let p2 = OnboardingPatch {
            skip_step: Some("workspace".into()),
            ..Default::default()
        };
        p2.apply(&mut s);
        assert!(s.is_skipped("workspace"));
        assert!(!s.is_step_complete("workspace"));
    }

    #[test]
    fn finished_states_cover_skip_and_abandon() {
        let mut s = OnboardingState::empty();
        s.status = OnboardingStatus::Skipped;
        assert!(s.is_finished());
        s.status = OnboardingStatus::Abandoned;
        assert!(s.is_finished());
        s.status = OnboardingStatus::InProgress;
        assert!(!s.is_finished());
    }
}
