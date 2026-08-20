//! Structured AISC CLI runner: discovery/pinning, argv-only process runner,
//! `aisc.cli/v1` envelope validation, and capability negotiation.
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §四 (capability), §八 (error codes), §九.1 (runner)
//! - 02-startup-flow.md §四.3 (discovery candidate order + selection rules)
//! - 03-lifecycle-contract.md §十 (domain API + Workbench error shape)

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};
use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, BufReader};
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::error::{redact, WorkbenchError};
use crate::settings::Settings;

const PROTOCOL: &str = "aisc.cli/v1";
const MAX_STDOUT: usize = 8 * 1024 * 1024; // 8 MB control-plane cap (05 §九.1)
const MAX_STDERR: usize = 64 * 1024; // 64 KB summary for redacted technical_detail
/// `aisc version` probe budget. KI-3 (2026-08-18): a COLD one-file sidecar
/// (first execution after install/dev-root reset) unpacks to %TEMP% and eats
/// a full real-time AV scan of the exe — that can exceed the old 15s budget,
/// marking every candidate invalid ("CLI not found" in the wizard/picker;
/// re-detect passed because the scan verdict was cached). 45s only bites in
/// the pathological cold case (wizard spinner); warm probes stay instant.
const VERSION_TIMEOUT: Duration = Duration::from_secs(45);

const EXPECTED_RUNTIME: &str = "aisc.runtime/v1";
const EXPECTED_SESSION: &str = "aisc.session/v1";
const EXPECTED_PROVIDER: &str = "aisc.provider-status/v1";
const EXPECTED_BUILD: &str = "aisc.build-events/v1";

// ---------------------------------------------------------------------------
// Envelope (aisc.cli/v1)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct Envelope {
    pub meta: EnvelopeMeta,
    #[serde(default)]
    pub data: Option<Value>,
    #[serde(default)]
    pub errors: Vec<CliError>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EnvelopeMeta {
    pub protocol: String,
    pub command: String,
    pub exit_code: i64,
    #[serde(default)]
    pub timestamp: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub run_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CliError {
    pub code: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub hint: Option<String>,
}

/// Parse stdout bytes into an envelope and validate protocol + exit-code
/// consistency. `expected_exit_code` is the OS process exit code (05 §八:
/// `meta.exit_code` must match the process exit code).
pub fn parse_and_validate(stdout: &[u8], expected_exit_code: Option<i32>) -> Result<Envelope, WorkbenchError> {
    let env: Envelope = serde_json::from_slice(stdout)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("json parse: {e}")))?;
    if env.meta.protocol != PROTOCOL {
        return Err(WorkbenchError::cli_protocol()
            .with_detail(format!("protocol mismatch: {}", env.meta.protocol)));
    }
    if let Some(code) = expected_exit_code {
        if env.meta.exit_code != code as i64 {
            return Err(WorkbenchError::cli_protocol().with_detail(format!(
                "exit_code mismatch: meta={} process={code}",
                env.meta.exit_code
            )));
        }
    }
    Ok(env)
}

// ---------------------------------------------------------------------------
// Build events (aisc.build-events/v1 JSONL, 05 §4.1)
// ---------------------------------------------------------------------------

/// One JSONL line from `aisc build --events`. Forwarded verbatim to the
/// frontend via a Tauri Channel; Workbench only inspects `event_type` and the
/// terminal events' `data.exit_code` / `data.error_code` (05 §4.1.3).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BuildEvent {
    #[serde(default)]
    pub protocol: String,
    #[serde(default)]
    pub command: String,
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub seq: u64,
    #[serde(rename = "type", default)]
    pub event_type: String,
    #[serde(default)]
    pub ts: String,
    #[serde(default)]
    pub data: Value,
}

// ---------------------------------------------------------------------------
// Capabilities
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Default, Serialize)]
pub struct Capabilities {
    #[serde(default)]
    pub runtime: Option<String>,
    #[serde(default)]
    pub session: Option<String>,
    #[serde(rename = "providerStatus", default)]
    pub provider_status: Option<String>,
    #[serde(rename = "buildEvents", default)]
    pub build_events: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default, Serialize)]
pub struct VersionInfo {
    #[serde(default)]
    pub cli_version: Option<String>,
    #[serde(default)]
    pub bundle_version: Option<String>,
    #[serde(default)]
    pub contract_version: Option<String>,
    #[serde(default)]
    pub image_version: Option<String>,
    #[serde(default)]
    pub claude_version: Option<String>,
    #[serde(default)]
    pub python_version: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CapabilityReport {
    pub required_ok: bool,
    pub runtime: bool,
    pub session: bool,
    pub provider_status: bool,
    pub build_events: bool,
    pub missing_required: Vec<String>,
    pub missing_optional: Vec<String>,
    pub version_info: Option<VersionInfo>,
    pub error: Option<WorkbenchError>,
}

/// Classify capabilities into (required_ok, missing_required, missing_optional).
/// Pure unit-testable.
pub fn classify(caps: &Capabilities) -> (bool, Vec<String>, Vec<String>) {
    let runtime_ok = caps.runtime.as_deref() == Some(EXPECTED_RUNTIME);
    let session_ok = caps.session.as_deref() == Some(EXPECTED_SESSION);
    let provider_ok = caps.provider_status.as_deref() == Some(EXPECTED_PROVIDER);
    let build_ok = caps.build_events.as_deref() == Some(EXPECTED_BUILD);

    let mut missing_required = Vec::new();
    if !runtime_ok {
        missing_required.push("runtime".into());
    }
    if !session_ok {
        missing_required.push("session".into());
    }
    let mut missing_optional = Vec::new();
    if !provider_ok {
        missing_optional.push("providerStatus".into());
    }
    if !build_ok {
        missing_optional.push("buildEvents".into());
    }
    (missing_required.is_empty(), missing_required, missing_optional)
}

fn report_from_envelope(env: Envelope) -> CapabilityReport {
    if let Some(err) = env.errors.first() {
        let e = WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone());
        return failed_report(Some(e));
    }
    let data = env.data.unwrap_or(Value::Null);
    let caps: Capabilities = serde_json::from_value(data.get("capabilities").cloned().unwrap_or(Value::Null))
        .unwrap_or_default();
    let vi: VersionInfo = serde_json::from_value(data).unwrap_or_default();
    let (required_ok, missing_required, missing_optional) = classify(&caps);
    let error = if !required_ok {
        Some(WorkbenchError::capability_unsupported().with_detail(format!("missing: {missing_required:?}")))
    } else {
        None
    };
    CapabilityReport {
        required_ok,
        runtime: caps.runtime.as_deref() == Some(EXPECTED_RUNTIME),
        session: caps.session.as_deref() == Some(EXPECTED_SESSION),
        provider_status: caps.provider_status.as_deref() == Some(EXPECTED_PROVIDER),
        build_events: caps.build_events.as_deref() == Some(EXPECTED_BUILD),
        missing_required,
        missing_optional,
        version_info: Some(vi),
        error,
    }
}

fn failed_report(error: Option<WorkbenchError>) -> CapabilityReport {
    CapabilityReport {
        required_ok: false,
        runtime: false,
        session: false,
        provider_status: false,
        build_events: false,
        missing_required: vec!["runtime".into(), "session".into()],
        missing_optional: vec!["providerStatus".into(), "buildEvents".into()],
        version_info: None,
        error,
    }
}

/// Run `aisc version --format json` and classify capabilities. Any transport
/// or protocol failure is returned as a structured `CapabilityReport` (never
/// panics) so the UI can render a blocking page instead of crashing.
pub async fn negotiate(executable: &Path, cancel: CancellationToken) -> CapabilityReport {
    let argv = vec!["version".into(), "--format".into(), "json".into()];
    match run_control(executable, argv, VERSION_TIMEOUT, cancel).await {
        Ok(env) => report_from_envelope(env),
        Err(e) => failed_report(Some(e)),
    }
}

// ---------------------------------------------------------------------------
// Discovery / pinning
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateSource {
    Explicit,
    Saved,
    #[serde(rename = "path")]
    PathEnv,
    Platform,
    /// Bundled CLI shipped with the Workbench (S4.1.a).
    Sidecar,
}

#[derive(Debug, Clone, Serialize)]
pub struct Candidate {
    pub path: String,
    pub source: CandidateSource,
    pub valid: bool,
    pub version_info: Option<VersionInfo>,
    pub capabilities: Option<Capabilities>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DiscoveryReport {
    pub candidates: Vec<Candidate>,
    pub selected: Option<String>,
    pub needs_confirm: bool,
    pub error: Option<WorkbenchError>,
}

/// Enumerate candidate CLI paths in priority order (02 §四.3 + S4.1.a):
/// explicit arg > saved pin > bundled sidecar > process PATH > platform known
/// locations. Dedups by canonical path. Pure (does not validate
/// executability/version).
pub fn enumerate_candidates(explicit: Option<&Path>, saved: Option<&Path>) -> Vec<(PathBuf, CandidateSource)> {
    let mut extra: Vec<(PathBuf, CandidateSource)> = Vec::new();
    if let Some(p) = sidecar_candidate() {
        extra.push((p, CandidateSource::Sidecar));
    }
    if let Some(p) = path_candidate() {
        extra.push((p, CandidateSource::PathEnv));
    }
    for p in platform_candidates() {
        extra.push((p, CandidateSource::Platform));
    }
    enumerate_with(explicit, saved, &extra)
}

/// Bundled CLI sidecar path (S4.1.a). Tauri `bundle.externalBin` places the
/// sidecar next to the main binary under its **base name** (target triple
/// stripped, e.g. `aisc.exe` on Windows — tauri-bundler 2.9.x NSIS layout);
/// dev builds have no sidecar (None).
fn sidecar_candidate() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    sidecar_candidate_in(exe.parent()?)
}

/// Pure lookup for tests: sidecar next to *exe_dir*. Accepts both the
/// target-triple name (older layouts / manually staged resources) and the
/// base name tauri-bundler 2.9.x actually installs.
fn sidecar_candidate_in(exe_dir: &Path) -> Option<PathBuf> {
    let name = format!("aisc-{}", target_triple());
    let base = "aisc";
    let candidates = [
        exe_dir.join(&name),
        exe_dir.join(format!("{name}.exe")),
        exe_dir.join(base),
        exe_dir.join(format!("{base}.exe")),
    ];
    candidates.into_iter().find(|p| p.is_file())
}

/// Target triple of this Workbench build (matches the sidecar name suffix).
fn target_triple() -> &'static str {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    { return "x86_64-unknown-linux-gnu"; }
    #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
    { return "aarch64-unknown-linux-gnu"; }
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    { return "aarch64-apple-darwin"; }
    #[cfg(all(target_os = "macos", target_arch = "x86_64"))]
    { return "x86_64-apple-darwin"; }
    #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
    { return "x86_64-pc-windows-msvc"; }
    #[cfg(all(target_os = "windows", target_arch = "aarch64"))]
    { return "aarch64-pc-windows-msvc"; }
    #[allow(unreachable_code)]
    "unknown-unknown"
}

fn enumerate_with(
    explicit: Option<&Path>,
    saved: Option<&Path>,
    extra: &[(PathBuf, CandidateSource)],
) -> Vec<(PathBuf, CandidateSource)> {
    let mut out: Vec<(PathBuf, CandidateSource)> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut push = |path: PathBuf, src: CandidateSource| {
        let key = dedup_key(&path);
        if seen.insert(key) {
            out.push((path, src));
        }
    };
    if let Some(p) = explicit {
        push(p.to_path_buf(), CandidateSource::Explicit);
    }
    if let Some(p) = saved {
        push(p.to_path_buf(), CandidateSource::Saved);
    }
    for (p, s) in extra {
        push(p.clone(), *s);
    }
    out
}

fn dedup_key(path: &Path) -> String {
    std::fs::canonicalize(path)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| path.to_string_lossy().into_owned())
}

fn path_candidate() -> Option<PathBuf> {
    path_candidate_in(std::env::var("PATH").ok().as_deref())
}

fn path_candidate_in(path_var: Option<&str>) -> Option<PathBuf> {
    let path = path_var?;
    let sep = if cfg!(windows) { ';' } else { ':' };
    let exe = if cfg!(windows) { "aisc.exe" } else { "aisc" };
    for dir in path.split(sep) {
        if dir.is_empty() {
            continue;
        }
        let p = Path::new(dir).join(exe);
        if p.exists() {
            return Some(p);
        }
    }
    None
}

fn platform_candidates() -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();
    if cfg!(target_os = "linux") {
        let xdg = std::env::var("XDG_BIN_HOME").ok().filter(|s| !s.is_empty());
        let base = xdg
            .map(PathBuf::from)
            .or_else(|| dirs::home_dir().map(|h| h.join(".local/bin")));
        if let Some(b) = base {
            out.push(b.join("aisc"));
        }
    } else if cfg!(target_os = "macos") {
        out.push(PathBuf::from("/usr/local/bin/aisc"));
        if let Some(h) = dirs::home_dir() {
            out.push(h.join(".local/bin/aisc"));
        }
    } else if cfg!(target_os = "windows") {
        if let Some(la) = std::env::var("LOCALAPPDATA").ok().filter(|s| !s.is_empty()) {
            let la = PathBuf::from(la);
            out.push(la.join("Programs/AISC/aisc.exe"));
            out.push(la.join("AISC/aisc.exe"));
        }
    }
    out.into_iter().filter(|p| p.exists()).collect()
}

pub fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        match std::fs::metadata(path) {
            Ok(m) => m.is_file() && (m.permissions().mode() & 0o111) != 0,
            Err(_) => false,
        }
    }
    #[cfg(windows)]
    {
        match std::fs::metadata(path) {
            Ok(m) => m.is_file(),
            Err(_) => false,
        }
    }
}

/// Extract a validated `Candidate` from a `version --format json` envelope.
/// Pure (no IO) so discovery result semantics are unit-testable without
/// spawning a real CLI (CLI-A04: source / absolute path / version / caps).
fn candidate_from_envelope(path: String, source: CandidateSource, env: Envelope) -> Candidate {
    if let Some(err) = env.errors.first() {
        return Candidate {
            path,
            source,
            valid: false,
            version_info: None,
            capabilities: None,
            error: Some(err.code.clone()),
        };
    }
    let data = env.data.unwrap_or(Value::Null);
    let caps: Capabilities = serde_json::from_value(data.get("capabilities").cloned().unwrap_or(Value::Null))
        .unwrap_or_default();
    let vi: VersionInfo = serde_json::from_value(data).unwrap_or_default();
    Candidate {
        path,
        source,
        valid: true,
        version_info: Some(vi),
        capabilities: Some(caps),
        error: None,
    }
}

/// Validate a candidate: executable check + `version --format json`. IO.
/// KI-3: a TIMEOUT gets exactly one retry — the timed-out cold spawn has
/// already triggered the AV scan/unpack, so the retry is warm in practice;
/// genuinely broken candidates still fail on the second probe.
pub async fn validate_candidate(path: PathBuf, source: CandidateSource) -> Candidate {
    let path_str = path.to_string_lossy().into_owned();
    if !is_executable(&path) {
        return Candidate {
            path: path_str,
            source,
            valid: false,
            version_info: None,
            capabilities: None,
            error: Some("not executable".into()),
        };
    }
    let argv = vec!["version".into(), "--format".into(), "json".into()];
    let mut attempt = run_control(&path, argv.clone(), VERSION_TIMEOUT, CancellationToken::new()).await;
    if let Err(e) = &attempt {
        if e.code == "WB_ERR_CLI_TIMEOUT" {
            attempt = run_control(&path, argv, VERSION_TIMEOUT, CancellationToken::new()).await;
        }
    }
    match attempt {
        Ok(env) => candidate_from_envelope(path_str, source, env),
        Err(e) => Candidate {
            path: path_str,
            source,
            valid: false,
            version_info: None,
            capabilities: None,
            error: Some(e.code),
        },
    }
}

fn same_path(a: &str, b: &Path) -> bool {
    let pa = Path::new(a);
    let ca = std::fs::canonicalize(pa).ok();
    let cb = std::fs::canonicalize(b).ok();
    match (ca, cb) {
        (Some(x), Some(y)) => x == y,
        _ => pa == b,
    }
}

// ---------------------------------------------------------------------------
// Runner (argv-only, timeout, cancellation, stdout cap)
// ---------------------------------------------------------------------------

/// Run an AISC control command and return its validated envelope.
///
/// - argv-only (no shell) per 05 §九.1.
/// - timeout + cancellation both kill + reap the child (05 §九.1).
/// - stdout capped at `MAX_STDOUT`; overflow -> protocol error.
/// - `meta.exit_code` must equal the process exit code (05 §八).
/// Timed entry point for every CLI operation: records duration + outcome in
/// the bounded op-trace ring (REL-01) then returns the envelope.
pub async fn run_control(
    executable: &Path,
    argv: Vec<String>,
    timeout: Duration,
    cancel: CancellationToken,
) -> Result<Envelope, WorkbenchError> {
    let phase = argv.first().map(|s| s.as_str()).unwrap_or("cli").to_owned();
    // lifecycle-logging P1: one run_id per call — injected into the child
    // (env AISC_RUN_ID), reused by the envelope and the CLI's cli_exit log
    // line, and carried by this app-side op line: one id threads the call
    // across both process boundaries.
    let run_id = uuid::Uuid::new_v4().to_string();
    let started_op = std::time::Instant::now();
    let result = crate::trace::timed(
        "cli",
        &phase,
        run_control_inner(executable, argv, None, timeout, cancel, &run_id),
    )
    .await;
    log_cli_op(&phase, &run_id, started_op, &result);
    result
}

/// `run_control` with a stdin payload (Stage 8e): the cc-switch provider data
/// plane carries its request document (including any API key) through the
/// child's STDIN — argv, disk and logs never see a secret.
pub async fn run_control_input(
    executable: &Path,
    argv: Vec<String>,
    input: String,
    timeout: Duration,
    cancel: CancellationToken,
) -> Result<Envelope, WorkbenchError> {
    let phase = argv.first().map(|s| s.as_str()).unwrap_or("cli").to_owned();
    let run_id = uuid::Uuid::new_v4().to_string();
    let started_op = std::time::Instant::now();
    let result = crate::trace::timed(
        "cli",
        &phase,
        run_control_inner(executable, argv, Some(input), timeout, cancel, &run_id),
    )
    .await;
    log_cli_op(&phase, &run_id, started_op, &result);
    result
}

/// lifecycle-logging P1: the app-side line for one CLI call — best-effort,
/// allowlisted fields only (phase/duration/outcome/error_code; never argv
/// or stdin content).
fn log_cli_op(
    phase: &str,
    run_id: &str,
    started: std::time::Instant,
    result: &Result<Envelope, WorkbenchError>,
) {
    let (level, outcome, error_code) = match result {
        Ok(_) => ("info", "ok", None),
        Err(e) => ("error", "error", Some(e.code.clone())),
    };
    let mut extra = serde_json::json!({
        "phase": phase,
        "outcome": outcome,
        "duration_ms": started.elapsed().as_millis() as u64,
    });
    if let Some(code) = error_code {
        extra["error_code"] = serde_json::json!(code);
    }
    crate::logging::append_event(level, "app", "op", Some(run_id), extra);
}

async fn run_control_inner(
    executable: &Path,
    argv: Vec<String>,
    input: Option<String>,
    timeout: Duration,
    cancel: CancellationToken,
    run_id: &str,
) -> Result<Envelope, WorkbenchError> {
    let mut cmd = Command::new(executable);
    cmd.args(&argv);
    cmd.env("AISC_RUN_ID", run_id);
    // KI-6: the GUI process may carry a launch-time PATH snapshot without
    // Docker's bin (per-user installs register it in the USER PATH only
    // after install). Prepend the resolved docker bin dir so every docker
    // subprocess the aisc CLI spawns keeps resolving.
    #[cfg(windows)]
    if let Some(dir) = crate::env::docker_bin_dir() {
        let path = std::env::var("PATH").unwrap_or_default();
        cmd.env("PATH", format!("{};{}", dir.display(), path));
    }
    if input.is_some() {
        cmd.stdin(Stdio::piped());
    } else {
        cmd.stdin(Stdio::null());
    }
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW: no console flash for piped children
    let mut child = match cmd.spawn()
    {
        Ok(c) => c,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Err(WorkbenchError::cli_not_found().with_detail(executable.display().to_string()));
        }
        Err(e) => {
            return Err(WorkbenchError::cli_protocol().with_detail(format!("spawn failed: {e}")));
        }
    };

    // Write the stdin payload (if any) concurrently with waiting — a blocking
    // write before the wait would deadlock on pipe-buffer limits. Dropping the
    // handle after the write closes the pipe (EOF) for the child.
    let stdin_handle = input.map(|text| {
        let mut stdin = child.stdin.take().expect("piped stdin");
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            let _ = stdin.write_all(text.as_bytes()).await;
            let _ = stdin.shutdown().await;
        })
    });

    let stdout_handle = tokio::spawn(read_capped(child.stdout.take().expect("piped stdout"), MAX_STDOUT));
    let stderr_handle = tokio::spawn(read_capped(child.stderr.take().expect("piped stderr"), MAX_STDERR));

    let exit = tokio::select! {
        r = child.wait() => r,
        _ = tokio::time::sleep(timeout) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            return Err(WorkbenchError::cli_timeout());
        }
        _ = cancel.cancelled() => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            return Err(WorkbenchError::cli_cancelled());
        }
    };

    let (stdout_bytes, stdout_truncated) = stdout_handle.await.unwrap_or((Vec::new(), false));
    let (stderr_bytes, _) = stderr_handle.await.unwrap_or((Vec::new(), false));
    if let Some(handle) = stdin_handle {
        let _ = handle.await;
    }

    let exit = exit.map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("wait failed: {e}")))?;
    let exit_code = exit.code();

    if stdout_truncated {
        return Err(WorkbenchError::cli_protocol().with_detail(format!(
            "stdout exceeded {} bytes",
            MAX_STDOUT
        )));
    }

    let stderr_summary = redact(&String::from_utf8_lossy(&stderr_bytes));
    parse_and_validate(&stdout_bytes, exit_code).map_err(|mut e| {
        let detail = if e.technical_detail.is_some() {
            format!("{} | stderr: {}", e.technical_detail.as_ref().unwrap(), stderr_summary)
        } else {
            format!("stderr: {stderr_summary}")
        };
        e.technical_detail = Some(detail);
        e
    })
}

/// Read up to `cap` bytes; if exceeded, keep draining to EOF (so the child can
/// exit) and return `(capped_buf, true)`.
async fn read_capped<R: AsyncRead + Unpin>(mut r: R, cap: usize) -> (Vec<u8>, bool) {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 8192];
    let mut truncated = false;
    loop {
        match r.read(&mut tmp).await {
            Ok(0) => break,
            Ok(n) => {
                if !truncated {
                    if buf.len() + n <= cap {
                        buf.extend_from_slice(&tmp[..n]);
                    } else {
                        let room = cap - buf.len();
                        buf.extend_from_slice(&tmp[..room]);
                        truncated = true;
                    }
                }
            }
            Err(_) => break,
        }
    }
    (buf, truncated)
}

/// Signal a child to cancel. On Unix send SIGINT so the CLI can emit
/// `build.cancelled` and clean its Docker child group (S0.5 start_new_session +
/// killpg). On Windows there is no SIGINT equivalent for a detached process, so
/// SIGKILL via `start_kill` (no cancelled event -> transport failure, §4.1.4).
fn sigint_or_kill(child: &mut tokio::process::Child) {
    #[cfg(unix)]
    {
        if let Some(pid) = child.id() {
            unsafe {
                libc::kill(pid as i32, libc::SIGINT);
            }
        }
    }
    #[cfg(not(unix))]
    {
        let _ = child.start_kill();
    }
}

/// Run `aisc build --events` (or any JSONL-streaming command): read stdout line
/// by line, parse each as a `BuildEvent`, and forward via `event_tx`. On cancel
/// or timeout, SIGINT the child so it emits `build.cancelled` and reaps its
/// Docker child group, then drain remaining events. Returns Ok on
/// `build.complete`, Err on failed/cancelled/transport (05 §4.1).
pub async fn run_build_stream(
    executable: &Path,
    argv: Vec<String>,
    timeout: Duration,
    cancel: CancellationToken,
    event_tx: mpsc::Sender<BuildEvent>,
) -> Result<(), WorkbenchError> {
    let mut cmd = Command::new(executable);
    cmd.args(&argv);
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW: no console flash for piped children
    let mut child = match cmd.spawn()
    {
        Ok(c) => c,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Err(WorkbenchError::cli_not_found().with_detail(executable.display().to_string()));
        }
        Err(e) => {
            return Err(WorkbenchError::cli_protocol().with_detail(format!("spawn failed: {e}")));
        }
    };

    let stdout = child.stdout.take().expect("piped stdout");
    let stderr_handle = tokio::spawn(read_capped(child.stderr.take().expect("piped stderr"), MAX_STDERR));

    // Reader: parse JSONL lines, forward events, capture the terminal event.
    let tx = event_tx.clone();
    let reader_handle = tokio::spawn(async move {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        let mut terminal: Option<(String, Option<i32>, Option<String>)> = None;
        loop {
            line.clear();
            match reader.read_line(&mut line).await {
                Ok(0) => break,
                Ok(_) => {
                    let trimmed = line.trim_end();
                    if trimmed.is_empty() {
                        continue;
                    }
                    let ev = match serde_json::from_str::<BuildEvent>(trimmed) {
                        Ok(ev) => ev,
                        Err(_) => continue, // skip non-JSON line (stdout must be pure JSONL, §4.1.1)
                    };
                    let is_terminal = matches!(
                        ev.event_type.as_str(),
                        "build.complete" | "build.failed" | "build.cancelled"
                    );
                    if is_terminal {
                        let exit_code = ev.data.get("exit_code").and_then(|v| v.as_i64()).map(|c| c as i32);
                        let error_code = ev.data.get("error_code").and_then(|v| v.as_str()).map(str::to_string);
                        terminal = Some((ev.event_type.clone(), exit_code, error_code));
                    }
                    if tx.send(ev).await.is_err() {
                        break; // consumer gone
                    }
                }
                Err(_) => break,
            }
        }
        terminal
    });

    let exit = tokio::select! {
        r = child.wait() => r,
        _ = tokio::time::sleep(timeout) => {
            sigint_or_kill(&mut child);
            child.wait().await
        }
        _ = cancel.cancelled() => {
            sigint_or_kill(&mut child);
            child.wait().await
        }
    };

    let terminal = reader_handle.await.unwrap_or(None);
    let (stderr_bytes, _) = stderr_handle.await.unwrap_or((Vec::new(), false));
    let stderr_summary = redact(&String::from_utf8_lossy(&stderr_bytes));

    let _exit = exit.map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("wait failed: {e}")))?;

    match terminal {
        Some((t, _code, err_code)) => match t.as_str() {
            "build.complete" => Ok(()),
            "build.cancelled" => Err(WorkbenchError::cli_cancelled().with_detail(stderr_summary)),
            "build.failed" => {
                let mut e = match err_code.as_deref() {
                    Some(c) => WorkbenchError::map_aisc(c),
                    None => WorkbenchError::cli_protocol(),
                };
                if !stderr_summary.is_empty() {
                    e = e.with_detail(stderr_summary);
                }
                Err(e)
            }
            _ => Err(WorkbenchError::cli_protocol().with_detail(format!("unknown terminal: {t}"))),
        },
        None => Err(WorkbenchError::cli_protocol()
            .with_detail(format!("no terminal build event | stderr: {stderr_summary}"))),
    }
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

fn config_dir(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    // Stage 7 (DATA-04): <data-root>/config (legacy app_config_dir is the
    // adoption source / fallback). See session::config_dir.
    let legacy = app.path().app_config_dir().ok();
    Ok(crate::data_root::app_state_dir(legacy.as_deref()))
}

/// Process-arg `--aisc-cli` value (S4.1.a). Managed as Tauri state so
/// negotiate/discover can outrank the saved pin without re-parsing argv.
#[derive(Default, Clone)]
pub struct CliArg(pub std::sync::Arc<std::sync::Mutex<Option<String>>>);

/// Resolve the explicit CLI path: `--aisc-cli` process arg first, else the
/// per-invocation `explicit_path` command argument.
pub fn explicit_cli_path(app: &AppHandle, explicit_path: Option<String>) -> Option<PathBuf> {
    let from_arg = app
        .try_state::<CliArg>()
        .and_then(|s| s.0.lock().ok().and_then(|g| g.clone()))
        .map(PathBuf::from);
    from_arg.or_else(|| explicit_path.map(PathBuf::from))
}

#[tauri::command]
pub async fn cli_discover(
    app: AppHandle,
    explicit_path: Option<String>,
) -> Result<DiscoveryReport, WorkbenchError> {
    let dir = config_dir(&app)?;
    let settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    let saved = settings.aisc_cli_path().map(PathBuf::from);
    let explicit = explicit_cli_path(&app, explicit_path);

    let raw = enumerate_candidates(explicit.as_deref(), saved.as_deref());
    let mut candidates = Vec::with_capacity(raw.len());
    for (p, s) in raw {
        candidates.push(validate_candidate(p, s).await);
    }

    let valid_count = candidates.iter().filter(|c| c.valid).count();
    let (selected, needs_confirm, error) = match (&saved, valid_count) {
        (Some(pin), _) => {
            let pin_valid = candidates
                .iter()
                .any(|c| c.valid && same_path(&c.path, pin));
            if pin_valid {
                (Some(pin.to_string_lossy().into_owned()), false, None)
            } else {
                (
                    None,
                    false,
                    Some(
                        WorkbenchError::cli_not_found()
                            .with_detail(format!("pinned CLI invalid: {}", pin.display())),
                    ),
                )
            }
        }
        (None, 1) => (
            candidates.iter().find(|c| c.valid).map(|c| c.path.clone()),
            false,
            None,
        ),
        // KI-3: carry per-candidate probe results so "CLI not found" is
        // diagnosable from the gate (which candidate, which error code).
        (None, 0) => {
            let mut err = WorkbenchError::cli_not_found();
            let detail = candidates
                .iter()
                .map(|c| format!("{} [{}] -> {}", c.path, source_label(c.source), c.error.as_deref().unwrap_or("?")))
                .collect::<Vec<_>>()
                .join("; ");
            if !detail.is_empty() {
                err = err.with_detail(detail);
            }
            (None, false, Some(err))
        }
        (None, _) => (None, true, None), // >1 valid, no pin -> user must confirm
    };

    Ok(DiscoveryReport {
        candidates,
        selected,
        needs_confirm,
        error,
    })
}

#[tauri::command]
pub async fn cli_pin(app: AppHandle, path: String) -> Result<CapabilityReport, WorkbenchError> {
    let raw = PathBuf::from(&path);
    let canon = std::fs::canonicalize(&raw)
        .map_err(|e| WorkbenchError::cli_not_found().with_detail(format!("canonicalize: {e}")))?;
    if !is_executable(&canon) {
        return Err(WorkbenchError::cli_not_found().with_detail("not executable"));
    }
    let report = negotiate(&canon, CancellationToken::new()).await;
    if !report.required_ok {
        return Ok(report); // surface the unsupported report, do not pin
    }
    let dir = config_dir(&app)?;
    let mut settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    settings.set_aisc_cli_path(Some(&canon.to_string_lossy()));
    settings.save(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    Ok(report)
}

#[tauri::command]
pub async fn cli_clear_pin(app: AppHandle) -> Result<(), WorkbenchError> {
    let dir = config_dir(&app)?;
    let mut settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    settings.set_aisc_cli_path(None);
    settings.save(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    Ok(())
}

/// Auto-select the highest-priority valid CLI candidate (S4.1.a sidecar >
/// PATH > platform) and PERSIST it as the pin. Returns the selected path
/// (already capability-checked) or an enriched cli_not_found.
///
/// KI-3 round 2 (2026-08-18): the REAL recurrence was `session::resolve_pin`
/// racing negotiate — during the onboarding wizard negotiate is deferred, so
/// the wizard env probe and the post-wizard preflight saw "no pin" and failed
/// with a BARE cli_not_found (technical_detail: null); the manual re-detect
/// passed because negotiate had by then written the pin. `session::resolve_cli`
/// now delegates here whenever the pin is absent, so every CLI consumer
/// converges on the same auto-selection instead of failing the race.
pub async fn auto_select_and_pin(app: &AppHandle) -> Result<PathBuf, WorkbenchError> {
    let dir = config_dir(app)?;
    let mut settings = Settings::load(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    let raw = enumerate_candidates(None, None);
    let mut valid: Vec<PathBuf> = Vec::new();
    let mut probed: Vec<Candidate> = Vec::new();
    for (p, _) in raw {
        let candidate = validate_candidate(p.clone(), CandidateSource::PathEnv).await;
        if candidate.valid {
            valid.push(p);
        }
        probed.push(candidate);
    }
    if let Some(first) = valid.first() {
        // Pin only a COMPATIBLE CLI (same contract as negotiate below).
        let report = negotiate(&first, CancellationToken::new()).await;
        if !report.required_ok {
            return Err(WorkbenchError::cli_not_found().with_detail(format!(
                "candidate lacks required capabilities: {}",
                first.display()
            )));
        }
        settings.set_aisc_cli_path(Some(&first.to_string_lossy()));
        settings.save(&dir).map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
        return Ok(first.clone());
    }
    // KI-3: no valid candidate — say WHY each probe failed (path + error
    // code), so a recurrence is diagnosable from the blocked gate instead of
    // a bare "CLI not found". Empty candidate list stays a plain error.
    let mut err = WorkbenchError::cli_not_found();
    if !probed.is_empty() {
        let detail = probed
            .iter()
            .map(|c| format!("{} [{}] -> {}", c.path, source_label(c.source), c.error.as_deref().unwrap_or("?")))
            .collect::<Vec<_>>()
            .join("; ");
        err = err.with_detail(detail);
    }
    Err(err)
}

#[tauri::command]
pub async fn negotiate_capabilities(app: AppHandle) -> Result<CapabilityReport, WorkbenchError> {
    let cancel = CancellationToken::new();
    // `--aisc-cli` process arg outranks the saved pin (S4.1.a).
    if let Some(explicit) = explicit_cli_path(&app, None) {
        return Ok(negotiate(&explicit, cancel).await);
    }
    if let Ok(pin) = crate::session::resolve_pin(&app) {
        return Ok(negotiate(&pin, cancel).await);
    }
    // No pin — or a STALE one (pinned file deleted by uninstall/upgrade;
    // resolve_pin errs on it, KI-3 round 3): auto-select + persist, then report.
    let first = auto_select_and_pin(&app).await?;
    Ok(negotiate(&first, cancel).await)
}

/// Short human label for a candidate source (diagnostic detail only). */
fn source_label(source: CandidateSource) -> &'static str {
    match source {
        CandidateSource::Explicit => "explicit",
        CandidateSource::Saved => "saved",
        CandidateSource::PathEnv => "path",
        CandidateSource::Platform => "platform",
        CandidateSource::Sidecar => "sidecar",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    fn caps(runtime: Option<&str>, session: Option<&str>, provider: Option<&str>, build: Option<&str>) -> Capabilities {
        Capabilities {
            runtime: runtime.map(str::to_string),
            session: session.map(str::to_string),
            provider_status: provider.map(str::to_string),
            build_events: build.map(str::to_string),
        }
    }

    #[test]
    fn classify_all_present() {
        let (ok, mr, mo) = classify(&caps(
            Some(EXPECTED_RUNTIME),
            Some(EXPECTED_SESSION),
            Some(EXPECTED_PROVIDER),
            Some(EXPECTED_BUILD),
        ));
        assert!(ok);
        assert!(mr.is_empty());
        assert!(mo.is_empty());
    }

    #[test]
    fn classify_missing_required_blocks() {
        let (ok, mr, mo) = classify(&caps(None, Some(EXPECTED_SESSION), Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD)));
        assert!(!ok);
        assert_eq!(mr, vec!["runtime"]);
        assert!(mo.is_empty());
    }

    #[test]
    fn classify_missing_optional_does_not_block() {
        let (ok, mr, mo) = classify(&caps(Some(EXPECTED_RUNTIME), Some(EXPECTED_SESSION), None, None));
        assert!(ok);
        assert!(mr.is_empty());
        assert_eq!(mo, vec!["providerStatus", "buildEvents"]);
    }

    #[test]
    fn classify_wrong_version_is_missing() {
        let (ok, _, _) = classify(&caps(Some("aisc.runtime/v2"), Some(EXPECTED_SESSION), None, None));
        assert!(!ok);
    }

    // --- Stage 2 (S2.3, CLI-A03): systematic capability matrix ---

    /// (runtime, session, provider, build, required_ok, missing_required, missing_optional)
    const CAP_MATRIX: [(&str, Option<&str>, Option<&str>, Option<&str>, Option<&str>, bool, &[&str], &[&str]); 8] = [
        // all present at v1
        ("all-v1", Some(EXPECTED_RUNTIME), Some(EXPECTED_SESSION), Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD), true, &[], &[]),
        // each required missing blocks
        ("no-runtime", None, Some(EXPECTED_SESSION), Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD), false, &["runtime"], &[]),
        ("no-session", Some(EXPECTED_RUNTIME), None, Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD), false, &["session"], &[]),
        // old version counts as missing (fail closed, no guessing)
        ("old-runtime", Some("aisc.runtime/v2"), Some(EXPECTED_SESSION), Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD), false, &["runtime"], &[]),
        ("old-session", Some(EXPECTED_RUNTIME), Some("aisc.session/v2"), Some(EXPECTED_PROVIDER), Some(EXPECTED_BUILD), false, &["session"], &[]),
        // optional missing does not block
        ("no-provider", Some(EXPECTED_RUNTIME), Some(EXPECTED_SESSION), None, Some(EXPECTED_BUILD), true, &[], &["providerStatus"]),
        ("no-build", Some(EXPECTED_RUNTIME), Some(EXPECTED_SESSION), Some(EXPECTED_PROVIDER), None, true, &[], &["buildEvents"]),
        // everything absent
        ("all-absent", None, None, None, None, false, &["runtime", "session"], &["providerStatus", "buildEvents"]),
    ];

    #[test]
    fn capability_matrix_is_systematic() {
        for (name, runtime, session, provider, build, ok, mr, mo) in CAP_MATRIX {
            let caps = caps(runtime, session, provider, build);
            let (got_ok, got_mr, got_mo) = classify(&caps);
            assert_eq!(got_ok, ok, "[{name}] required_ok");
            assert_eq!(got_mr, mr, "[{name}] missing_required");
            assert_eq!(got_mo, mo, "[{name}] missing_optional");
        }
    }

    #[test]
    fn missing_required_capability_yields_stable_error_and_action() {
        // CLI-A03: a missing required capability must surface the stable
        // unsupported code + upgrade action so callers never proceed into a
        // command the CLI cannot serve (fail closed, no silent downgrade).
        use crate::error::Action;
        let body = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 0},
            "data": {"capabilities": {"session": EXPECTED_SESSION}},
            "errors": []
        });
        let env: Envelope = serde_json::from_value(body).unwrap();
        let report = report_from_envelope(env);
        assert!(!report.required_ok, "missing runtime must not be required_ok");
        let e = report.error.expect("missing required must carry an error");
        assert_eq!(e.code, "WB_ERR_CAPABILITY_UNSUPPORTED");
        assert!(matches!(e.action, Action::UpgradeCli), "action must be UpgradeCli");
        assert!(!e.retryable);
    }

    #[test]
    fn full_capability_report_has_no_error() {
        let body = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 0},
            "data": {"capabilities": {
                "runtime": EXPECTED_RUNTIME,
                "session": EXPECTED_SESSION,
                "providerStatus": EXPECTED_PROVIDER,
                "buildEvents": EXPECTED_BUILD,
            }},
            "errors": []
        });
        let env: Envelope = serde_json::from_value(body).unwrap();
        let report = report_from_envelope(env);
        assert!(report.required_ok);
        assert!(report.error.is_none());
        assert!(report.missing_required.is_empty());
    }

    #[test]
    fn parse_valid_envelope() {
        let body = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 0,
                     "timestamp": "t", "version": "1.0", "run_id": "r"},
            "data": {"cli_version": "1.0", "capabilities": {
                "runtime": "aisc.runtime/v1", "session": "aisc.session/v1",
                "providerStatus": "aisc.provider-status/v1", "buildEvents": "aisc.build-events/v1"}},
            "errors": []
        });
        let bytes = serde_json::to_vec(&body).unwrap();
        let env = parse_and_validate(&bytes, Some(0)).expect("valid");
        assert_eq!(env.meta.command, "version");
    }

    #[test]
    fn parse_bad_json_is_protocol_error() {
        let err = parse_and_validate(b"not json", Some(0)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn parse_wrong_protocol_is_protocol_error() {
        let body = json!({"meta": {"protocol": "other", "command": "x", "exit_code": 0}, "data": null, "errors": []});
        let err = parse_and_validate(&serde_json::to_vec(&body).unwrap(), Some(0)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn parse_exit_code_mismatch_is_protocol_error() {
        let body = json!({"meta": {"protocol": "aisc.cli/v1", "command": "x", "exit_code": 0}, "data": null, "errors": []});
        let err = parse_and_validate(&serde_json::to_vec(&body).unwrap(), Some(2)).unwrap_err();
        assert_eq!(err.code, "WB_ERR_CLI_PROTOCOL");
    }

    #[test]
    fn enumerate_priority_and_dedup() {
        let a = PathBuf::from("/x/aisc");
        let b = PathBuf::from("/y/aisc");
        let extra = vec![(PathBuf::from("/z/aisc"), CandidateSource::PathEnv)];

        let r = enumerate_with(Some(&a), Some(&b), &extra);
        assert_eq!(r.len(), 3);
        assert_eq!(r[0].1, CandidateSource::Explicit);
        assert_eq!(r[1].1, CandidateSource::Saved);
        assert_eq!(r[2].1, CandidateSource::PathEnv);
    }

    #[test]
    fn enumerate_dedups_same_path() {
        let a = PathBuf::from("/x/aisc");
        let r = enumerate_with(Some(&a), Some(&a), &[]);
        assert_eq!(r.len(), 1);
    }

    #[test]
    fn sidecar_priority_over_path_env() {
        // S4.1.a: explicit > saved > sidecar > PATH > platform. enumerate_with
        // takes the extras in order, so feeding sidecar first proves the order.
        let explicit = PathBuf::from("/explicit/aisc");
        let saved = PathBuf::from("/saved/aisc");
        let extra = vec![
            (PathBuf::from("/sidecar/aisc"), CandidateSource::Sidecar),
            (PathBuf::from("/path/aisc"), CandidateSource::PathEnv),
        ];
        let r = enumerate_with(Some(&explicit), Some(&saved), &extra);
        assert_eq!(r.len(), 4);
        assert_eq!(r[0].1, CandidateSource::Explicit);
        assert_eq!(r[1].1, CandidateSource::Saved);
        assert_eq!(r[2].1, CandidateSource::Sidecar);
        assert_eq!(r[3].1, CandidateSource::PathEnv);
    }

    #[test]
    fn five_source_priority_is_strict_and_deduped() {
        // CLI-A04: explicit > saved > sidecar > PATH > platform, dedup by path.
        let explicit = PathBuf::from("/explicit/aisc");
        let saved = PathBuf::from("/saved/aisc");
        let extra = vec![
            (PathBuf::from("/sidecar/aisc"), CandidateSource::Sidecar),
            (PathBuf::from("/path/aisc"), CandidateSource::PathEnv),
            (PathBuf::from("/platform/aisc"), CandidateSource::Platform),
        ];
        let r = enumerate_with(Some(&explicit), Some(&saved), &extra);
        assert_eq!(r.len(), 5);
        assert_eq!(r[0].1, CandidateSource::Explicit);
        assert_eq!(r[1].1, CandidateSource::Saved);
        assert_eq!(r[2].1, CandidateSource::Sidecar);
        assert_eq!(r[3].1, CandidateSource::PathEnv);
        assert_eq!(r[4].1, CandidateSource::Platform);
        // Same path offered as both explicit and saved collapses to the
        // higher-priority source (Explicit) — dedup keeps the first.
        let r2 = enumerate_with(Some(&explicit), Some(&explicit), &extra);
        assert_eq!(r2.len(), 4); // explicit (+3 extras), saved deduped away
        assert_eq!(r2[0].1, CandidateSource::Explicit);
    }

    #[test]
    fn candidate_from_envelope_carries_source_path_version_caps() {
        // CLI-A04: the discovery result exposes absolute path, source, version
        // and capabilities so the UI can render where the CLI came from.
        let body = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 0},
            "data": {"cli_version": "2.1.5.dev0", "capabilities": {
                "runtime": EXPECTED_RUNTIME,
                "session": EXPECTED_SESSION,
                "providerStatus": EXPECTED_PROVIDER,
                "buildEvents": EXPECTED_BUILD,
            }},
            "errors": []
        });
        let env: Envelope = serde_json::from_value(body).unwrap();
        let c = candidate_from_envelope("/abs/aisc".into(), CandidateSource::Explicit, env);
        assert!(c.valid);
        assert_eq!(c.path, "/abs/aisc");
        assert_eq!(c.source, CandidateSource::Explicit);
        assert_eq!(c.version_info.unwrap().cli_version.as_deref(), Some("2.1.5.dev0"));
        let caps = c.capabilities.unwrap();
        assert_eq!(caps.runtime.as_deref(), Some(EXPECTED_RUNTIME));
        assert_eq!(c.error, None);
    }

    #[test]
    fn candidate_from_envelope_surfaces_error_code() {
        // A CLI that answers with a stable error code is invalid + surfaced,
        // never silently treated as OK (fail closed).
        let body = json!({
            "meta": {"protocol": "aisc.cli/v1", "command": "version", "exit_code": 1},
            "data": null,
            "errors": [{"code": "AISC_ERR_CAPABILITY_UNSUPPORTED", "message": "x"}]
        });
        let env: Envelope = serde_json::from_value(body).unwrap();
        let c = candidate_from_envelope("/abs/aisc".into(), CandidateSource::PathEnv, env);
        assert!(!c.valid);
        assert_eq!(c.error.as_deref(), Some("AISC_ERR_CAPABILITY_UNSUPPORTED"));
        assert!(c.version_info.is_none());
        assert!(c.capabilities.is_none());
    }

    #[test]
    fn sidecar_lookup_finds_file_named_with_triple() {
        let dir = tempdir().unwrap();
        let triple = target_triple();
        let name = format!("aisc-{triple}");
        let file = dir.path().join(if cfg!(windows) { format!("{name}.exe") } else { name.clone() });
        std::fs::write(&file, b"x").unwrap();
        let found = sidecar_candidate_in(dir.path());
        assert_eq!(found.as_deref(), Some(file.as_path()));
    }

    #[test]
    fn sidecar_lookup_finds_base_name() {
        // tauri-bundler 2.9.x installs the externalBin sidecar under its base
        // name (triple stripped): `aisc` / `aisc.exe` next to the main binary.
        let dir = tempdir().unwrap();
        let file = dir.path().join(if cfg!(windows) { "aisc.exe" } else { "aisc" });
        std::fs::write(&file, b"x").unwrap();
        let found = sidecar_candidate_in(dir.path());
        assert_eq!(found.as_deref(), Some(file.as_path()));
    }

    #[test]
    fn sidecar_lookup_none_when_absent() {
        let dir = tempdir().unwrap();
        assert!(sidecar_candidate_in(dir.path()).is_none());
    }

    #[test]
    fn path_lookup_finds_first_match() {
        let dir = std::env::temp_dir();
        let exe = if cfg!(windows) { "aisc.exe" } else { "aisc" };
        let fake = dir.join(exe);
        std::fs::write(&fake, b"#!/bin/sh\n").ok();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755));
        }

        let path_var = dir.to_string_lossy().to_string();
        let found = path_candidate_in(Some(&path_var));
        assert_eq!(found, Some(fake.clone()));

        let _ = std::fs::remove_file(&fake);
    }

    #[test]
    fn path_lookup_empty_returns_none() {
        assert_eq!(path_candidate_in(Some("")), None);
        assert_eq!(path_candidate_in(None), None);
    }

    // --- Stage 0 (S0.4, B-R04): resource budgets and truncation semantics ---

    #[tokio::test]
    async fn read_capped_truncates_at_cap_and_drains() {
        let data: Vec<u8> = (0u8..=255).collect();
        let mut reader = &data[..];
        let (buf, truncated) = read_capped(&mut reader, 8).await;
        assert_eq!(buf.len(), 8);
        assert!(truncated, "overflow must be observable");
    }

    #[tokio::test]
    async fn read_capped_passes_through_under_cap() {
        let mut reader = &b"hello"[..];
        let (buf, truncated) = read_capped(&mut reader, 64).await;
        assert_eq!(buf, b"hello");
        assert!(!truncated);
    }

    #[tokio::test]
    async fn read_capped_empty_input() {
        let mut reader = &b""[..];
        let (buf, truncated) = read_capped(&mut reader, 8).await;
        assert!(buf.is_empty());
        assert!(!truncated);
    }

    #[test]
    fn control_plane_budget_is_stable() {
        // S0.4 (B-R04): freeze control-plane caps so a future change is a
        // deliberate, reviewed adjustment rather than a silent growth.
        assert_eq!(MAX_STDOUT, 8 * 1024 * 1024);
        assert_eq!(MAX_STDERR, 64 * 1024);
    }
}
