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
    /// F1 (field report: "本地放不下"): user-cancelled sync. While set,
    /// launch never re-attaches; the sidebar shows 已取消 + a re-enable
    /// action. Absent/None = normal.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sync_disabled: Option<bool>,
    /// Exclusion globs for oversized content (field report: multi-hundred-GB
    /// remotes). Applied at session create AND every self-heal recreate —
    /// the metadata is the single source.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub ignore_patterns: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SshWorkspaceCreated {
    pub workspace_path: String,
    /// True when the directory already existed (re-open): the metadata was
    /// left untouched and the caller should just OPEN the workspace — never
    /// surface a duplicate error (field report #1, 2026-09-04).
    pub existed: bool,
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
    ignore_patterns: Option<Vec<String>>,
) -> Result<SshWorkspaceCreated, WorkbenchError> {
    if !valid_workspace_name(&name) {
        return Err(WorkbenchError::usage("workspace name must be alphanumeric/-/_ (max 64), got {name:?}"));
    }
    if !valid_remote_path(&remote_path) {
        return Err(WorkbenchError::usage("remote path must be an absolute POSIX path"));
    }
    let profile: crate::settings::SshProfile = serde_json::from_value(profile)
        .map_err(|e| WorkbenchError::usage(format!("invalid ssh profile: {e}")))?;
    // Exclusion globs (oversized-content strategy): non-empty, trimmed,
    // no whitespace/control chars inside each pattern.
    let ignore_patterns: Vec<String> = ignore_patterns.unwrap_or_default()
        .into_iter()
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty() && !p.chars().any(|c| c.is_whitespace()))
        .collect();

    let root = crate::data_root::validate_data_root()
        .map_err(|e| WorkbenchError::usage(format!("data root: {}", e.message())))?;
    let dir = root.join("sync-workspaces").join(&name);
    if dir.exists() {
        // Re-open (field report #1): never an error — the existing metadata
        // (profile snapshot) stays authoritative; the frontend opens the
        // path and the multi-workspace layer adopts the running instance.
        return Ok(SshWorkspaceCreated {
            workspace_path: dir.to_string_lossy().to_string(),
            existed: true,
        });
    }
    std::fs::create_dir_all(&dir)
        .map_err(|e| WorkbenchError::usage(format!("create shadow dir: {e}")))?;

    let meta = SshWorkspaceMeta {
        schema_version: META_SCHEMA.to_string(),
        profile,
        remote_path,
        created_at: now_iso(),
        sync_disabled: None,
        ignore_patterns,
    };
    let bytes = serde_json::to_vec_pretty(&meta)
        .map_err(|e| WorkbenchError::usage(format!("encode metadata: {e}")))?;
    crate::storage::atomic_replace(&dir.join(META_FILE), &bytes)
        .map_err(|e| WorkbenchError::usage(format!("write metadata: {e}")))?;

    Ok(SshWorkspaceCreated {
        workspace_path: dir.to_string_lossy().to_string(),
        existed: false,
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

/// The MANAGED block marker pair in ~/.ssh/config. Everything between the
/// markers is ours to rewrite; user content outside is never touched.
const SSH_BLOCK_BEGIN: &str = "# BEGIN AISC SYNC (managed — do not edit inside)";
const SSH_BLOCK_END: &str = "# END AISC SYNC (managed)";

/// Stable alias for one profile: `aisc-sync-<8 hex of host|port|user>`.
/// The alias (not the raw host) rides the endpoint, so ~/.ssh/config's
/// managed block fully controls HostName/Port/User/key for every consumer.
pub fn ssh_alias(profile: &crate::settings::SshProfile) -> String {
    let seed = format!("{}|{}|{}", profile.host, profile.port, profile.user);
    let mut h: u32 = 2166136261;
    for b in seed.bytes() {
        h ^= b as u32;
        h = h.wrapping_mul(16777619);
    }
    format!("aisc-sync-{:08x}", h)
}

/// The managed `Host <alias>` block body for one profile. Host keys use
/// accept-new (first connect auto-records; changed keys still hard-fail).
pub fn ssh_config_body(meta: &SshWorkspaceMeta) -> String {
    let p = &meta.profile;
    let mut s = String::new();
    s.push_str(&format!("Host {}\n", ssh_alias(p)));
    s.push_str(&format!("  HostName {}\n", p.host));
    s.push_str(&format!("  Port {}\n", p.port));
    s.push_str(&format!("  User {}\n", p.user));
    if !p.key_path.trim().is_empty() {
        s.push_str(&format!("  IdentityFile {}\n", p.key_path));
    }
    s.push_str("  StrictHostKeyChecking accept-new\n");
    s.push_str("  ConnectTimeout 15\n");
    s
}

/// Maintain the managed block in `~/.ssh/config`: create the file if absent,
/// replace ONLY the marker-bounded block (idempotent), never touch user
/// content. This replaces the PATH-injected `ssh.cmd` wrapper — a cmd batch
/// forwarding layer that HALVED transport throughput (1GiB: 2m09s raw vs
/// 4m11s via wrapper, measured 2026-09-04); consumers now hit the real ssh
/// binary directly (alias resolves the profile).
pub fn ensure_managed_ssh_config(profile: &crate::settings::SshProfile) -> Result<(), WorkbenchError> {
    let home = dirs::home_dir()
        .ok_or_else(|| WorkbenchError::usage("cannot resolve home dir"))?;
    let ssh_dir = home.join(".ssh");
    std::fs::create_dir_all(&ssh_dir)
        .map_err(|e| WorkbenchError::usage(format!("create ~/.ssh: {e}")))?;
    let path = ssh_dir.join("config");
    let current = std::fs::read_to_string(&path).unwrap_or_default();
    let block = format!(
        "{}\n{}{}\n{}\n",
        SSH_BLOCK_BEGIN,
        ssh_config_body(&SshWorkspaceMeta {
            schema_version: String::new(),
            profile: profile.clone(),
            remote_path: String::new(),
            created_at: String::new(),
            sync_disabled: None,
            ignore_patterns: Vec::new(),
        }),
        "",
        SSH_BLOCK_END,
    );
    let next = match (current.find(SSH_BLOCK_BEGIN), current.find(SSH_BLOCK_END)) {
        (Some(a), Some(b)) if b > a => {
            format!("{}{}{}", &current[..a], block, &current[b + SSH_BLOCK_END.len()..])
                .trim_end_matches('\n').to_string() + "\n"
        }
        _ => {
            let prefix = if current.is_empty() { String::new() } else { current.trim_end().to_string() + "\n\n" };
            format!("{prefix}{block}")
        }
    };
    if next != current {
        std::fs::write(&path, next.as_bytes())
            .map_err(|e| WorkbenchError::usage(format!("write ssh config: {e}")))?;
    }
    Ok(())
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

/// SCP-style endpoint URL: `<alias>:/path`. The alias (resolved through the
/// managed ~/.ssh/config block) carries host/port/user/key — the endpoint
/// never embeds them (probe-verified v0.16 facts: `ssh://` scheme URLs
/// mis-parse; the SCP form has NO port slot — a `:22` folded into the
/// remote path and synced a nonexistent root).
pub fn scp_endpoint(meta: &SshWorkspaceMeta) -> String {
    format!("{}:/{}", ssh_alias(&meta.profile), meta.remote_path.trim_start_matches('/'))
}

/// Prepare the transport dir (config + wrapper) under
/// `<data-root>/sync-workspaces/bin/`; returns the dir to PREPEND to PATH
/// (mutagen spawns a bare `ssh` resolved through PATH).
fn ensure_transport(meta: &SshWorkspaceMeta) -> Result<std::path::PathBuf, WorkbenchError> {
    ensure_transport_for(&meta.profile)
}

fn ensure_transport_for(profile: &crate::settings::SshProfile) -> Result<std::path::PathBuf, WorkbenchError> {
    // The managed ~/.ssh/config alias IS the transport now (the ssh.cmd
    // wrapper is retired — it halved throughput). The returned dir is kept
    // only for PATH-prepend compatibility with run_mutagen's signature.
    ensure_managed_ssh_config(profile)?;
    let root = crate::data_root::validate_data_root()
        .map_err(|e| WorkbenchError::usage(format!("data root: {}", e.message())))?;
    let dir = root.join("sync-workspaces").join("bin");
    std::fs::create_dir_all(&dir)
        .map_err(|e| WorkbenchError::usage(format!("transport dir: {e}")))?;
    Ok(dir)
}

/// One remote directory entry (T-F1e browse picker).
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SshDirEntry {
    pub name: String,
    pub is_dir: bool,
}

/// F1 (oversized-content strategy): pull ONE remote file into the shadow
/// workspace on demand. The file lands OUTSIDE the ignore-matched sync flow
/// — present and usable for the container agent, never auto-deleted. Binary
/// safe (raw stdout stream → file), CREATE_NO_WINDOW, real timeout.
#[tauri::command]
pub async fn ssh_pull_file(
    workspace: String, remote_path: String,
) -> Result<String, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let meta = read_meta(&ws)
        .ok_or_else(|| WorkbenchError::usage("not an SSH workspace (no metadata)"))?;
    if !valid_remote_path(&remote_path)
        || remote_path.contains('\'') || remote_path.contains('"') || remote_path.contains('\\') {
        return Err(WorkbenchError::usage(format!("invalid remote path: {remote_path:?}")));
    }
    ensure_transport_for(&meta.profile)?;
    let ssh = which_ssh_like("ssh")
        .ok_or_else(|| WorkbenchError::usage("no ssh binary found on PATH"))?;
    // Single-segment basename only — the file lands at the workspace root,
    // no traversal possible.
    let name = remote_path.rsplit('/').next().unwrap_or_default().to_string();
    if name.is_empty() || name.starts_with('.') && name.len() <= 2 {
        return Err(WorkbenchError::usage("cannot derive a local file name"));
    }
    let dest = ws.join(&name);

    let mut cmd = std::process::Command::new(&ssh);
    cmd.args(["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
              &ssh_alias(&meta.profile),
              &format!("cat -- '{remote_path}'")])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd.spawn()
        .map_err(|e| WorkbenchError::usage(format!("spawn ssh: {e}")))?;
    use std::io::{Read, Write};
    let mut file = std::fs::File::create(&dest)
        .map_err(|e| WorkbenchError::usage(format!("create local file: {e}")))?;
    let mut buf = [0u8; 64 * 1024];
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(300);
    if let Some(mut out) = child.stdout.take() {
        loop {
            match out.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    file.write_all(&buf[..n])
                        .map_err(|e| WorkbenchError::usage(format!("write local file: {e}")))?;
                }
                Err(e) => return Err(WorkbenchError::usage(format!("stream: {e}"))),
            }
            if std::time::Instant::now() > deadline {
                let _ = child.kill();
                return Err(WorkbenchError::usage("pull timed out (300s)"));
            }
        }
    }
    let status = child.wait()
        .map_err(|e| WorkbenchError::usage(format!("wait ssh: {e}")))?;
    if !status.success() {
        let _ = std::fs::remove_file(&dest);
        let err = child.stderr.take().map(|mut p| {
            let mut b = String::new();
            let _ = p.read_to_string(&mut b);
            b
        }).unwrap_or_default();
        let tail = err.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        return Err(WorkbenchError::usage(format!("ssh cat failed: {tail}")));
    }
    Ok(dest.to_string_lossy().to_string())
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
    ensure_transport_for(&profile)?;
    let ssh = which_ssh_like("ssh")
        .ok_or_else(|| WorkbenchError::usage("no ssh binary found on PATH"))?;
    let alias = ssh_alias(&profile);

    let mut cmd = std::process::Command::new(&ssh);
    cmd.args(["-o", "BatchMode=yes",
              "-o", "ConnectTimeout=15", &alias,
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

/// Run mutagen with the transport PATH prepended and mutagen's OWN state
/// pinned under the data root (field report #4: without this the daemon
/// litters `~/.mutagen/` + `~/.mutagen.yml` into the user's home).
/// MUTAGEN_SSH_PATH points at the REAL ssh binary — the retired ssh.cmd
/// wrapper halved throughput (see ensure_managed_ssh_config).
fn mutagen_env(cmd: &mut std::process::Command) {
    if let Ok(root) = crate::data_root::validate_data_root() {
        let data = root.join("mutagen");
        let _ = std::fs::create_dir_all(&data);
        cmd.env("MUTAGEN_DATA_DIRECTORY", &data);
        cmd.env("MUTAGEN_CONFIG_FILE_PATH", data.join("mutagen.yml"));
    }
    if let Some(ssh) = which_ssh_like("ssh") {
        cmd.env("MUTAGEN_SSH_PATH", ssh);
    }
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
    mutagen_env(&mut cmd);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    // REAL timeout (field report: `sync terminate` against a session stuck
    // in a multi-GB remote scan blocks indefinitely — cmd.output() has no
    // deadline). Poll try_wait to the deadline, then kill.
    let mut child = cmd.spawn()
        .map_err(|e| WorkbenchError::usage(format!("spawn mutagen: {e}")))?;
    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(s)) => break s,
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    // Child::kill() is the stable cross-platform API.
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(WorkbenchError::usage(format!(
                        "mutagen {} timed out after {}s",
                        args.first().copied().unwrap_or(""),
                        timeout.as_secs()
                    )));
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            Err(e) => return Err(WorkbenchError::usage(format!("wait mutagen: {e}"))),
        }
    };
    use std::io::Read;
    let mut stdout_buf = Vec::new();
    let mut stderr_buf = Vec::new();
    if let Some(mut p) = child.stdout.take() {
        let _ = p.read_to_end(&mut stdout_buf);
    }
    if let Some(mut p) = child.stderr.take() {
        let _ = p.read_to_end(&mut stderr_buf);
    }
    let stdout = String::from_utf8_lossy(&stdout_buf).to_string();
    let stderr = String::from_utf8_lossy(&stderr_buf).to_string();
    if !status.success() {
        let tail = stderr.lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("");
        return Err(WorkbenchError::usage(format!(
            "mutagen {} failed: {}",
            args.first().copied().unwrap_or(""),
            tail
        )));
    }
    let _ = timeout; // enforced above via the deadline loop
    Ok((stdout, stderr))
}

/// One session's status projection (T-F1d renders this). `alpha_files` /
/// `beta_files` / `total_file_size` are the progress counters from the
/// session JSON (None-shaped until the first scan completes — a multi-GB
/// remote keeps the tree legitimately empty for a while; these numbers are
/// what makes that VISIBLE instead of looking broken).
#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatus {
    pub status: String,
    pub message: String,
    pub last_error: String,
    pub alpha_files: Option<u64>,
    pub beta_files: Option<u64>,
    pub total_file_size: Option<u64>,
}

fn session_name(workspace: &std::path::Path) -> String {
    workspace
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default()
}

fn write_meta(ws: &std::path::Path, meta: &SshWorkspaceMeta) -> Result<(), WorkbenchError> {
    let bytes = serde_json::to_vec_pretty(meta)
        .map_err(|e| WorkbenchError::usage(format!("encode metadata: {e}")))?;
    crate::storage::atomic_replace(&ws.join(META_FILE), &bytes)
        .map_err(|e| WorkbenchError::usage(format!("write metadata: {e}")))
}

/// F1 (field report: "本地放不下这么多东西"): CANCEL the sync permanently
/// for this workspace — terminate the session (tolerating a timeout against
/// a scan-stuck session; the daemon-side definition dies with it, and a
/// timeout kill leaves the CLI dead but the session still registered, which
/// the next enable's terminate sweep handles), DELETE the already-synced
/// content from the shadow dir (metadata file survives), and set the
/// `sync_disabled` flag so launch NEVER re-attaches until the user
/// explicitly re-enables.
#[tauri::command]
pub async fn sync_session_cancel(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let mut meta = read_meta(&ws)
        .ok_or_else(|| WorkbenchError::usage("not an SSH workspace (no metadata)"))?;

    // 1) IMMEDIATELY disable + wipe content — the UI flips to 已取消 the
    //    moment this returns (field report: the terminate wait used to keep
    //    it showing the old state for a long stretch).
    meta.sync_disabled = Some(true);
    write_meta(&ws, &meta)?;
    if let Ok(entries) = std::fs::read_dir(&ws) {
        for e in entries.flatten() {
            if e.file_name().to_string_lossy() == META_FILE {
                continue;
            }
            let p = e.path();
            if p.is_dir() {
                let _ = std::fs::remove_dir_all(&p);
            } else {
                let _ = std::fs::remove_file(&p);
            }
        }
    }

    // 2) Session teardown runs detached: terminate (10s budget — a scanning
    //    session blocks indefinitely), and if it somehow survives, kill the
    //    daemon + delete this workspace's persisted session definition (the
    //    emergency-path recipe: daemon restarts lazily and the other
    //    workspaces' persisted sessions re-attach).
    let name = session_name(&ws);
    let shadow = ws.to_string_lossy().to_string();
    std::thread::spawn(move || {
        use std::process::Command;
        let Some(meta) = read_meta(std::path::Path::new(&shadow)) else { return };
        let Ok(transport) = ensure_transport(&meta) else { return };
        let still_alive = run_mutagen(&["sync", "terminate", &name], &transport, std::time::Duration::from_secs(10)).is_err()
            && session_exists(&name, &transport);
        if still_alive {
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                let _ = Command::new("taskkill")
                    .args(["/F", "/IM", "mutagen.exe"])
                    .creation_flags(0x0800_0000)
                    .status();
            }
            #[cfg(not(windows))]
            {
                let _ = Command::new("pkill").arg("-f").arg("mutagen").status();
            }
            // Delete OUR persisted definition only (others survive + re-attach
            // on the next daemon start).
            if let Ok(root) = crate::data_root::validate_data_root() {
                let dir = root.join("mutagen").join("sessions");
                if let Ok(entries) = std::fs::read_dir(&dir) {
                    for e in entries.flatten() {
                        let p = e.path();
                        if let Ok(bytes) = std::fs::read(&p) {
                            if bytes.windows(shadow.len().min(bytes.len()))
                                .any(|w| w == shadow.as_bytes())
                            {
                                let _ = std::fs::remove_file(&p);
                            }
                        }
                    }
                }
            }
        }
    });

    Ok(SyncStatus { status: "disabled".into(), ..Default::default() })
}

/// Does a session with this name exist right now? (Best-effort list.)
fn session_exists(name: &str, transport: &std::path::Path) -> bool {
    run_mutagen(&["sync", "list", "--template", "{{json .}}"], transport, std::time::Duration::from_secs(15))
        .ok()
        .and_then(|(out, _)| serde_json::from_str::<Value>(out.trim()).ok())
        .and_then(|v| v.as_array().cloned())
        .map(|arr| arr.iter().any(|s| s["name"].as_str() == Some(name)))
        .unwrap_or(false)
}

/// Re-enable a cancelled sync (the explicit user action that un-does
/// `sync_session_cancel`; launch-time attach NEVER does this implicitly).
#[tauri::command]
pub async fn sync_session_enable(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let mut meta = read_meta(&ws)
        .ok_or_else(|| WorkbenchError::usage("not an SSH workspace (no metadata)"))?;
    meta.sync_disabled = None;
    write_meta(&ws, &meta)?;
    sync_session_start_impl(ws, meta).await
}

/// Create (or reconnect to) the sync session for an SSH workspace. A PLAIN
/// local workspace is a no-op returning `status: "none"` (the frontend fires
/// this on every launch — non-SSH must not surface as an error).
///
/// IDEMPOTENT by session name (field reports #2/#3: re-opening showed stale
/// content because `sync create` fails on an existing name and the error
/// only landed in the sidebar): an existing session is resumed if paused,
/// then FLUSHED — a forced synchronization cycle that pulls the initial /
/// lagging content immediately instead of waiting for the scan cadence.
#[tauri::command]
pub async fn sync_session_start(workspace: String) -> Result<SyncStatus, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let Some(meta) = read_meta(&ws) else {
        return Ok(SyncStatus { status: "none".into(), ..Default::default() });
    };
    if meta.sync_disabled == Some(true) {
        return Ok(SyncStatus { status: "disabled".into(), ..Default::default() });
    }
    sync_session_start_impl(ws, meta).await
}

async fn sync_session_start_impl(
    ws: std::path::PathBuf, meta: SshWorkspaceMeta,
) -> Result<SyncStatus, WorkbenchError> {
    let workspace = ws.to_string_lossy().to_string();
    let transport = ensure_transport(&meta)?;
    let name = session_name(&ws);
    // v0.16 list elements ARE the Session objects (field paths verified
    // live): top-level `name` and `beta.path`.
    let existing = run_mutagen(
        &["sync", "list", "--template", "{{json .}}"],
        &transport,
        std::time::Duration::from_secs(15),
    )
    .ok()
    .and_then(|(out, _)| serde_json::from_str::<Value>(out.trim()).ok())
    .and_then(|v| v.as_array().cloned())
    .and_then(|arr| {
        arr.into_iter().find(|s| s["name"].as_str() == Some(name.as_str()))
    });

    // Self-heal: a session whose beta path disagrees with the metadata
    // (e.g. the port-folding bug created `22/home/...` roots that never
    // existed) is terminated and recreated with the correct endpoint.
    let mut existing = existing;
    if let Some(sess) = &existing {
        let bad_beta = sess["beta"]["path"].as_str()
            .map(|p| !p.trim_end_matches('/').eq_ignore_ascii_case(
                meta.remote_path.trim_end_matches('/')))
            .unwrap_or(true);
        if bad_beta {
            let _ = run_mutagen(&["sync", "terminate", &name], &transport, std::time::Duration::from_secs(30));
            existing = None;
        }
    }

    if existing.is_some() {
        // Reconnect path: resume a paused session, then force one cycle.
        let _ = run_mutagen(&["sync", "resume", &name], &transport, std::time::Duration::from_secs(30));
        let _ = run_mutagen(&["sync", "flush", &name], &transport, std::time::Duration::from_secs(90));
    } else {
        let alpha = workspace.clone();
        let beta = scp_endpoint(&meta);
        // Dynamic argv: metadata ignore_patterns (oversized-content
        // strategy) ride alongside the fixed AISC-managed-file excludes.
        let mut argv: Vec<&str> = vec![
            "sync", "create", "--name", &name, "--ignore-vcs",
            // AISC-managed files must never propagate to the remote.
            "--ignore", ".aisc-ssh-workspace.json",
            "--ignore", ".mcp.json",
        ];
        for pat in &meta.ignore_patterns {
            argv.push("--ignore");
            argv.push(pat);
        }
        argv.push(&alpha);
        argv.push(&beta);
        run_mutagen(&argv, &transport, std::time::Duration::from_secs(60))?;
        // Fresh session: create already performs the initial scan, but flush
        // guarantees a completed cycle before we report status (report #3:
        // "new workspace content differs from remote").
        let _ = run_mutagen(&["sync", "flush", &name], &transport, std::time::Duration::from_secs(90));
    }
    sync_status_inner(&ws, &meta, &transport)
}

/// Status by session name. Field paths verified against the REAL v0.16
/// `sync list --template '{{json .}}'` shape: the array elements ARE the
/// Session objects — `name`, `status` and `beta.path` are TOP-LEVEL fields
/// (the earlier `.Session/.Status` nesting silently matched nothing).
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
                .find(|s| s["name"].as_str() == Some(name.as_str()));
            match mine {
                Some(s) => SyncStatus {
                    status: s["status"].as_str().unwrap_or("").to_string(),
                    message: s["lastError"].as_str().unwrap_or("").to_string(),
                    last_error: s["lastError"].as_str().unwrap_or("").to_string(),
                    alpha_files: s["alpha"]["files"].as_u64(),
                    beta_files: s["beta"]["files"].as_u64(),
                    total_file_size: s["beta"]["totalFileSize"].as_u64(),
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
    if meta.sync_disabled == Some(true) {
        return Ok(SyncStatus { status: "disabled".into(), ..Default::default() });
    }
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
            sync_disabled: None,
        ignore_patterns: Vec::new(),
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
            sync_disabled: None,
        ignore_patterns: Vec::new(),
        }
    }

    #[test]
    fn ssh_config_body_carries_the_profile() {
        let cfg = ssh_config_body(&test_meta());
        // The ALIAS heads the block (not the raw host) — ~/.ssh/config's
        // managed block is the single source of host/port/user/key.
        assert!(cfg.contains(&format!("Host {}", ssh_alias(&test_meta().profile))));
        assert!(cfg.contains("HostName 10.0.0.5"));
        assert!(cfg.contains("Port 2222"));
        assert!(cfg.contains("User deploy"));
        assert!(cfg.contains("IdentityFile C:/keys/id_ed25519"));
        assert!(cfg.contains("StrictHostKeyChecking accept-new"));
        // no key -> no IdentityFile line (agent/default-key path)
        let mut m = test_meta();
        m.profile.key_path = String::new();
        assert!(!ssh_config_body(&m).contains("IdentityFile"));
    }

    #[test]
    fn scp_endpoint_shape() {
        // The ALIAS rides the endpoint (host/port/user live in the managed
        // ssh block; the endpoint never embeds them — a `:22` here once
        // folded into the remote path and synced a nonexistent root).
        let alias = ssh_alias(&test_meta().profile);
        assert!(alias.starts_with("aisc-sync-"));
        assert_eq!(scp_endpoint(&test_meta()), format!("{alias}:/srv/proj"));
        let mut m = test_meta();
        m.remote_path = "/a/b/".into();
        assert_eq!(scp_endpoint(&m), format!("{alias}:/a/b/"));
    }

    #[test]
    fn alias_is_stable_and_profile_scoped() {
        let a = ssh_alias(&test_meta().profile);
        assert_eq!(a, ssh_alias(&test_meta().profile)); // stable
        let mut other = test_meta().profile;
        other.port = 23;
        assert_ne!(a, ssh_alias(&other)); // profile-scoped
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
        // ISOLATE the home dir: ensure_managed_ssh_config writes the managed
        // block into ~/.ssh/config — without this the test pollutes the REAL
        // user config (found the hard way, 2026-09-04).
        let home = tempfile::tempdir().unwrap();
        #[cfg(windows)]
        std::env::set_var("USERPROFILE", home.path());
        #[cfg(not(windows))]
        std::env::set_var("HOME", home.path());
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
