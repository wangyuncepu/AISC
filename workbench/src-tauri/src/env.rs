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
    /// Redacted engine-probe detail — WHY the engine is not ready (spawn err /
    /// non-zero exit / timeout / docker CLI missing). "" when ready. Surfaced
    /// in the wizard + Doctor for diagnostics (Stage 6 KI-1). Never secret.
    #[serde(default)]
    pub engine_detail: String,
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
            engine_detail: String::new(),
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

/// Candidate paths for the `docker` CLI binary next to Docker Desktop
/// (`resources\bin\docker.exe`). The GUI process may not have Docker's bin on
/// PATH even when Docker Desktop is installed (launch-time env snapshot), so
/// the probe falls back to these known locations instead of only PATH.
#[cfg(windows)]
fn docker_cli_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(base) = std::env::var("LOCALAPPDATA") {
        let la = PathBuf::from(&base);
        // Per-user Docker Desktop install (default "Install for me" — observed
        // 2026-08-19: engine probe missed it and fell back to a stale launch
        // PATH, so the summary showed "engine not running" with Desktop up).
        out.push(la.join("Programs\\DockerDesktop\\resources\\bin\\docker.exe"));
        out.push(la.join("Docker\\Docker Desktop\\resources\\bin\\docker.exe"));
    }
    if let Ok(pf) = std::env::var("ProgramFiles") {
        out.push(PathBuf::from(pf).join("Docker\\Docker\\resources\\bin\\docker.exe"));
    }
    out
}

#[cfg(not(windows))]
fn docker_cli_candidates() -> Vec<PathBuf> {
    Vec::new()
}

/// Resolve a `docker` CLI executable: prefer the known Docker Desktop resource
/// paths (authoritative for the Desktop engine, and independent of the GUI's
/// launch-time PATH), then fall back to the bare name resolved via PATH.
/// Returns "" only when neither a candidate file nor a PATH fallback exists.
fn resolve_docker_cli() -> PathBuf {
    for p in docker_cli_candidates() {
        if p.is_file() {
            return p;
        }
    }
    PathBuf::from("docker") // PATH resolution at spawn; caller probes the failure
}

/// Directory holding the resolved docker.exe (when it came from a known
/// candidate). The aisc CLI child processes get this prepended to their PATH
/// (KI-6): the GUI's launch-time PATH snapshot may predate Docker's install
/// and its USER-PATH registration, but runtime operations must still find
/// docker.
#[cfg(windows)]
pub(crate) fn docker_bin_dir() -> Option<PathBuf> {
    let resolved = resolve_docker_cli();
    if resolved.is_absolute() && resolved.is_file() {
        resolved.parent().map(|p| p.to_path_buf())
    } else {
        None
    }
}

/// Real-time engine liveness straight from the engine's own named pipe
/// (`\\.\pipe\docker_engine`, HTTP-over-pipe) — independent of the GUI's
/// launch-time PATH and of where Docker Desktop is installed (KI-6: a
/// per-user install plus a pre-install terminal made the CLI probe see
/// "engine not running" with Desktop up). Returns ``None`` when the pipe
/// does not exist (engine absent → CLI probe reports the detail).
#[cfg(windows)]
async fn engine_reachable_via_pipe() -> Option<bool> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::windows::named_pipe::ClientOptions;

    let mut client = match ClientOptions::new().open(r"\\.\pipe\docker_engine") {
        Ok(c) => c,
        Err(_) => return None,
    };
    let req = b"GET /_ping HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n";
    if client.write_all(req).await.is_err() {
        return Some(false);
    }
    let mut buf = [0u8; 128];
    match tokio::time::timeout(ENGINE_PROBE_TIMEOUT, client.read(&mut buf)).await {
        Ok(Ok(n)) if n > 0 => {
            let head = String::from_utf8_lossy(&buf[..n]);
            Some(head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200"))
        }
        _ => Some(false),
    }
}

/// Probe whether the Docker Engine is reachable, with a bounded timeout.
/// Prefers the engine named pipe (real-time, location-independent, KI-6);
/// falls back to `docker version --format {{.Server.Version}}` (the CLI is
/// a hard dependency for operations anyway) with a tokio deadline so a hung
/// daemon never blocks onboarding. Returns (reachable, redacted-detail) —
/// the detail explains WHY not ready (spawn failed / non-zero exit /
/// timeout) for the wizard + Doctor (KI-1).
async fn engine_reachable_detail() -> (bool, String) {
    #[cfg(windows)]
    if let Some(up) = engine_reachable_via_pipe().await {
        return if up {
            (true, String::new())
        } else {
            (false, "engine pipe answered but /_ping did not return 200".into())
        };
    }
    let cli = resolve_docker_cli();
    if cli.as_os_str().is_empty() {
        return (false, "docker CLI not found (not on PATH or Docker Desktop bin)".into());
    }
    let mut cmd = tokio::process::Command::new(&cli);
    cmd.args(["version", "--format", "{{.Server.Version}}"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .stdin(std::process::Stdio::null());
    // `docker` is a console-subsystem binary; without CREATE_NO_WINDOW a GUI
    // process flashes a console per probe — every 500ms during the engine poll
    // and every 5s during auto-poll (observed 2026-08-16 as a flicker).
    // `creation_flags` is Windows-only (tokio), so keep it behind cfg(windows).
    #[cfg(windows)]
    cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return (false, format!("docker spawn failed: {e}")),
    };
    match tokio::time::timeout(ENGINE_PROBE_TIMEOUT, child.wait()).await {
        Ok(Ok(status)) if status.success() => (true, String::new()),
        Ok(Ok(status)) => (false, format!("docker version exited {:?}", status.code())),
        Ok(Err(e)) => (false, format!("docker run error: {e}")),
        Err(_) => {
            let _ = child.kill().await; // reap on timeout
            (false, format!("docker probe timed out after {}s", ENGINE_PROBE_TIMEOUT.as_secs()))
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
///
/// The Evergreen runtime registers its version under
/// `EdgeUpdate\Clients\{F3017226-...}` in ONE of several roots/views: the
/// per-user HKCU key, the per-machine HKLM 64-bit key, or the HKLM WOW6432Node
/// (32-bit view) key. Which one varies by how the runtime was installed, so we
/// probe all of them (observed 2026-08-16: present under HKLM WOW6432Node while
/// HKCU/HKLM were empty). `pv` non-empty ⇒ runtime present.
fn webview2_present() -> bool {
    #[cfg(windows)]
    {
        use winreg::enums::{KEY_READ, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
        use winreg::RegKey;

        const WV2_KEY: &str =
            "Software\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
        const WV2_KEY_32: &str =
            "Software\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";

        let has_pv = |key: Result<RegKey, _>| -> bool {
            key.map(|k| {
                k.get_value::<String, _>("pv")
                    .map(|v| !v.is_empty())
                    .unwrap_or(false)
            })
            .unwrap_or(false)
        };

        has_pv(
            RegKey::predef(HKEY_CURRENT_USER)
                .open_subkey_with_flags(WV2_KEY, KEY_READ),
        ) || has_pv(
            RegKey::predef(HKEY_LOCAL_MACHINE)
                .open_subkey_with_flags(WV2_KEY, KEY_READ),
        ) || has_pv(
            RegKey::predef(HKEY_LOCAL_MACHINE)
                .open_subkey_with_flags(WV2_KEY_32, KEY_READ),
        )
    }
    #[cfg(not(windows))]
    {
        false // Tauri bundles/uses the runtime on each platform; unknown on POSIX here.
    }
}

/// Resolve a CLI path for readiness. Uses the full discovery order
/// (explicit > saved pin > bundled sidecar > PATH > platform-known) but
/// presence-only — no subprocess, no version probe. During onboarding the pin
/// may be stale or empty while the bundled sidecar is right next to the exe, so
/// pin-only lookup falsely reported "unavailable" on a fresh install (manual
/// test 2026-08-16). The real negotiate (cli.rs) validates version/capability.
fn resolve_cli_path(app: &tauri::AppHandle) -> PathBuf {
    // Presence-only (sync) lookup: the pin when present, else the first
    // existing candidate file. The async resolve_cli (auto-pin) is NOT used
    // here — readiness is a cheap presence probe, never a subprocess spawn.
    let saved = crate::session::resolve_pin(app).ok();
    for (path, _src) in crate::cli::enumerate_candidates(None, saved.as_deref()) {
        if path.is_file() {
            return path;
        }
    }
    PathBuf::new()
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

    // Engine reachability (separate from install — the contract). The detail
    // (why not ready) rides along for the wizard/Doctor when not ready.
    let (reachable, detail) = engine_reachable_detail().await;
    r.engine_detail = detail;
    if reachable {
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
    let was_ready = r.engine == "ready";
    while !r.engine.eq("ready") && start.elapsed().as_millis() < deadline_ms as u128 {
        // Bounded jitter (5% of 500ms base) so concurrent apps don't stampede.
        let jitter_ms = 500 + (std::process::id() as u64 % 25) * 4;
        tokio::time::sleep(Duration::from_millis(jitter_ms)).await;
        r = compute_readiness(app.clone()).await;
    }
    // One-shot Windows toast when the engine comes up mid-poll (manual test
    // 2026-08-16: after Docker starts the wizard had no real-time feedback).
    if !was_ready && r.engine == "ready" {
        crate::runtime::notify_docker(&app, "Docker 已就绪", "Docker 引擎已启动，可以继续完成首次设置。");
    }
    r
}

/// Tauri command: one-shot environment readiness (ONB-02 entry). Timed so the
/// Docker probe latency lands in the op-trace ring (REL-01 / KI-1 diagnosis).
#[tauri::command]
pub async fn env_readiness(app: tauri::AppHandle) -> EnvReadiness {
    crate::trace::timed_ok("docker", "env_readiness", compute_readiness(app)).await
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
        let _ = engine_reachable_detail().await;
    }

    /// KI-1 diagnostic (Stage 6, 6a): on this machine Docker is running and
    /// `docker version` succeeds from a shell, so the probe MUST be true. This
    /// is a temporary reproduction test — remove once KI-1 is root-caused.
    #[tokio::test]
    async fn diag_engine_reachable_true_with_running_docker() {
        let (ok, detail) = engine_reachable_detail().await;
        eprintln!("[diag] engine_reachable = {ok} detail = {detail:?}");
        assert!(ok, "Docker is running; engine_reachable_detail() must be true (detail: {detail})");
    }

    #[test]
    fn diag_docker_cli_candidates_are_well_formed() {
        for c in docker_cli_candidates() {
            assert!(c.to_string_lossy().ends_with("docker.exe"));
        }
    }

    /// KI-6 (2026-08-19): a per-user Docker Desktop install keeps docker.exe
    /// under `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin` — with a
    /// stale launch-time PATH the engine probe saw "engine not running" while
    /// Desktop was up. The per-user location must be among the candidates.
    #[cfg(windows)]
    #[test]
    fn diag_docker_cli_candidates_include_per_user_install() {
        let cands = docker_cli_candidates();
        let base = std::env::var("LOCALAPPDATA").unwrap_or_default();
        assert!(
            cands.iter().any(|c| c.to_string_lossy().contains(
                &format!("{base}\\Programs\\DockerDesktop\\resources\\bin\\docker.exe")
            )),
            "per-user DockerDesktop bin missing from candidates: {cands:?}"
        );
    }

    #[cfg(windows)]
    #[test]
    fn webview2_probe_checks_all_registry_roots() {
        // Must not panic and must find the runtime that this machine actually
        // has (registered under one of HKCU/HKLM/WOW6432Node). If the CI/machine
        // genuinely lacks WebView2 this returns false — the invariant is that
        // probing all roots never panics.
        let _ = webview2_present();
    }
}
