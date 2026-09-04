//! F1 (D-10): SSH workspaces — local shadow directories under
//! `<data-root>/sync-workspaces/<name>/`.
//!
//! The shadow directory IS the workspace (the "identity chain untouched"
//! ruling): canonicalize/hash/watcher/mounts/explorer all operate on it;
//! SSH-ness converges into the sync layer that T-F1c builds on the metadata
//! file written here.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::WorkbenchError;

const META_SCHEMA: &str = "aisc.ssh-workspace/v1";
const META_FILE: &str = ".aisc-ssh-workspace.json";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SshWorkspaceMeta {
    pub schema_version: String,
    /// Snapshot of the connection profile at creation time (the sync layer
    /// reads THIS, not live settings — a later profile edit never silently
    /// rewires an existing workspace).
    pub profile: crate::settings::SshProfile,
    /// Absolute POSIX path on the remote.
    pub remote_path: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SshWorkspaceCreated {
    pub workspace_path: String,
}

/// Workspace names: one leading alnum then alnum/-/_ up to 64 — no path
/// separators, no dots (blocks `..`, hidden dirs, and extension tricks).
pub fn valid_workspace_name(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphanumeric() => {}
        _ => return false,
    }
    name.len() <= 64
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// Remote paths are absolute POSIX (`/...`) and not just "/".
pub fn valid_remote_path(p: &str) -> bool {
    p.starts_with('/') && p.len() > 1 && !p.contains('\0')
}

/// Create the shadow directory + metadata. Refuses an existing directory
/// (a same-named workspace must be reopened, not overwritten).
#[tauri::command]
pub async fn ssh_workspace_create(
    name: String,
    profile: Value,
    remote_path: String,
) -> Result<SshWorkspaceCreated, WorkbenchError> {
    if !valid_workspace_name(&name) {
        return Err(WorkbenchError::usage("workspace name must be alphanumeric/-/_ (max 64), got {name:?}"));
    }
    if !valid_remote_path(&remote_path) {
        return Err(WorkbenchError::usage("remote path must be an absolute POSIX path"));
    }
    let profile: crate::settings::SshProfile = serde_json::from_value(profile)
        .map_err(|e| WorkbenchError::usage(format!("invalid ssh profile: {e}")))?;

    let root = crate::data_root::validate_data_root()
        .map_err(|e| WorkbenchError::usage(format!("data root: {}", e.message())))?;
    let dir = root.join("sync-workspaces").join(&name);
    if dir.exists() {
        return Err(WorkbenchError::usage(format!(
            "sync workspace already exists: {}",
            dir.display()
        )));
    }
    std::fs::create_dir_all(&dir)
        .map_err(|e| WorkbenchError::usage(format!("create shadow dir: {e}")))?;

    let meta = SshWorkspaceMeta {
        schema_version: META_SCHEMA.to_string(),
        profile,
        remote_path,
        created_at: now_iso(),
    };
    let bytes = serde_json::to_vec_pretty(&meta)
        .map_err(|e| WorkbenchError::usage(format!("encode metadata: {e}")))?;
    crate::storage::atomic_replace(&dir.join(META_FILE), &bytes)
        .map_err(|e| WorkbenchError::usage(format!("write metadata: {e}")))?;

    Ok(SshWorkspaceCreated {
        workspace_path: dir.to_string_lossy().to_string(),
    })
}

/// Read the SSH metadata of a shadow directory (None when it is a plain
/// local workspace). T-F1c's sync layer uses this to find its session.
pub fn read_meta(workspace: &std::path::Path) -> Option<SshWorkspaceMeta> {
    let text = std::fs::read_to_string(workspace.join(META_FILE)).ok()?;
    let meta: SshWorkspaceMeta = serde_json::from_str(&text).ok()?;
    (meta.schema_version == META_SCHEMA).then_some(meta)
}

fn now_iso() -> String {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs().to_string())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_name_rules() {
        assert!(valid_workspace_name("office"));
        assert!(valid_workspace_name("dev-2_server"));
        assert!(!valid_workspace_name(""));
        assert!(!valid_workspace_name("-lead"));
        assert!(!valid_workspace_name("a/b"));
        assert!(!valid_workspace_name("a.b"));
        assert!(!valid_workspace_name(".."));
        assert!(!valid_workspace_name(&"x".repeat(65)));
    }

    #[test]
    fn remote_path_rules() {
        assert!(valid_remote_path("/home/me/proj"));
        assert!(!valid_remote_path("relative/path"));
        assert!(!valid_remote_path("/"));
        assert!(!valid_remote_path("C:/x"));
    }

    #[test]
    fn meta_roundtrip_rejects_foreign_schema() {
        let dir = tempfile::tempdir().unwrap();
        let p = crate::settings::SshProfile {
            name: "srv".into(),
            host: "10.0.0.5".into(),
            port: 22,
            user: "me".into(),
            key_path: "".into(),
        };
        let meta = SshWorkspaceMeta {
            schema_version: META_SCHEMA.into(),
            profile: p,
            remote_path: "/srv/proj".into(),
            created_at: "1".into(),
        };
        std::fs::write(
            dir.path().join(META_FILE),
            serde_json::to_vec(&meta).unwrap(),
        )
        .unwrap();
        let back = read_meta(dir.path()).expect("reads back");
        assert_eq!(back.remote_path, "/srv/proj");

        // foreign/absent schema -> None (plain local workspace)
        let mut foreign = meta;
        foreign.schema_version = "aisc.ssh-workspace/v9".into();
        std::fs::write(
            dir.path().join(META_FILE),
            serde_json::to_vec(&foreign).unwrap(),
        )
        .unwrap();
        assert!(read_meta(dir.path()).is_none());
    }
}
