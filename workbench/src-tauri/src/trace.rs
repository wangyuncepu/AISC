//! Bounded operation-timing ring (REL-01; 02-domain-contract.md).
//!
//! Records the most recent operations as
//! `{operation_id, source, phase, duration_ms, outcome, error_code, retryable,
//! action, detail}` (detail redacted). In-memory, bounded, process-local —
//! never persisted and never uploaded (D6-05). Surfaced in the Doctor dialog
//! and included in the exported diagnostic bundle (allowlist only).
//!
//! `run_control` (all CLI ops) and `env_readiness`/`start_docker` feed this.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;

const MAX_TRACES: usize = 64;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpTrace {
    pub operation_id: String,
    pub source: String, // rust | cli | docker | ui
    pub phase: String,
    pub duration_ms: u64,
    pub outcome: String, // ok | error | cancel
    pub error_code: Option<String>,
    pub retryable: bool,
    pub action: Option<String>,
    /// Redacted detail (never raw secrets/args beyond the phase).
    pub detail: Option<String>,
}

static TRACES: OnceLock<Mutex<VecDeque<OpTrace>>> = OnceLock::new();
static OP_COUNTER: AtomicU64 = AtomicU64::new(0);

fn traces() -> &'static Mutex<VecDeque<OpTrace>> {
    TRACES.get_or_init(|| Mutex::new(VecDeque::with_capacity(MAX_TRACES)))
}

fn next_operation_id() -> String {
    let n = OP_COUNTER.fetch_add(1, Ordering::Relaxed);
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("op-{ms:x}-{n}")
}

fn push(source: &str, phase: &str, duration_ms: u64, outcome: &str, error_code: Option<&str>, retryable: bool, action: Option<&str>, detail: Option<&str>) {
    let mut ring = traces().lock().expect("trace ring poisoned");
    ring.push_back(OpTrace {
        operation_id: next_operation_id(),
        source: source.into(),
        phase: phase.into(),
        duration_ms,
        outcome: outcome.into(),
        error_code: error_code.map(String::from),
        retryable,
        action: action.map(String::from),
        detail: detail.map(String::from),
    });
    while ring.len() > MAX_TRACES {
        ring.pop_front();
    }
}

/// Time a future and record it as one operation trace. `phase` names the op;
/// the error's outcome/code/retryable/action are captured via `TraceOutcome`.
pub async fn timed<T, E>(
    source: &str,
    phase: &str,
    f: impl std::future::Future<Output = Result<T, E>>,
) -> Result<T, E>
where
    E: TraceOutcome,
{
    let start = Instant::now();
    let result = f.await;
    let duration_ms = start.elapsed().as_millis() as u64;
    push(
        source,
        phase,
        duration_ms,
        match &result {
            Ok(_) => "ok",
            Err(e) => e.outcome(),
        },
        result.as_ref().err().and_then(|e| e.error_code()),
        result.as_ref().err().map(|e| e.retryable()).unwrap_or(true),
        result.as_ref().err().and_then(|e| e.action()),
        None, // error technical_detail is redacted where shown
    );
    result
}

/// Time an infallible future (records outcome "ok"); used for snapshot-style
/// ops like env_readiness where a value is always returned.
pub async fn timed_ok<T>(source: &str, phase: &str, f: impl std::future::Future<Output = T>) -> T {
    let start = Instant::now();
    let value = f.await;
    push(source, phase, start.elapsed().as_millis() as u64, "ok", None, true, None, None);
    value
}

/// Snapshot of the ring (newest last).
pub fn snapshot() -> Vec<OpTrace> {
    traces().lock().expect("trace ring poisoned").iter().cloned().collect()
}

/// Tauri command: recent operation traces (REL-01; Doctor dialog + bundle).
#[tauri::command]
pub fn op_traces() -> Vec<OpTrace> {
    snapshot()
}

/// Trait so `timed()` can derive outcome/error_code/action from the error.
pub trait TraceOutcome {
    fn outcome(&self) -> &'static str;
    fn error_code(&self) -> Option<&str>;
    fn retryable(&self) -> bool;
    fn action(&self) -> Option<&str>;
}

impl TraceOutcome for crate::error::WorkbenchError {
    fn outcome(&self) -> &'static str {
        "error"
    }
    fn error_code(&self) -> Option<&str> {
        Some(&self.code)
    }
    fn retryable(&self) -> bool {
        self.retryable
    }
    fn action(&self) -> Option<&str> {
        match self.action {
            crate::error::Action::Retry => Some("retry"),
            crate::error::Action::Refresh => Some("refresh"),
            crate::error::Action::UpgradeCli => Some("upgrade_cli"),
            crate::error::Action::StartDocker => Some("start_docker"),
            crate::error::Action::BuildImage => Some("build_image"),
            crate::error::Action::ChooseWorkspace => Some("choose_workspace"),
            crate::error::Action::ChooseCli => Some("choose_cli"),
            crate::error::Action::None => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The ring is process-global and both tests below assert on
    /// `snapshot().last()`, so they must not interleave (CI flake 2026-08-25:
    /// the docker test's snapshot caught the cli test's event as last).
    static TEST_ORDER: OnceLock<Mutex<()>> = OnceLock::new();

    #[tokio::test]
    async fn timed_records_ok_and_bounds_the_ring() {
        let _serial = TEST_ORDER.get_or_init(|| Mutex::new(())).lock().unwrap();
        for _ in 0..(MAX_TRACES + 20) {
            let _: Result<(), crate::error::WorkbenchError> =
                timed("cli", "version", async { Ok(()) }).await;
        }
        let snap = snapshot();
        assert!(snap.len() <= MAX_TRACES, "ring must be bounded");
        assert!(snap.last().unwrap().phase == "version");
        assert!(snap.last().unwrap().outcome == "ok");
    }

    #[tokio::test]
    async fn timed_records_error_outcome() {
        let _serial = TEST_ORDER.get_or_init(|| Mutex::new(())).lock().unwrap();
        let err: Result<(), crate::error::WorkbenchError> =
            timed("docker", "env_readiness", async { Err(crate::error::WorkbenchError::cli_timeout()) }).await;
        assert!(err.is_err());
        let last = snapshot().last().unwrap().clone();
        assert_eq!(last.source, "docker");
        assert_eq!(last.phase, "env_readiness");
        assert_eq!(last.outcome, "error");
        assert_eq!(last.error_code.as_deref(), Some("WB_ERR_CLI_TIMEOUT"));
        assert_eq!(last.action.as_deref(), Some("retry"));
    }
}
