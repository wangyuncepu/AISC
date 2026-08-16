//! Environment readiness for first-run onboarding (Stage 5, A-ONB02).
//!
//! Returns the structured readiness of CLI / Docker Desktop / Docker Engine /
//! WebView2. The core contract (02-domain-contract.md): **Docker installed ≠
//! Engine ready**. This module separates "is Docker Desktop present" from "is
//! the Engine reachable", and offers a deadline-bound Engine poll (with jitter)
//! to use after the installer/user launches Docker Desktop.
//!
//! Readiness states (internal enums only ever map to user copy in the UI):
//!   cli:          unknown | checking | ready | unavailable
//!   docker:       unknown | not_installed | installing | installed | starting | ready | blocked
//!   engine:       unknown | unavailable | starting | ready | permission_denied
//!   webview2:     unknown | ready | missing
//! None of these carry secrets.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use serde::Serialize;

const ENGINE_PROBE_TIMEOUT: Duration = Duration::from_secs(4);

/// Structured environment readiness (frontend consumes this for ONB-02).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EnvReadiness {
    pub cli: String,
    pub docker: String,
    pub engine: String,
    pub webview2: String,
    /// Path of the Docker Desktop executable when found ("" if none).
    pub docker_desktop_path: String,
    /// CLI path resolved for readiness ("" if unavailable).
    pub cli_path: String,
}

impl EnvReadiness {
    fn unknown() -> Self {
        Self {
            cli: "unknown".into(),
            docker: "unknown".into(),
            engine: "unknown".into(),
            webview2: "unknown".into(),
            docker_desktop_path: String::new(),
            cli_path: String::new(),
        }
    }

    /// True when every core piece the onboarding needs is ready.
    pub fn ready(&self) -> bool {
        self.cli == "ready" && self.engine == "ready"
    }
}

/// Candidate paths for the Docker Desktop executable. Single source lives in
/// `runtime::docker_desktop_candidates` (shared with `start_docker`).
pub(crate) fn docker_desktop_candidates() -> Vec<PathBuf> {
    #[cfg(windows)]
    {
        crate::runtime::docker_desktop_candidates()
    }
    #[cfg(not(windows))]
    {
        Vec::new()
    }
}

/// Probe whether the Docker Engine is reachable, with a bounded timeout.
/// Uses `docker version --format {{.Server.Version}}` (the CLI is a hard
/// dependency) with a tokio deadline so a hung daemon never blocks onboarding.
async fn engine_reachable() -> bool {
    let mut child = match tokio::process::Command::new("docker")
        .args(["version", "--format", "{{.Server.Version}}"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .stdin(std::process::Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return false, // docker CLI not on PATH
    };
    match tokio::time::timeout(ENGINE_PROBE_TIMEOUT, child.wait()).await {
        Ok(Ok(status)) => status.success(),
        _ => {
            let _ = child.kill().await; // reap on timeout
            false
        }
    }
}

/// Check Docker Desktop presence (installed ≠ engine ready).
fn docker_desktop_installed() -> (bool, String) {
    for exe in docker_desktop_candidates() {
        if exe.exists() {
            return (true, exe.to_string_lossy().into_owned());
        }
    }
    (false, String::new())
}

/// Check whether WebView2 runtime is present (Windows-only, best-effort).
fn webview2_present() -> bool {
    #[cfg(windows)]
    {
        use winreg::enums::{HKEY_CURRENT_USER, KEY_READ};
        use winreg::RegKey;
        // Evergreen WebView2 runtime registers under this key.
        let key = RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey_with_flags(
                "Software\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                KEY_READ,
            )
            .ok();
        key.is_some_and(|k| {
            k.get_value::<String, _>("pv").map(|v| !v.is_empty()).unwrap_or(false)
        })
    }
    #[cfg(not(windows))]
    {
        false // Tauri bundles/uses the runtime on each platform; unknown on POSIX here.
    }
}

/// Resolve the pinned CLI path (best-effort; errors → empty).
fn resolve_cli_path(app: &tauri::AppHandle) -> PathBuf {
    crate::session::resolve_pin(app).unwrap_or_default()
}

/// Compute a fresh environment readiness snapshot. Bounded: never blocks longer
/// than the engine probe timeout. This is the UI's poll target (ONB-02).
pub async fn compute_readiness(app: tauri::AppHandle) -> EnvReadiness {
    let mut r = EnvReadiness::unknown();

    // CLI
    let cli_path = resolve_cli_path(&app);
    if !cli_path.as_os_str().is_empty() && cli_path.exists() {
        r.cli = "ready".into();
        r.cli_path = cli_path.to_string_lossy().into_owned();
    } else {
        r.cli = "unavailable".into();
    }

    // Docker Desktop presence
    let (installed, exe) = docker_desktop_installed();
    r.docker = if installed { "installed".into() } else { "not_installed".into() };
    r.docker_desktop_path = exe;

    // Engine reachability (separate from install — the contract)
    if engine_reachable().await {
        r.engine = "ready".into();
    } else if installed {
        r.engine = "starting".into(); // Desktop present but daemon not answering yet
    } else {
        r.engine = "unavailable".into();
    }

    // WebView2
    r.webview2 = if webview2_present() { "ready".into() } else { "missing".into() };

    r
}

/// Poll Engine readiness with a deadline + jitter, for the "installed but
/// starting" case (A-ONB02: don't treat a stale snapshot as ready). Returns
/// the final readiness (ready when the daemon answers within `deadline_ms`).
pub async fn poll_engine_ready(app: tauri::AppHandle, deadline_ms: u64) -> EnvReadiness {
    let start = Instant::now();
    let mut r = compute_readiness(app.clone()).await;
    while !r.engine.eq("ready") && start.elapsed().as_millis() < deadline_ms as u128 {
        // Bounded jitter (5% of 500ms base) so concurrent apps don't stampede.
        let jitter_ms = 500 + (std::process::id() as u64 % 25) * 4;
        tokio::time::sleep(Duration::from_millis(jitter_ms)).await;
        r = compute_readiness(app.clone()).await;
    }
    r
}

/// Tauri command: one-shot environment readiness (ONB-02 entry).
#[tauri::command]
pub async fn env_readiness(app: tauri::AppHandle) -> EnvReadiness {
    compute_readiness(app).await
}

/// Tauri command: poll Engine until ready or deadline (used after the user
/// clicks "start Docker" / the installer launched Docker Desktop).
#[tauri::command]
pub async fn env_poll_engine(app: tauri::AppHandle, deadline_ms: u64) -> EnvReadiness {
    poll_engine_ready(app, deadline_ms).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readiness_defaults_are_unknown() {
        let r = EnvReadiness::unknown();
        assert_eq!(r.cli, "unknown");
        assert!(!r.ready());
    }

    #[test]
    fn ready_requires_cli_and_engine() {
        let mut r = EnvReadiness::unknown();
        r.cli = "ready".into();
        r.engine = "ready".into();
        assert!(r.ready());
        r.engine = "starting".into();
        assert!(!r.ready());
    }

    #[test]
    fn docker_desktop_candidates_are_well_formed() {
        let candidates = docker_desktop_candidates();
        // Non-empty on Windows (LOCALAPPDATA or ProgramFiles present); the
        // important invariant is each ends with Docker Desktop.exe.
        for c in &candidates {
            assert!(c.to_string_lossy().ends_with("Docker Desktop.exe"));
        }
    }

    #[tokio::test]
    async fn engine_probe_falls_back_without_panicking() {
        // No assertion on the result (environment-dependent); must not panic.
        let _ = engine_reachable().await;
    }
}
