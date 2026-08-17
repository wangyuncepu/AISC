// Data root contract (Stage 7, 7a) — Rust mirror of
// `src/aisc/domain/data_root.py` + `src/aisc/application/data_root.py`.
//
// The Workbench must never concatenate data-root paths itself
// (01-cross-stage-contracts §1): everything comes from this resolver, kept in
// sync with the Python SSOT via `tests/fixtures/data-root/hash-vectors.json`
// (consumed by tests on both sides).
//
// `resolve` is READ-ONLY (lifecycle contract): it validates and reports;
// directory creation is `prepare` (7b), never here.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

pub const DATA_ROOT_PROTOCOL: &str = "aisc.data-root/v1";
pub const DATA_ROOT_SCHEMA_VERSION: u32 = 1;

/// Versioned workspace isolation hash (D7-02). `sha256-v1:<64 hex>` in JSON
/// fields; directory names swap the colon for a dash (illegal on Windows).
pub const WORKSPACE_HASH_ALGO: &str = "sha256-v1";

pub const SHARED_SUBDIRS: [&str; 7] = [
    "config",
    "state",
    "workspaces",
    "artifacts",
    "cache",
    "diagnostics",
    "migrations",
];

pub const WORKSPACE_SUBDIRS: [&str; 5] = ["claude", "codex", "cc-switch", "runtime", "logs"];

const ENV_OVERRIDE: &str = "AISC_DATA_ROOT";

// Stable error codes (mirror the Python constants; exit mapping is the
// caller's job — the Workbench surfaces codes in diagnostics).
pub const ERR_OVERRIDE_RELATIVE: &str = "AISC_ERR_DATA_ROOT_OVERRIDE_RELATIVE";
pub const ERR_REPARSE_POINT: &str = "AISC_ERR_DATA_ROOT_REPARSE_POINT";
pub const ERR_WORKSPACE_OVERLAP: &str = "AISC_ERR_DATA_ROOT_WORKSPACE_OVERLAP";

// windows.h FILE_ATTRIBUTE_REPARSE_POINT (symlink, junction, OneDrive
// placeholder, app-exec link — any tag, per D7-04 fail-closed).
#[cfg(windows)]
const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DataRootError {
    /// `AISC_DATA_ROOT` is not an absolute path (or has whitespace edges).
    OverrideInvalid(String),
    /// A path component of the root is a reparse point/symlink.
    ReparsePoint(PathBuf),
    /// The root and the workspace are not disjoint subtrees.
    WorkspaceOverlap(PathBuf),
}

impl DataRootError {
    pub fn code(&self) -> &'static str {
        match self {
            DataRootError::OverrideInvalid(_) => ERR_OVERRIDE_RELATIVE,
            DataRootError::ReparsePoint(_) => ERR_REPARSE_POINT,
            DataRootError::WorkspaceOverlap(_) => ERR_WORKSPACE_OVERLAP,
        }
    }

    pub fn message(&self) -> String {
        match self {
            DataRootError::OverrideInvalid(v) => {
                format!("{ENV_OVERRIDE} must be an absolute path: {v:?}")
            }
            DataRootError::ReparsePoint(p) => {
                format!("data root path component is a reparse point/symlink: {}", p.display())
            }
            DataRootError::WorkspaceOverlap(p) => {
                format!("data root overlaps the workspace: {}", p.display())
            }
        }
    }
}

/// Structured resolver result. Path maps are name → absolute path in contract
/// order (BTreeMap keeps a stable, comparable ordering for diagnostics).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedDataRoot {
    pub root: PathBuf,
    pub origin: &'static str, // "default" | "env"
    pub workspace_hash: String,
    pub writable: bool,
    pub shared_dirs: BTreeMap<&'static str, PathBuf>,
    pub workspace_dirs: BTreeMap<&'static str, PathBuf>,
}

impl ResolvedDataRoot {
    /// `workspaces/<hash>/` — the per-workspace subtree root.
    pub fn workspace_dir(&self) -> PathBuf {
        self.shared_dirs["workspaces"].join(workspace_dir_name(&self.workspace_hash))
    }
}

/// Drop Windows verbatim (`\\?\`) prefixes so both languages hash the same
/// string (Rust `canonicalize` adds the prefix; the Python `resolve()` does
/// not). Extracted from `artifact.rs::workspace_hash` semantics.
pub fn strip_verbatim(path_str: &str) -> String {
    if let Some(stripped) = path_str.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{stripped}")
    } else if let Some(stripped) = path_str.strip_prefix(r"\\?\") {
        stripped.to_string()
    } else {
        path_str.to_string()
    }
}

/// Canonical absolute path string used as the hash input (non-strict: a
/// missing workspace canonicalizes as-given, matching the Python side).
pub fn canonical_workspace_path(workspace: &Path) -> String {
    let canon = fs::canonicalize(workspace).unwrap_or_else(|_| workspace.to_path_buf());
    strip_verbatim(&canon.to_string_lossy())
}

/// Pure hash of an ALREADY-canonical path string → `sha256-v1:<64 hex>`
/// (full digest, not the 16-hex artifact-registry short form — D7-02).
pub fn hash_canonical_path(canon: &str) -> String {
    let digest = Sha256::digest(canon.as_bytes());
    format!("{WORKSPACE_HASH_ALGO}:{}", hex(&digest))
}

pub fn workspace_hash_v1(workspace: &Path) -> String {
    hash_canonical_path(&canonical_workspace_path(workspace))
}

/// Windows-safe directory form: `sha256-v1:<hex>` → `sha256-v1-<hex>`.
pub fn workspace_dir_name(workspace_hash: &str) -> String {
    workspace_hash.replacen(':', "-", 1)
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

/// Platform default root, injectable for tests: `%LOCALAPPDATA%\AISC\data`
/// on Windows, XDG data elsewhere (the CLI/container stay cross-platform,
/// D-24). Mirrors `_default_root` in `application/data_root.py`.
pub fn default_root_from(
    localappdata: Option<&str>,
    xdg_data_home: Option<&str>,
    home: Option<&Path>,
) -> PathBuf {
    if cfg!(windows) {
        let base = match localappdata {
            Some(s) => PathBuf::from(s),
            None => home
                .map(|h| h.join("AppData").join("Local"))
                .unwrap_or_default(),
        };
        return base.join("AISC").join("data");
    }
    if let Some(xdg) = xdg_data_home.filter(|s| !s.is_empty()) {
        return PathBuf::from(xdg).join("aisc").join("data");
    }
    home.map(|h| h.join(".local").join("share").join("aisc").join("data"))
        .unwrap_or_else(|| PathBuf::from(".aisc-data"))
}

pub fn default_data_root() -> PathBuf {
    default_root_from(
        std::env::var("LOCALAPPDATA").ok().as_deref(),
        std::env::var("XDG_DATA_HOME").ok().as_deref(),
        dirs::home_dir().as_deref(),
    )
}

/// Resolve (and validate, but never create) the data root for one workspace.
pub fn resolve_data_root(workspace: &Path) -> Result<ResolvedDataRoot, DataRootError> {
    let (root, origin) = select_root()?;
    check_overlap(&root, workspace)?;
    check_reparse_segments(&root)?;
    Ok(build_result(root, origin, workspace))
}

/// Workbench app-state dir (Stage 7, DATA-04): `<data-root>/config`.
///
/// Adopts the legacy Tauri `app_config_dir` state files copy-when-absent on
/// first use (settings/history/onboarding/artifacts index); never
/// overwrites, sources are kept so a downgrade keeps working. If the data
/// root cannot be VALIDATED (reparse/relative override), falls back to the
/// legacy dir — app state must stay loadable (writes through the CLI still
/// fail closed there).
pub fn app_state_dir(legacy: Option<&Path>) -> PathBuf {
    let dir = match validate_data_root() {
        Ok(root) => root.join("config"),
        Err(_) => {
            return legacy.map(|p| p.to_path_buf()).unwrap_or(default_data_root().join("config"))
        }
    };
    if let Some(legacy) = legacy {
        for name in ["settings.json", "history.json", "onboarding.json", "artifacts.json"] {
            adopt_file(&legacy.join(name), &dir.join(name));
        }
    }
    dir
}

/// Full root selection + validation (override shape + reparse walk),
/// reusable without a workspace.
pub fn validate_data_root() -> Result<PathBuf, DataRootError> {
    let (root, _origin) = select_root()?;
    check_reparse_segments(&root)?;
    Ok(root)
}

/// Copy src→dst only when dst is absent (hardlink create = no-overwrite
/// under a concurrent adopter; never touches the source).
fn adopt_file(src: &Path, dst: &Path) {
    if dst.exists() || !src.is_file() {
        return;
    }
    if let Some(parent) = dst.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let tmp = dst.with_extension("adopt.tmp");
    if fs::copy(src, &tmp).is_err() {
        let _ = fs::remove_file(&tmp);
        return;
    }
    // Link-then-unlink: creating the link fails atomically if a concurrent
    // adopter already placed the file.
    match fs::hard_link(&tmp, dst) {
        Ok(()) => {
            let _ = fs::remove_file(&tmp);
        }
        Err(_) => {
            let _ = fs::remove_file(&tmp);
        }
    }
}

fn select_root() -> Result<(PathBuf, &'static str), DataRootError> {
    if let Ok(override_raw) = std::env::var(ENV_OVERRIDE) {
        if !override_raw.is_empty() {
            // Whitespace edges are a misconfiguration, not something to trim
            // silently (Python domain/config.py precedent).
            if override_raw != override_raw.trim() || !Path::new(&override_raw).is_absolute() {
                return Err(DataRootError::OverrideInvalid(override_raw));
            }
            return Ok((PathBuf::from(override_raw), "env"));
        }
    }
    Ok((default_data_root(), "default"))
}

/// The data root and the workspace must be disjoint subtrees: a root inside
/// the workspace recreates DATA-01 pollution; a workspace inside the root
/// lets migration/quarantine touch user files.
fn check_overlap(root: &Path, workspace: &Path) -> Result<(), DataRootError> {
    let root_c = fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let ws_c = fs::canonicalize(workspace).unwrap_or_else(|_| workspace.to_path_buf());
    if root_c == ws_c || root_c.starts_with(&ws_c) || ws_c.starts_with(&root_c) {
        return Err(DataRootError::WorkspaceOverlap(root_c));
    }
    Ok(())
}

/// Reject reparse points/symlinks on any EXISTING segment of the root path
/// (01-risk-analysis: junction escapes → arbitrary paths).
pub fn check_reparse_segments(root: &Path) -> Result<(), DataRootError> {
    let mut cur = root.to_path_buf();
    loop {
        if let Ok(meta) = fs::symlink_metadata(&cur) {
            let is_reparse = meta.file_type().is_symlink() || {
                #[cfg(windows)]
                {
                    use std::os::windows::fs::MetadataExt;
                    meta.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
                }
                #[cfg(not(windows))]
                {
                    false
                }
            };
            if is_reparse {
                return Err(DataRootError::ReparsePoint(cur));
            }
        }
        match cur.parent() {
            Some(parent) if parent != cur => cur = parent.to_path_buf(),
            _ => return Ok(()),
        }
    }
}

fn build_result(
    root: PathBuf,
    origin: &'static str,
    workspace: &Path,
) -> ResolvedDataRoot {
    let workspace_hash = workspace_hash_v1(workspace);
    let shared_dirs: BTreeMap<&'static str, PathBuf> = SHARED_SUBDIRS
        .iter()
        .map(|name| (*name, root.join(name)))
        .collect();
    let ws_root_dir = shared_dirs["workspaces"].join(workspace_dir_name(&workspace_hash));
    let workspace_dirs: BTreeMap<&'static str, PathBuf> = WORKSPACE_SUBDIRS
        .iter()
        .map(|name| (*name, ws_root_dir.join(name)))
        .collect();
    ResolvedDataRoot {
        root,
        origin,
        workspace_hash,
        writable: probe_writable(&shared_dirs["workspaces"]),
        shared_dirs,
        workspace_dirs,
    }
}

/// Informational writability probe on the nearest existing ancestor
/// (`prepare` fails closed on real writes).
fn probe_writable(path: &Path) -> bool {
    let mut cur = path.to_path_buf();
    loop {
        if cur.exists() {
            // Windows `access(W_OK)` is near-useless for directories; a
            // metadata read keeps this a cheap read-only best-effort probe.
            #[cfg(windows)]
            {
                return fs::metadata(&cur).map(|_| true).unwrap_or(false);
            }
            #[cfg(not(windows))]
            {
                use std::os::unix::fs::PermissionsExt;
                return fs::metadata(&cur)
                    .map(|m| m.permissions().mode() & 0o200 != 0)
                    .unwrap_or(false);
            }
        }
        match cur.parent() {
            Some(parent) if parent != cur => cur = parent.to_path_buf(),
            _ => return false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::{Mutex, MutexGuard};

    // Tests that mutate AISC_DATA_ROOT serialize on this lock (cargo runs
    // tests in parallel threads; env is process-global).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn lock_env() -> MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn vectors_path() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/data-root/hash-vectors.json")
    }

    #[test]
    fn hash_vectors_match_python() {
        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(vectors_path()).unwrap()).unwrap();
        for v in doc["hash_vectors"].as_array().unwrap() {
            let canonical = v["canonical"].as_str().unwrap();
            let expected = v["hash"].as_str().unwrap();
            assert_eq!(hash_canonical_path(canonical), expected, "vector {canonical:?}");
        }
    }

    #[test]
    fn strip_vectors_match_python() {
        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(vectors_path()).unwrap()).unwrap();
        for v in doc["strip_vectors"].as_array().unwrap() {
            let verbatim = v["verbatim"].as_str().unwrap();
            let stripped = v["stripped"].as_str().unwrap();
            assert_eq!(strip_verbatim(verbatim), stripped);
        }
    }

    #[test]
    fn workspace_dir_name_is_windows_safe() {
        let h = hash_canonical_path("/x");
        let name = workspace_dir_name(&h);
        assert!(!name.contains(':'));
        assert!(name.starts_with("sha256-v1-"));
        assert_eq!(name.len(), "sha256-v1-".len() + 64);
    }

    #[test]
    fn default_root_branches() {
        // The platform branch is compile-time; assert the branch that this
        // build actually takes so a config swap can't drift silently.
        if cfg!(windows) {
            let win = default_root_from(Some("C:\\u\\AppData\\Local"), None, None);
            assert_eq!(win, PathBuf::from("C:\\u\\AppData\\Local").join("AISC").join("data"));
        } else {
            let xdg = default_root_from(None, Some("/opt/xdg"), None);
            assert_eq!(xdg, PathBuf::from("/opt/xdg/aisc/data"));
            let home = default_root_from(None, None, Some(Path::new("/home/dev")));
            assert_eq!(home, PathBuf::from("/home/dev/.local/share/aisc/data"));
        }
    }

    #[test]
    fn resolve_builds_contract_layout() {
        let _env = lock_env();
        let ws = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap(); // disjoint from ws
        std::env::set_var(ENV_OVERRIDE, root.path());
        let result = resolve_data_root(ws.path()).unwrap();
        std::env::remove_var(ENV_OVERRIDE);

        assert_eq!(result.origin, "env");
        assert_eq!(result.root, root.path());
        assert_eq!(result.shared_dirs.len(), SHARED_SUBDIRS.len());
        assert_eq!(result.workspace_dirs.len(), WORKSPACE_SUBDIRS.len());
        for name in SHARED_SUBDIRS {
            assert_eq!(result.shared_dirs[name], root.path().join(name));
        }
        let ws_dir = result.workspace_dir();
        for name in WORKSPACE_SUBDIRS {
            assert_eq!(result.workspace_dirs[name], ws_dir.join(name));
        }
        // resolve is read-only: nothing was created.
        assert!(!ws_dir.exists());
        assert!(!result.shared_dirs["config"].exists());
    }

    #[test]
    fn workspace_overlap_rejected() {
        let _env = lock_env();
        let ws = tempfile::tempdir().unwrap();
        let root = ws.path().join("nested-root");
        fs::create_dir_all(&root).unwrap();
        std::env::set_var(ENV_OVERRIDE, &root);
        let err = resolve_data_root(ws.path()).unwrap_err();
        std::env::remove_var(ENV_OVERRIDE);
        assert_eq!(err.code(), ERR_WORKSPACE_OVERLAP);
    }

    #[test]
    fn relative_override_rejected() {
        let _env = lock_env();
        std::env::set_var(ENV_OVERRIDE, "relative/data");
        let err = resolve_data_root(Path::new("/definitely/not/overlapping/ws")).unwrap_err();
        std::env::remove_var(ENV_OVERRIDE);
        assert_eq!(err.code(), ERR_OVERRIDE_RELATIVE);
    }

    #[test]
    fn app_state_dir_adopts_legacy_without_overwrite() {
        let _env = lock_env();
        let legacy = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        fs::write(legacy.path().join("settings.json"), r#"{"a":1}"#).unwrap();
        fs::write(legacy.path().join("onboarding.json"), r#"{"b":2}"#).unwrap();

        // Keep the override for BOTH calls — a stray default-root resolve
        // would adopt into the real %LOCALAPPDATA%.
        std::env::set_var(ENV_OVERRIDE, root.path());
        let dir = app_state_dir(Some(legacy.path()));

        assert_eq!(dir, root.path().join("config"));
        assert_eq!(
            fs::read_to_string(dir.join("settings.json")).unwrap(),
            r#"{"a":1}"#
        );
        assert!(dir.join("onboarding.json").is_file());
        // Locks/transients are not adopted.
        assert!(!dir.join("settings.json.lock").exists());
        // Sources kept for downgrade compatibility.
        assert!(legacy.path().join("settings.json").is_file());

        // No-overwrite: existing canonical state wins over legacy.
        fs::write(dir.join("settings.json"), r#"{"canonical":true}"#).unwrap();
        fs::write(legacy.path().join("settings.json"), r#"{"stale":1}"#).unwrap();
        let dir2 = app_state_dir(Some(legacy.path()));
        std::env::remove_var(ENV_OVERRIDE);
        assert_eq!(dir2, dir);
        assert_eq!(
            fs::read_to_string(dir2.join("settings.json")).unwrap(),
            r#"{"canonical":true}"#
        );
    }

    #[test]
    fn app_state_dir_falls_back_to_legacy_on_invalid_root() {
        let _env = lock_env();
        let legacy = tempfile::tempdir().unwrap();
        // Relative override cannot be validated → keep the legacy dir.
        std::env::set_var(ENV_OVERRIDE, "relative/data");
        let dir = app_state_dir(Some(legacy.path()));
        std::env::remove_var(ENV_OVERRIDE);
        assert_eq!(dir, legacy.path());
    }

    #[test]
    fn reparse_point_on_root_path_rejected() {
        let _env = lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let real = tmp.path().join("real-root");
        let link = tmp.path().join("link-root");
        fs::create_dir_all(&real).unwrap();
        // cfg! branches both compile — use cfg attributes per platform.
        #[cfg(windows)]
        let made = std::process::Command::new("cmd")
            .args(["/c", "mklink", "/J"])
            .arg(&link)
            .arg(&real)
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        #[cfg(not(windows))]
        let made = std::os::unix::fs::symlink(&real, &link).is_ok();
        if !made {
            // No symlink privilege in this environment (skipped, not passed).
            return;
        }
        std::env::set_var(ENV_OVERRIDE, &link);
        let err = resolve_data_root(&tmp.path().join("unrelated-ws")).unwrap_err();
        std::env::remove_var(ENV_OVERRIDE);
        assert_eq!(err.code(), ERR_REPARSE_POINT);
    }
}
