//! Lifecycle event log (lifecycle-logging P1) — the app-side appender.
//!
//! One JSONL event per line in `<data root>/logs/aisc.log`, shared with the
//! Python CLI's appender (`aisc.applog`): a single timeline where one
//! `run_id` — generated here per CLI call, injected into the child via the
//! `AISC_RUN_ID` env var, reused by the envelope and the CLI's `cli_exit`
//! line — threads 界面操作 → CLI 调用 → 容器操作 end to end.
//!
//! Red line (allowed-fields-only, mirrors the diagnostic bundle D6-05/06):
//! stdin payloads, subscription URLs, API keys, PTY content and full
//! environments never enter the log. Best-effort by contract — a logging
//! failure must never fail an operation.

use std::io::Write;
use std::path::PathBuf;

use serde_json::{json, Value};

/// Rotation bounds — byte sizes kept identical to the Python side
/// (`aisc.applog`) so either appender rotates the file.
pub(crate) const MAX_BYTES: u64 = 2 * 1024 * 1024;
const KEEP_ROTATED: u32 = 2; // aisc.log + .1 + .2

/// The log file path; None when the data root can't be resolved (caller
/// then skips logging — fail-open).
pub(crate) fn log_file_path() -> Option<PathBuf> {
    Some(crate::data_root::default_data_root().join("logs").join("aisc.log"))
}

/// RFC3339 UTC from epoch milliseconds (std-only; Howard Hinnant's
/// civil-from-days). Millisecond precision — Python-side lines are
/// second-precision; both parse as valid timestamps on one timeline.
pub(crate) fn iso8601_from_epoch_ms(ms: u64) -> String {
    let secs = ms / 1000;
    let millis = ms % 1000;
    let days = (secs / 86400) as i64;
    let sod = secs % 86400;
    let (h, m, s) = (sod / 3600, (sod % 3600) / 60, sod % 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mth = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if mth <= 2 { y + 1 } else { y };
    format!("{y:04}-{mth:02}-{d:02}T{h:02}:{m:02}:{s:02}.{millis:03}Z")
}

fn now_iso8601() -> String {
    let ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    iso8601_from_epoch_ms(ms)
}

/// Append one lifecycle event (`source: "app"`). Never panics on IO.
pub(crate) fn append_event(
    level: &str,
    event: &str,
    run_id: Option<&str>,
    extra: Value,
) {
    let Some(path) = log_file_path() else { return };
    let mut record = json!({
        "ts": now_iso8601(),
        "level": level,
        "source": "app",
        "event": event,
    });
    if let Some(id) = run_id {
        record["run_id"] = json!(id);
    }
    if let Value::Object(fields) = extra {
        for (k, v) in fields {
            record[k] = v;
        }
    }
    let line = format!("{}\n", serde_json::to_string(&record).unwrap_or_default());
    let Some(parent) = path.parent() else { return };
    let _ = std::fs::create_dir_all(parent);
    let _ = rotate(&path, MAX_BYTES);
    let Ok(mut fh) = std::fs::OpenOptions::new().create(true).append(true).open(&path)
    else {
        return;
    };
    let _ = fh.write_all(line.as_bytes());
}

/// Size-capped rotation: aisc.log → .1 → .2 (oldest dropped).
fn rotate(path: &std::path::Path, max_bytes: u64) -> std::io::Result<()> {
    let Ok(meta) = std::fs::metadata(path) else { return Ok(()) };
    if meta.len() < max_bytes {
        return Ok(());
    }
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("aisc.log");
    let parent = path.parent().unwrap_or_else(|| std::path::Path::new("."));
    for i in (1..KEEP_ROTATED).rev() {
        let src = parent.join(format!("{name}.{i}"));
        let dst = parent.join(format!("{name}.{}", i + 1));
        if src.exists() {
            std::fs::rename(&src, &dst)?;
        }
    }
    std::fs::rename(path, parent.join(format!("{name}.1")))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // Rotation math against a temp file with a tiny bound.
    #[test]
    fn rotate_rolls_and_drops_oldest() {
        let dir = std::env::temp_dir().join(format!("aisc-log-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let log = dir.join("aisc.log");
        std::fs::write(&log, "x").unwrap();
        std::fs::write(dir.join("aisc.log.1"), "old").unwrap();
        std::fs::write(dir.join("aisc.log.2"), "oldest").unwrap();

        rotate(&log, 1).unwrap();

        assert!(dir.join("aisc.log.2").exists()); // .1 → .2 (dropped oldest)
        assert!(dir.join("aisc.log.1").exists()); // log → .1
        assert!(!log.exists());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn max_bytes_matches_python_side() {
        // cross-side rotation parity — see aisc.applog.MAX_BYTES
        assert_eq!(MAX_BYTES, 2 * 1024 * 1024);
    }

    #[test]
    fn iso8601_known_epochs() {
        assert_eq!(iso8601_from_epoch_ms(0), "1970-01-01T00:00:00.000Z");
        // 2026-08-06T09:06:31Z == 1786007191s (verified against Python)
        assert_eq!(
            iso8601_from_epoch_ms(1_786_007_191_500),
            "2026-08-06T09:06:31.500Z"
        );
        // leap-year day: 2024-02-29T12:00:00Z == 1709208000s
        assert_eq!(
            iso8601_from_epoch_ms(1_709_208_000_000),
            "2024-02-29T12:00:00.000Z"
        );
    }
}
