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
    /// Disk guard (field report: "总容量把磁盘爆掉"): the low-disk guard
    /// auto-paused this session. While set, resume is gated on free space
    /// recovering above the floor; launch keeps the session parked.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub low_disk_paused: Option<bool>,
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
        low_disk_paused: None,
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

/// Bundle-resource dir (set once at app setup — `tauri::Manager::path()
/// resource_dir()`). The mutagen agents tarball rides `bundle.resources`,
/// which on deb/DMG installs lands AWAY from the externalBin binary dir.
pub static MUTAGEN_RESOURCE_DIR: std::sync::OnceLock<std::path::PathBuf> =
    std::sync::OnceLock::new();

/// The mutagen AGENT bundle: every beta dial STREAMS the remote agent from
/// this file, searched ONLY next to the mutagen binary itself. Shipping the
/// bare binary without it kills every SSH endpoint with "unable to locate
/// agent bundle" (field report 2026-09-05: all sessions stuck in
/// connecting-beta — the tauri-staged binary sat alone in target/debug).
const MUTAGEN_AGENTS_FILE: &str = "mutagen-agents.tar.gz";

/// First existing agents-bundle candidate among the lookup chain.
fn find_agents_bundle(bin: &std::path::Path) -> Option<std::path::PathBuf> {
    let bin_dir = bin.parent()?;
    let mut candidates: Vec<std::path::PathBuf> = vec![bin_dir.join(MUTAGEN_AGENTS_FILE)];
    // Workbench exe dir (installed layouts put the resource next to the exe).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            candidates.push(d.join(MUTAGEN_AGENTS_FILE));
        }
    }
    if let Some(res) = MUTAGEN_RESOURCE_DIR.get() {
        candidates.push(res.join(MUTAGEN_AGENTS_FILE));
    }
    // Dev fallback: the repo's staging dir (target/debug → src-tauri/binaries).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            candidates.push(
                d.join("..").join("..").join("binaries").join(MUTAGEN_AGENTS_FILE),
            );
        }
    }
    candidates.into_iter().find(|c| c.is_file())
}

/// Copy the binary + agents bundle into `dir` and return the installed
/// binary path (used when the binary's own dir is read-only or the bundle
/// can't legally sit beside it). Cheap-idempotent: same-length files skip.
fn install_mutagen_pair(
    bin: &std::path::Path,
    agents: &std::path::Path,
    dir: &std::path::Path,
) -> Option<std::path::PathBuf> {
    fn copy_if_changed(src: &std::path::Path, dst: &std::path::Path) -> bool {
        let Ok(meta) = std::fs::metadata(src) else { return false };
        if let Ok(existing) = std::fs::metadata(dst) {
            if existing.len() == meta.len() {
                return true;
            }
        }
        std::fs::copy(src, dst).is_ok()
    }
    std::fs::create_dir_all(dir).ok()?;
    if !copy_if_changed(bin, &dir.join(bin.file_name()?)) {
        return None;
    }
    if !copy_if_changed(agents, &dir.join(MUTAGEN_AGENTS_FILE)) {
        return None;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let installed = dir.join(bin.file_name()?);
        if let Ok(meta) = std::fs::metadata(&installed) {
            let mut perm = meta.permissions();
            perm.set_mode(perm.mode() | 0o755);
            let _ = std::fs::set_permissions(&installed, perm);
        }
    }
    Some(dir.join(bin.file_name()?))
}

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

/// The binary every mutagen invocation actually runs. ALWAYS the data-root
/// managed copy (`<data-root>/mutagen/bin/`), never the staged source:
/// (1) the agents bundle is guaranteed next to it (externalBin staging
///     ships a bare binary — field report 2026-09-05);
/// (2) the daemon runs FROM this binary for its whole life, and Windows
///     locks executing images — a daemon on target/debug/mutagen.exe makes
///     every later `cargo build` die in tauri-build's remove_file with
///     PermissionDenied;
/// (3) /usr/bin-style install dirs are read-only; the data root never is.
/// Falls back to the bare discovered binary only when the install fails.
pub fn ensure_mutagen_ready() -> Option<std::path::PathBuf> {
    let bin = mutagen_binary()?;
    let agents = find_agents_bundle(&bin)?;
    let dir = crate::data_root::validate_data_root().ok()?.join("mutagen").join("bin");
    install_mutagen_pair(&bin, &agents, &dir).or(Some(bin))
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
    let path = home.join(".ssh").join("config");
    ensure_managed_ssh_config_at(&path, profile)
}

/// Path-injected core (the test isolation that env vars could NOT deliver:
/// `dirs::home_dir()` on Windows resolves via SHGetKnownFolderPath and
/// IGNORES USERPROFILE/HOME — the env-var "isolation" in the transport test
/// rewrote the REAL ~/.ssh/config managed block with the test profile on
/// every cargo test run, field report 2026-09-05).
pub fn ensure_managed_ssh_config_at(
    path: &std::path::Path,
    profile: &crate::settings::SshProfile,
) -> Result<(), WorkbenchError> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)
            .map_err(|e| WorkbenchError::usage(format!("create ~/.ssh: {e}")))?;
    }
    let current = std::fs::read_to_string(path).unwrap_or_default();
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
            low_disk_paused: None,
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
        std::fs::write(path, next.as_bytes())
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
    // Sweep retired-wrapper leftovers (ssh.cmd forced -F onto a config that
    // knows no aliases — a daemon resolving ssh through this PATH-prepended
    // dir would deadlock every alias endpoint).
    for legacy in ["ssh.cmd", "ssh.bat", "ssh_config"] {
        let _ = std::fs::remove_file(dir.join(legacy));
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
/// `-F` — this spawn is fully ours, no wrapper needed). Shared by the
/// picker's 远端路径 browse dialog (profile from the form) and the sidebar
/// pull-file browser (profile from the workspace metadata).
#[tauri::command]
pub async fn ssh_browse(
    profile: Value, path: String,
) -> Result<Vec<SshDirEntry>, WorkbenchError> {
    let profile: crate::settings::SshProfile = serde_json::from_value(profile)
        .map_err(|e| WorkbenchError::usage(format!("invalid ssh profile: {e}")))?;
    ssh_browse_impl(&profile, path)
}

/// Browse variant for an OPEN SSH workspace: the profile snapshot comes
/// from the metadata (the sidebar pull-file flow has no live profile form).
#[tauri::command]
pub async fn ssh_browse_workspace(
    workspace: String, path: String,
) -> Result<Vec<SshDirEntry>, WorkbenchError> {
    let ws = std::path::PathBuf::from(&workspace);
    let meta = read_meta(&ws)
        .ok_or_else(|| WorkbenchError::usage("not an SSH workspace (no metadata)"))?;
    ssh_browse_impl(&meta.profile, path)
}

fn ssh_browse_impl(
    profile: &crate::settings::SshProfile, path: String,
) -> Result<Vec<SshDirEntry>, WorkbenchError> {
    let path = if path.trim().is_empty() { "/".to_string() } else { path };
    if !valid_remote_path(&path) && path != "/"
        || path.contains('\'') || path.contains('"') || path.contains('\\') {
        return Err(WorkbenchError::usage(format!("invalid remote path: {path:?}")));
    }
    ensure_transport_for(profile)?;
    let ssh = which_ssh_like("ssh")
        .ok_or_else(|| WorkbenchError::usage("no ssh binary found on PATH"))?;
    let alias = ssh_alias(profile);

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
    let bin = ensure_mutagen_ready()
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
///
/// Disk guard: `free_bytes` is the live free space of the data-root volume
/// (the UI compares it against `total_file_size` — the REAL capacity check
/// the fixed 10 GB advisory could never make); `low_disk` reports the
/// metadata flag saying the guard auto-paused this session.
#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatus {
    pub status: String,
    pub message: String,
    pub last_error: String,
    pub alpha_files: Option<u64>,
    pub beta_files: Option<u64>,
    pub total_file_size: Option<u64>,
    pub free_bytes: Option<u64>,
    pub low_disk: bool,
}

// ===========================================================================
// Disk guard (field report: "小文件太多，总容量把本地磁盘爆掉怎么办").
// The fixed 10 GB advisory can't know the volume size; cancel-sync only acts
// after the user notices. Three layers here:
//   1. status carries free_bytes -> UI warns when remote > free;
//   2. a once-per-process guard thread pauses EVERY live session when the
//      data-root volume drops below the floor (a full system drive takes the
//      whole machine down, not just AISC);
//   3. resume/new-session creation is refused while below the floor.
// Known limit (accepted): the guard lives with the Workbench process — a
// mutagen daemon syncing while NO app instance runs is unguarded; the next
// launch's status immediately shows the capacity warning and the floor gates.
// ===========================================================================

/// Hard floor of free space on the data-root volume. Mirrored in
/// RuntimeSidebar.vue (LOW_DISK_FLOOR) for the resume-button gating.
pub const LOW_DISK_FLOOR_BYTES: u64 = 2 * 1024 * 1024 * 1024;

/// Free bytes on the data-root volume (None when the volume can't be probed
/// — treated as "no opinion", never as zero).
pub fn data_root_free_bytes() -> Option<u64> {
    let root = crate::data_root::validate_data_root().ok()?;
    fs4::free_space(&root).ok()
}

/// Pure guard decision: must sync be auto-paused at this free-space level?
pub fn low_disk_should_pause(free_bytes: Option<u64>) -> bool {
    matches!(free_bytes, Some(f) if f < LOW_DISK_FLOOR_BYTES)
}

static LOW_DISK_GUARD: std::sync::Once = std::sync::Once::new();

/// Start the global low-disk guard (once per process). Spawned lazily by
/// the sync commands — no sessions exist before the first one runs.
fn start_low_disk_guard() {
    LOW_DISK_GUARD.call_once(|| {
        let _ = std::thread::Builder::new()
            .name("aisc-low-disk-guard".into())
            .spawn(|| loop {
                std::thread::sleep(std::time::Duration::from_secs(30));
                if low_disk_should_pause(data_root_free_bytes()) {
                    low_disk_pause_all();
                }
            });
    });
}

/// Current status string of one session by name (best-effort list probe).
fn session_status_str(name: &str, transport: &std::path::Path) -> Option<String> {
    run_mutagen(
        &["sync", "list", "--template", "{{json .}}"],
        transport,
        std::time::Duration::from_secs(15),
    )
    .ok()
    .and_then(|(out, _)| serde_json::from_str::<Value>(out.trim()).ok())
    .and_then(|v| v.as_array().cloned())
    .and_then(|arr| arr.into_iter().find(|s| s["name"].as_str() == Some(name)))
    .and_then(|s| s["status"].as_str().map(str::to_string))
}

/// Pause every live session we own and stamp `low_disk_paused`. Already
/// flagged/disabled workspaces are skipped (no re-pause fight — resume is
/// the user's explicit call, gated on recovered space instead).
fn low_disk_pause_all() {
    let Ok(root) = crate::data_root::validate_data_root() else { return };
    let Ok(entries) = std::fs::read_dir(root.join("sync-workspaces")) else { return };
    for e in entries.flatten() {
        let ws = e.path();
        if !ws.is_dir() {
            continue;
        }
        let Some(mut meta) = read_meta(&ws) else { continue };
        if meta.sync_disabled == Some(true) || meta.low_disk_paused == Some(true) {
            continue;
        }
        let name = session_name(&ws);
        let Ok(transport) = ensure_transport(&meta) else { continue };
        // Pause only a transferring session (pause on paused/halted is
        // noise); the flag is stamped either way so the UI explains the
        // state and resume is gated.
        if let Some(st) = session_status_str(&name, &transport) {
            if !st.starts_with("paused") && !st.starts_with("halted") {
                let _ = run_mutagen(
                    &["sync", "pause", &name],
                    &transport,
                    std::time::Duration::from_secs(10),
                );
            }
        }
        meta.low_disk_paused = Some(true);
        let _ = write_meta(&ws, &meta);
    }
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
    meta.low_disk_paused = None;
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
    ws: std::path::PathBuf,
    mut meta: SshWorkspaceMeta,
) -> Result<SyncStatus, WorkbenchError> {
    start_low_disk_guard();
    let workspace = ws.to_string_lossy().to_string();
    let transport = ensure_transport(&meta)?;
    let name = session_name(&ws);

    // Disk-guard gate at launch. A guard-paused workspace stays parked
    // while space is still below the floor (and the session is FORCED
    // paused in case anything resumed it out from under us); once space
    // recovered, the flag clears and the normal reconnect runs.
    let below_floor = low_disk_should_pause(data_root_free_bytes());
    if meta.low_disk_paused == Some(true) {
        if below_floor {
            if let Some(st) = session_status_str(&name, &transport) {
                if !st.starts_with("paused") && !st.starts_with("halted") {
                    let _ = run_mutagen(
                        &["sync", "pause", &name],
                        &transport,
                        std::time::Duration::from_secs(10),
                    );
                }
            }
            return sync_status_inner(&ws, &meta, &transport);
        }
        meta.low_disk_paused = None;
        write_meta(&ws, &meta)?;
    }

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
        // Fresh session on a below-floor volume: refuse — a full initial
        // sync here would head straight into a full disk.
        if below_floor {
            let free = data_root_free_bytes().unwrap_or(0);
            return Err(WorkbenchError::usage(format!(
                "low disk: {free} bytes free on the data-root volume — sync creation refused \
                 (free up space, or re-create the workspace with exclude rules / a smaller \
                 sub-directory)"
            )));
        }
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
    let low_disk = meta.low_disk_paused == Some(true);
    let free_bytes = data_root_free_bytes();
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
                    free_bytes,
                    low_disk,
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
    start_low_disk_guard();
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
    // Disk guard: a guard-paused session resumes only once space recovered
    // above the floor (the UI mirrors this gate on the button; the server
    // check stands regardless of UI staleness).
    let ws = std::path::PathBuf::from(&workspace);
    if let Some(mut meta) = read_meta(&ws) {
        if meta.low_disk_paused == Some(true) {
            let free = data_root_free_bytes();
            if low_disk_should_pause(free) {
                return Err(WorkbenchError::usage(format!(
                    "low disk: {} bytes free — resume blocked until space is freed \
                     (clean up the volume, or cancel the sync)",
                    free.unwrap_or(0)
                )));
            }
            meta.low_disk_paused = None;
            write_meta(&ws, &meta)?;
        }
    }
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
        low_disk_paused: None,
        };
        std::fs::write(
            dir.path().join(META_FILE),
            serde_json::to_vec(&meta).unwrap(),
        )
        .unwrap();
        let back = read_meta(dir.path()).expect("reads back");
        assert_eq!(back.remote_path, "/srv/proj");
        assert_eq!(back.low_disk_paused, None);

        // the guard flag round-trips too (drives resume gating)
        let mut flagged = back;
        flagged.low_disk_paused = Some(true);
        std::fs::write(
            dir.path().join(META_FILE),
            serde_json::to_vec(&flagged).unwrap(),
        )
        .unwrap();
        assert_eq!(read_meta(dir.path()).and_then(|m| m.low_disk_paused), Some(true));

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
        low_disk_paused: None,
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

    /// Disk guard decision matrix: no opinion (None) never pauses; the floor
    /// itself is healthy; anything below pauses.
    #[test]
    fn low_disk_decision_matrix() {
        assert!(!low_disk_should_pause(None));
        assert!(!low_disk_should_pause(Some(LOW_DISK_FLOOR_BYTES)));
        assert!(low_disk_should_pause(Some(LOW_DISK_FLOOR_BYTES - 1)));
        assert!(low_disk_should_pause(Some(0)));
        // free-space probe is live and positive on a real volume (soft —
        // the data root may be unprobed in odd test envs).
        if let Some(f) = data_root_free_bytes() {
            assert!(f > 0);
            assert_eq!(low_disk_should_pause(Some(f)), f < LOW_DISK_FLOOR_BYTES);
        }
    }

    /// Agents-bundle co-location (field report 2026-09-05): install_mutagen_pair
    /// lands BOTH files in the managed dir, is idempotent, and find_agents_bundle
    /// prefers the sibling.
    #[test]
    fn agents_bundle_install_and_lookup() {
        let src = tempfile::tempdir().unwrap();
        let dst = tempfile::tempdir().unwrap();
        let bin = src.path().join("mutagen.exe");
        let agents = src.path().join(MUTAGEN_AGENTS_FILE);
        std::fs::write(&bin, b"fake-binary").unwrap();
        std::fs::write(&agents, vec![0u8; 4096]).unwrap();

        // lookup: sibling hits first
        assert_eq!(find_agents_bundle(&bin).unwrap(), agents);

        // install: both files land, idempotent second run
        let installed = install_mutagen_pair(&bin, &agents, dst.path()).unwrap();
        assert_eq!(installed, dst.path().join("mutagen.exe"));
        assert!(dst.path().join(MUTAGEN_AGENTS_FILE).is_file());
        assert_eq!(
            install_mutagen_pair(&bin, &agents, dst.path()).unwrap(),
            installed
        );

        // a changed bundle (length differs) is re-copied
        std::fs::write(&agents, vec![0u8; 8192]).unwrap();
        assert!(install_mutagen_pair(&bin, &agents, dst.path()).is_some());
        assert_eq!(
            std::fs::metadata(dst.path().join(MUTAGEN_AGENTS_FILE)).unwrap().len(),
            8192
        );
    }

    /// The wrapper must make mutagen's external ssh NON-INTERACTIVE: with
    /// BatchMode injected, a dead endpoint fails fast with a dial error and
    /// NEVER reaches a host-key/passphrase prompt (the deadlock that
    /// motivated the wrapper). Best-effort: skipped when no ssh/mutagen is
    /// resolvable (CI images without the host tool).
    ///
    /// ISOLATION (the hard way, twice): the managed-block writer must be
    /// driven against a tempdir config path. Env-var home overrides DON'T
    /// work on Windows — dirs::home_dir() resolves via SHGetKnownFolderPath
    /// and ignores USERPROFILE, so an earlier env-based "isolation" rewrote
    /// the REAL ~/.ssh/config on every cargo test run (2026-09-05).
    #[test]
    fn wrapper_makes_transport_non_interactive() {
        if which_ssh_like("ssh").is_none() || ensure_mutagen_ready().is_none() {
            eprintln!("skipping: ssh/mutagen not resolvable");
            return;
        }
        let home = tempfile::tempdir().unwrap();
        let config_path = home.path().join(".ssh").join("config");
        let mut m = test_meta();
        m.profile.host = "127.0.0.1".into();
        m.profile.port = 1; // nothing listens here
        m.remote_path = "/r".into();
        ensure_managed_ssh_config_at(&config_path, &m.profile).expect("managed block written");
        // The transport "dir" is PATH-prepend compatibility only (the
        // wrapper files are retired) — a tempdir stands in, and
        // ensure_transport is deliberately NOT called: it would rewrite the
        // REAL ~/.ssh/config managed block with this test profile.
        let transport = home.path().join("bin");
        std::fs::create_dir_all(&transport).unwrap();
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
