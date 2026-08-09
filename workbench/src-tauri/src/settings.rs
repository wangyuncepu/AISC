//! `settings.json` persistence for the pinned AISC CLI path.
//!
//! Spec: 02-startup-flow.md §九.1 (schema) + §九 强制要求 (atomic write, schema
//! mismatch preserves file). S1.2 only manages `schema_version` + `aisc_cli_path`;
//! unknown fields are preserved so later slices can extend the schema.
//!
//! GAP: cross-process advisory locking is deferred to S2.4 (`history.rs` slice,
//! which owns the cross-platform lock implementation). S1.2 uses atomic
//! replace only -- acceptable because pin writes are low-contention startup
//! operations from a single Workbench process.

use std::fs;
use std::io;
use std::path::Path;

use serde_json::Value;

use crate::storage;

const SCHEMA_VERSION: u64 = 1;
const SETTINGS_FILE: &str = "settings.json";

#[derive(Debug)]
pub enum SettingsError {
    Io(String),
    /// File exists but is not valid JSON.
    Corrupt(String),
    /// File schema_version is missing or unsupported. The original file is
    /// left untouched so the user can recover it (02 §九).
    UnsupportedSchema { found: Option<u64> },
}

impl std::fmt::Display for SettingsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(m) => write!(f, "settings io error: {m}"),
            Self::Corrupt(m) => write!(f, "settings.json corrupted: {m}"),
            Self::UnsupportedSchema { found } => match found {
                Some(v) => write!(f, "unsupported settings schema_version: {v}"),
                None => write!(f, "settings.json missing schema_version"),
            },
        }
    }
}

impl std::error::Error for SettingsError {}

/// Backing store is the raw JSON document so unknown fields survive round-trips.
#[derive(Debug, Clone)]
pub struct Settings {
    raw: Value,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            raw: serde_json::json!({
                "schema_version": SCHEMA_VERSION,
                "aisc_cli_path": null,
            }),
        }
    }
}

impl Settings {
    /// Load from `dir/settings.json`. Missing file -> default. Existing file
    /// with unsupported schema -> `UnsupportedSchema` (caller must not overwrite).
    pub fn load(dir: &Path) -> Result<Self, SettingsError> {
        let path = dir.join(SETTINGS_FILE);
        match fs::read(&path) {
            Ok(bytes) => {
                let raw: Value =
                    serde_json::from_slice(&bytes).map_err(|e| SettingsError::Corrupt(e.to_string()))?;
                let found = raw.get("schema_version").and_then(|v| v.as_u64());
                if found != Some(SCHEMA_VERSION) {
                    return Err(SettingsError::UnsupportedSchema { found });
                }
                Ok(Self { raw })
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(SettingsError::Io(e.to_string())),
        }
    }

    pub fn aisc_cli_path(&self) -> Option<&str> {
        self.raw
            .get("aisc_cli_path")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
    }

    pub fn set_aisc_cli_path(&mut self, path: Option<&str>) {
        match path {
            Some(p) => {
                self.raw["aisc_cli_path"] = Value::String(p.to_string());
            }
            None => {
                self.raw["aisc_cli_path"] = Value::Null;
            }
        }
    }

    /// Atomically write to `dir/settings.json` (temp + fsync + replace).
    pub fn save(&self, dir: &Path) -> Result<(), SettingsError> {
        fs::create_dir_all(dir).map_err(|e| SettingsError::Io(e.to_string()))?;
        let target = dir.join(SETTINGS_FILE);
        let bytes = serde_json::to_vec_pretty(&self.raw)
            .map_err(|e| SettingsError::Corrupt(e.to_string()))?;
        storage::atomic_replace(&target, &bytes).map_err(|e| SettingsError::Io(e.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn load_missing_file_yields_default() {
        let dir = tempdir().unwrap();
        let s = Settings::load(dir.path()).expect("missing file -> default");
        assert_eq!(s.aisc_cli_path(), None);
    }

    #[test]
    fn round_trip_pin() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("/usr/local/bin/aisc"));
        s.save(dir.path()).unwrap();

        let loaded = Settings::load(dir.path()).unwrap();
        assert_eq!(loaded.aisc_cli_path(), Some("/usr/local/bin/aisc"));
    }

    #[test]
    fn clear_pin_persists_null() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("/x/aisc"));
        s.save(dir.path()).unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(None);
        s.save(dir.path()).unwrap();
        assert_eq!(Settings::load(dir.path()).unwrap().aisc_cli_path(), None);
    }

    #[test]
    fn unknown_fields_preserved() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.raw["default_agent"] = Value::String("codex".into());
        s.raw["custom_future_field"] = Value::Number(42.into());
        s.set_aisc_cli_path(Some("/p/aisc"));
        s.save(dir.path()).unwrap();

        let loaded = Settings::load(dir.path()).unwrap();
        assert_eq!(loaded.aisc_cli_path(), Some("/p/aisc"));
        assert_eq!(loaded.raw.get("default_agent").and_then(|v| v.as_str()), Some("codex"));
        assert_eq!(loaded.raw.get("custom_future_field").and_then(|v| v.as_u64()), Some(42));
    }

    #[test]
    fn unsupported_schema_is_error_and_not_overwritten() {
        let dir = tempdir().unwrap();
        let bad = serde_json::json!({"schema_version": 999, "aisc_cli_path": "/x"});
        fs::write(dir.path().join(SETTINGS_FILE), serde_json::to_vec(&bad).unwrap()).unwrap();

        let err = Settings::load(dir.path()).unwrap_err();
        assert!(matches!(
            err,
            SettingsError::UnsupportedSchema { found: Some(999) }
        ));
        // Original file untouched.
        let on_disk: Value =
            serde_json::from_slice(&fs::read(dir.path().join(SETTINGS_FILE)).unwrap()).unwrap();
        assert_eq!(on_disk.get("schema_version").and_then(|v| v.as_u64()), Some(999));
    }

    #[test]
    fn corrupt_json_is_error() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(SETTINGS_FILE), b"{not json").unwrap();
        assert!(matches!(
            Settings::load(dir.path()),
            Err(SettingsError::Corrupt(_))
        ));
    }
}
