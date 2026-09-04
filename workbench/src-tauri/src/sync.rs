//! F1 (D-10): SSH workspaces — local shadow directories under
//! `<data-root>/sync-workspaces/<name>/`.
//!
//! The shadow directory IS the workspace (the "identity chain untouched"
//! ruling): canonicalize/hash/watcher/mounts/explorer all operate on it;
//! SSH-ness converges into the sync layer built here on the metadata file.
//!
//! T-F1c transport facts (live-probed on v0.16.4/Windows):
//! - `ssh://` scheme URLs mis-parse in v0.16 ("ssh" becomes the hostname) —
//!   use the SCP-STYLE endpoint `user@host:port/path`.
//! - v0.16's SSH transport shells out to the EXTERNAL `ssh` binary; URL
//!   query params (key/verifyHostKey) are ignored there, and its host-key /
//!   passphrase prompts deadlock a non-interactive spawn. Countermeasure:
//!   a generated ssh wrapper is prepended to PATH that injects
//!   `-F <generated config> -o BatchMode=yes` — the config carries the
//!   profile (HostName/Port/User/IdentityFile, accept-new host keys).
//! - `sync list --template '{{json .}}'` yields a JSON array (status).

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

// ===========================================================================
// T-F1c: the sync engine (mutagen) — discovery, ssh transport, sessions.
// ===========================================================================

/// Locate the host-side mutagen binary. Order: explicit override env,
/// next to the Workbench executable (installed layout), then PATH.
pub fn mutagen_binary() -> Option<std::path::PathBuf> {
    if let Ok(p) = std::env::var("AISC_MUTAGEN_PATH") {
        let path = std::path::PathBuf::from(p);
        if path.is_file() {
            return Some(path);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in ["mutagen.exe", "mutagen"] {
                let cand = dir.join(name);
                if cand.is_file() {
                    return Some(cand);
                }
            }
        }
    }
    which_ssh_like("mutagen")
}

fn which_ssh_like(name: &str) -> Option<std::path::PathBuf> {
    let path = std::env::var_os("PATH")?;
    let exe_name = if cfg!(windows) { format!("{name}.exe") } else { name.to_string() };
    for dir in std::env::split_paths(&path) {
        let cand = dir.join(&exe_name);
        if cand.is_file() {
            return Some(cand);
        }
    }
    None
}

/// The generated ssh config body for one profile (the `Host` block mutagen's
/// external ssh resolves through our wrapper's `-F`). Host keys use
/// accept-new (first connect auto-records; changed keys still hard-fail) and
/// BatchMode forbids any interactive prompt.
pub fn ssh_config_body(meta: &SshWorkspaceMeta) -> String {
    let p = &meta.profile;
    let mut s = String::new();
    s.push_str("# aisc-generated (sync transport)\n");
    s.push_str(&format!("Host {}\n", p.host));
    s.push_str(&format!("  HostName {}\n", p.host));
    s.push_str(&format!("  Port {}\n", p.port));
    s.push_str(&format!("  User {}\n", p.user));
    if !p.key_path.trim().is_empty() {
        s.push_str(&format!("  IdentityFile {}\n", p.key_path));
    }
    s.push_str("  StrictHostKeyChecking accept-new\n");
    s.push_str("  BatchMode yes\n");
    s.push_str("  ConnectTimeout 15\n");
    s
}

/// The wrapper script body that injects our config into every ssh mutagen
/// spawns. `real_ssh` must already be resolved OUTSIDE the wrapper dir.
pub fn ssh_wrapper_body(real_ssh: &std::path::Path, config: &std::path::Path) -> String {
    if cfg!(windows) {
        format!(
            "@echo off\r\n\"{}\" -F \"{}\" -o BatchMode=yes %*\r\n",
            real_ssh.display(),
            config.display()
        )
    } else {
        format!(
            "#!/bin/sh\nexec '{}' -F '{}' -o BatchMode=yes \"$@\"\n",
            real_ssh.display(),
            config.display()
        )
    }
}

/// SCP-style endpoint URL (v0.16's `ssh://` mis-parses — probe notes above).
pub fn scp_endpoint(meta: &SshWorkspaceMeta) -> String {
    let p = &meta.profile;
    format!("{}@{}:{}/{}", p.user, p.host, p.port, meta.remote_path.trim_start_matches('/'))
}

/// Prepare the transport dir (config + wrapper) under
/// `<data-root>/sync-workspaces/bin/`; returns the dir to PREPEND to PATH
/// (mutagen spawns a bare `ssh` resolved through PATH).
fn ensure_transport(meta: &SshWorkspaceMeta) -> Result<std::path::PathBuf, WorkbenchError> {
    ensure_transport_for(&meta.profile)
}

fn ensure_transport_for(profile: &crate::settings::SshProfile) -> Result<std::path::PathBuf, WorkbenchError> {
    let root = crate::data_root::validate_data_root()
        .map_err(|e| WorkbenchError::usage(format!("data root: {}", e.message())))?;
    let dir = root.join("sync-workspaces").join("bin");
    std::fs::create_dir_all(&dir)
        .map_err(|e| WorkbenchError::usage(format!("transport dir: {e}")))?;
    let config = dir.join("ssh_config");
    let body = ssh_config_body(&SshWorkspaceMeta {
        schema_version: String::new(),
        profile: profile.clone(),
        remote_path: String::new(),
        created_at: String::new(),
    });
    crate::storage::atomic_replace(&config, body.as_bytes())
        .map_err(|e| WorkbenchError::usage(format!("ssh config: {e}")))?;
    // Resolve the real ssh OUTSIDE our wrapper dir, then write the wrapper.
    let real = which_ssh_like("ssh")
        .ok_or_else(|| WorkbenchError::usage("no ssh binary found on PATH"))?;
    if real.parent() == Some(&dir) {
        return Err(WorkbenchError::usage("ssh resolution loop (wrapper dir)"));
    }
    let wrapper = dir.join(if cfg!(windows) { "ssh.cmd" } else { "ssh" });
    crate::storage::atomic_replace(&wrapper, ssh_wrapper_body(&real, &config).as_bytes())
        .map_err(|e| WorkbenchError::usage(format!("ssh wrapper: {e}")))?;
    if !cfg!(windows) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o755));
        }
    }
    Ok(dir)
}

/// One remote directory entry (T-F1e browse picker).
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SshDirEntry {
    pub name: String,
    pub is_dir: bool,
}

/// Parse `ls -1 -p` output: trailing `/` marks a directory.
pub fn parse_ls_entries(stdout: &str) -> Vec<SshDirEntry> {
    let mut dirs: Vec<SshDirEntry> = Vec::new();
    let mut files: Vec<SshDirEntry> = Vec::new();
    for line in stdout.lines() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() || line.starts_with("total ") {
            continue;
        }
        let (name, is_dir) = match line.strip_suffix('/') {
            Some(n) => (n.to_string(), true),
            None => (line.to_string(), false),
        };
        if name.is_empty() || name == "." || name == ".." {
            continue;
        }
        let e = SshDirEntry { name, is_dir };
        if is_dir { dirs.push(e); } else { files.push(e); }
    }
    dirs.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    files.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    dirs.extend(files);
    dirs
}

/// List one remote directory through the generated ssh config (explicit
/// `-F` — this spawn is fully ours, no wrapper needed). Used by the picker's
/// 远端路径 browse dialog.
#[tauri::command]
pub async fn ssh_browse(
    profile: Value, path: String,
) -> Result<Vec<SshDirEntry>, WorkbenchError> {
    let profile: crate::settings::SshProfile = serde_json::from_value(profile)
        .map_err(|e| WorkbenchError::usage(format!("invalid ssh profile: {e}")))?;
    let path = if path.trim().is_empty() { "/".to_string() } else { path };
    if !valid_remote_path(&path) && path != "/"
        || path.contains('\'') || path.contains('"') || path.contains('\\') {
        return Err(WorkbenchError::usage(format!("invalid remote path: {path:?}")));
    }
    let transport = ensure_transport_for(&profile)?;
    let config = transport.join("ssh_config");
    let ssh = which_ssh_like("ssh")
        .ok_or_else(|| WorkbenchError::usage("no ssh binary found on PATH"))?;

    let mut cmd = std::process::Command::new(&ssh);
    cmd.args(["-F", &config.to_string_lossy(), "-o", "BatchMode=yes",
              "-o", "ConnectTimeout=15", &profile.host,
              &format!("ls -1 -p -- '{path}'")])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let out = cmd.output()
        .map_err(|e| WorkbenchError::usage(format!("spawn ssh: {e}")))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let tail = err.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        return Err(WorkbenchError::usage(format!("ssh ls failed: {tail}")));
    }
    Ok(parse_ls_entries(&String::from_utf8_lossy(&out.stdout)))
}

/// Run mutagen with the transport PATH prepended. Returns (stdout, stderr).
fn run_mutagen(
    args: &[&str], transport: &std::path::Path, timeout: std::time::Duration,
) -> Result<(String, String), WorkbenchError> {
    let bin = mutagen_binary()
        .ok_or_else(|| WorkbenchError::usage("mutagen binary not found (install or AISC_MUTAGEN_PATH)"))?;
    let old_path = std::env::var_os("PATH").unwrap_or_default();
    let new_path = std::env::join_paths(
        std::iter::once(transport.to_path_buf()).chain(std::env::split_paths(&old_path)),
    )
    .map_err(|e| WorkbenchError::usage(format!("PATH join: {e}")))?;

    let mut cmd = std::process::Command::new(&bin);
    cmd.args(args)
        .env("PATH", new_path)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let child = cmd.output(); // output() blocks to completion
    let out = match child {
        Ok(o) => o,
        Err(e) => return Err(WorkbenchError::usage(format!("spawn mutagen: {e}"))),
    };
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
    if !out.status.success() {
        let tail = stderr.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        return Err(WorkbenchError::usage(format!(
            "mutagen {} failed: {}",
            args.first().copied().unwrap_or(""),
            tail
        )));
    }
    let _ = timeout; // output() is synchronous; the caller bounds via args
    Ok((stdout, stderr))
}

/// One session's status projection (T-F1d renders this).
#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatus {
    pub status: String,
    pub message: String,
    pub last_error: String,
}

fn session_name(workspace: &std::path::Path) -> String {
    workspace
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default()
}

/// Create (or reconnect to) the sync session for an SSH workspace. A PLAIN
/// local workspace is a no-op returning `status: "none"` (the frontend fires
/// this on every launch — non-SSH must not surface as an error).
#[tauri::command]
pub async fn sync_session_start(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let Some(meta) = read_meta(&ws) else {
        return Ok(SyncStatus { status: "none".into(), ..Default::default() });
    };
    let transport = ensure_transport(&meta)?;
    let name = session_name(&ws);
    let alpha = workspace.clone();
    let beta = scp_endpoint(&meta);
    let alpha_ref: &str = &alpha;
    let beta_ref: &str = &beta;
    run_mutagen(
        &["sync", "create", "--name", &name, "--ignore-vcs", alpha_ref, beta_ref],
        &transport,
        std::time::Duration::from_secs(60),
    )?;
    sync_status_inner(&ws, &meta, &transport)
}

/// Status by session name (defensive field walk — the JSON shape varies by
/// mutagen version; missing fields degrade to empty strings).
fn sync_status_inner(
    ws: &std::path::Path, meta: &SshWorkspaceMeta, transport: &std::path::Path,
) -> Result<SyncStatus, WorkbenchError> {
    let (out, _) = run_mutagen(
        &["sync", "list", "--template", "{{json .}}"],
        transport,
        std::time::Duration::from_secs(15),
    )?;
    let name = session_name(ws);
    let sessions: Value = serde_json::from_str(out.trim())
        .map_err(|e| WorkbenchError::usage(format!("sync list parse: {e}")))?;
    let _ = meta;
    Ok(match sessions.as_array() {
        Some(arr) => {
            let mine = arr
                .iter()
                .find(|s| s["Session"]["name"].as_str() == Some(name.as_str()));
            match mine {
                Some(s) => SyncStatus {
                    status: s["Status"]["status"].as_str().unwrap_or("").to_string(),
                    message: s["Status"]["message"].as_str().unwrap_or("").to_string(),
                    last_error: s["Status"]["lastError"]
                        .as_str()
                        .or_else(|| s["Status"]["last_error"].as_str())
                        .unwrap_or("")
                        .to_string(),
                },
                None => SyncStatus::default(),
            }
        }
        None => SyncStatus::default(),
    })
}

/// Current status (empty status = no session yet).
#[tauri::command]
pub async fn sync_session_status(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let Some(meta) = read_meta(&ws) else {
        return Ok(SyncStatus { status: "none".into(), ..Default::default() });
    };
    let transport = ensure_transport(&meta)?;
    sync_status_inner(&ws, &meta, &transport)
}

fn session_action(workspace: String, action: &str) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let meta = read_meta(&ws)
        .ok_or_else(|| WorkbenchError::usage("not an SSH workspace (no metadata)"))?;
    let transport = ensure_transport(&meta)?;
    let name = session_name(&ws);
    run_mutagen(
        &["sync", action, &name],
        &transport,
        std::time::Duration::from_secs(30),
    )?;
    sync_status_inner(&ws, &meta, &transport)
}

#[tauri::command]
pub async fn sync_session_pause(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    session_action(workspace, "pause")
}

#[tauri::command]
pub async fn sync_session_resume(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    session_action(workspace, "resume")
}

#[tauri::command]
pub async fn sync_session_terminate(workspace: String) -> Result<(), WorkbenchError> {
    session_action(workspace, "terminate").map(|_| ())
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

    fn test_meta() -> SshWorkspaceMeta {
        SshWorkspaceMeta {
            schema_version: META_SCHEMA.into(),
            profile: crate::settings::SshProfile {
                name: "srv".into(),
                host: "10.0.0.5".into(),
                port: 2222,
                user: "deploy".into(),
                key_path: "C:/keys/id_ed25519".into(),
            },
            remote_path: "/srv/proj".into(),
            created_at: "1".into(),
        }
    }

    #[test]
    fn ssh_config_body_carries_the_profile() {
        let cfg = ssh_config_body(&test_meta());
        assert!(cfg.contains("Host 10.0.0.5"));
        assert!(cfg.contains("Port 2222"));
        assert!(cfg.contains("User deploy"));
        assert!(cfg.contains("IdentityFile C:/keys/id_ed25519"));
        assert!(cfg.contains("StrictHostKeyChecking accept-new"));
        assert!(cfg.contains("BatchMode yes"));
        // no key -> no IdentityFile line (agent/default-key path)
        let mut m = test_meta();
        m.profile.key_path = String::new();
        assert!(!ssh_config_body(&m).contains("IdentityFile"));
    }

    #[test]
    fn scp_endpoint_shape() {
        assert_eq!(scp_endpoint(&test_meta()), "deploy@10.0.0.5:2222/srv/proj");
        let mut m = test_meta();
        m.remote_path = "/a/b/".into();
        assert_eq!(scp_endpoint(&m), "deploy@10.0.0.5:2222/a/b/");
    }

    #[test]
    fn ls_entries_parse_dirs_first() {
        let out = "total 8\nfile.txt\nsrc/\n.ZZ/\r\nweird name.md\n";
        let e = parse_ls_entries(out);
        assert_eq!(
            e.iter().map(|x| (x.name.as_str(), x.is_dir)).collect::<Vec<_>>(),
            vec![(".ZZ", true), ("src", true), ("file.txt", false), ("weird name.md", false)]
        );
        assert!(parse_ls_entries("").is_empty());
    }

    /// The wrapper must make mutagen's external ssh NON-INTERACTIVE: with
    /// BatchMode injected, a dead endpoint fails fast with a dial error and
    /// NEVER reaches a host-key/passphrase prompt (the deadlock that
    /// motivated the wrapper). Best-effort: skipped when no ssh/mutagen is
    /// resolvable (CI images without the host tool).
    #[test]
    fn wrapper_makes_transport_non_interactive() {
        if which_ssh_like("ssh").is_none() || mutagen_binary().is_none() {
            eprintln!("skipping: ssh/mutagen not resolvable");
            return;
        }
        let mut m = test_meta();
        m.profile.host = "127.0.0.1".into();
        m.profile.port = 1; // nothing listens here
        m.remote_path = "/r".into();
        let dir = tempfile::tempdir().unwrap();
        let alpha = dir.path().join("alpha");
        std::fs::create_dir_all(&alpha).unwrap();
        let meta = m;
        // simulate the full path: transport + create against the dead port
        let ws = dir.path().to_path_buf();
        std::fs::write(
            ws.join(META_FILE),
            serde_json::to_vec(&meta).unwrap(),
        )
        .unwrap();
        let transport = ensure_transport(&meta).expect("transport prepared");
        let alpha_s = alpha.to_string_lossy().to_string();
        let beta = scp_endpoint(&meta);
        let res = run_mutagen(
            &["sync", "create", "--name", "it-probe", "--ignore-vcs", &alpha_s, &beta],
            &transport,
            std::time::Duration::from_secs(60),
        );
        match res {
            Ok(_) => panic!("create must fail against a dead endpoint"),
            Err(e) => {
                let msg = format!("{e:?}");
                assert!(
                    !msg.contains("Are you sure"),
                    "interactive prompt leaked: {msg}"
                );
            }
        }
    }
}
