//! O7 (opt-batch, D-11): docker disk/cache panel — `aisc maintenance
//! cache-usage` / `cache-cleanup` behind typed Tauri commands. The CLI owns
//! every safety invariant (until-filtered prunes only, never global, never
//! `-a`); this layer is transport + envelope validation only (doctor.rs
//! pattern).

use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::AppHandle;

use crate::cli::run_control;
use crate::error::WorkbenchError;
use crate::session::resolve_cli;
use tokio_util::sync::CancellationToken;

const CACHE_TIMEOUT: Duration = Duration::from_secs(300);

/// Pure argv builders (05 §六 style; unit-pinned).
pub fn cache_usage_argv() -> Vec<String> {
    vec![
        "maintenance".into(),
        "cache-usage".into(),
        "--format".into(),
        "json".into(),
    ]
}

pub fn cache_cleanup_argv(min_age_hours: u32) -> Vec<String> {
    vec![
        "maintenance".into(),
        "cache-cleanup".into(),
        "--min-age-hours".into(),
        min_age_hours.to_string(),
        "--format".into(),
        "json".into(),
    ]
}

/// One `docker system df` row (type-keyed by the caller). Field names are
/// the CLI envelope's snake_case projection, not docker's raw PascalCase.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CacheDfRow {
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub total_count: String,
    #[serde(default)]
    pub active: String,
    #[serde(default)]
    pub size: String,
    #[serde(default)]
    pub reclaimable: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheUsage {
    pub docker_available: bool,
    pub rows: Vec<CacheDfRow>,
}

/// One prune outcome (kind = builder | dangling).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CachePruneEntry {
    pub kind: String,
    pub exit_code: i32,
    pub reclaimed: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheCleanupResult {
    pub prunes: Vec<CachePruneEntry>,
    pub warnings: Vec<String>,
    /// df rows after the run (the "before" rides the usage panel already).
    pub rows_after: Vec<CacheDfRow>,
}

fn df_rows_from(value: Value) -> Vec<CacheDfRow> {
    match value.get("df").and_then(|d| d.as_object()) {
        Some(map) => map
            .iter()
            .filter_map(|(kind, raw)| {
                let mut row: CacheDfRow = serde_json::from_value(raw.clone()).ok()?;
                row.kind = kind.clone();
                Some(row)
            })
            .collect(),
        None => Vec::new(),
    }
}

fn envelope_data(
    env: crate::cli::Envelope,
    expect_command: &str,
) -> Result<Value, WorkbenchError> {
    if let Some(err) = env.errors.first() {
        return Err(WorkbenchError::map_aisc(&err.code).with_detail(err.message.clone()));
    }
    if env.meta.command != expect_command {
        return Err(WorkbenchError::cli_protocol().with_detail(format!(
            "unexpected command: {}",
            env.meta.command
        )));
    }
    Ok(env.data.unwrap_or(Value::Null))
}

/// Read-only `docker system df` summary for the settings card.
#[tauri::command]
pub async fn cache_usage(app: AppHandle) -> Result<CacheUsage, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let env = run_control(
        &pin,
        cache_usage_argv(),
        CACHE_TIMEOUT,
        CancellationToken::new(),
    )
    .await?;
    let data = envelope_data(env, "maintenance")?;
    Ok(CacheUsage {
        docker_available: data
            .get("docker_available")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        rows: df_rows_from(data),
    })
}

/// Prune the builder cache + dangling images (until-filtered, CLI-owned
/// invariants). Returns per-prune outcomes and the post-run df.
#[tauri::command]
pub async fn cache_cleanup(
    app: AppHandle,
    min_age_hours: u32,
) -> Result<CacheCleanupResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let env = run_control(
        &pin,
        cache_cleanup_argv(min_age_hours),
        CACHE_TIMEOUT,
        CancellationToken::new(),
    )
    .await?;
    let data = envelope_data(env, "maintenance")?;
    Ok(CacheCleanupResult {
        prunes: data
            .get("prunes")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|v| serde_json::from_value(v.clone()).ok())
                    .collect()
            })
            .unwrap_or_default(),
        warnings: data
            .get("warnings")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        rows_after: df_rows_from(data.get("df_after").cloned().unwrap_or(Value::Null)),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn usage_argv_is_read_only() {
        assert_eq!(
            cache_usage_argv(),
            vec!["maintenance", "cache-usage", "--format", "json"]
        );
    }

    #[test]
    fn cleanup_argv_carries_age_filter() {
        assert_eq!(
            cache_cleanup_argv(24),
            vec![
                "maintenance",
                "cache-cleanup",
                "--min-age-hours",
                "24",
                "--format",
                "json"
            ]
        );
    }

    #[test]
    fn df_rows_parse_type_keyed_map() {
        // The CLI envelope projects docker's PascalCase df to snake_case.
        let data: Value = serde_json::json!({
            "docker_available": true,
            "df": {
                "Build Cache": {
                    "total_count": "120", "active": "0",
                    "size": "6.7GB", "reclaimable": "4.1GB (61%)"
                }
            }
        });
        let rows = df_rows_from(data);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].kind, "Build Cache");
        assert_eq!(rows[0].size, "6.7GB");
        assert_eq!(rows[0].reclaimable, "4.1GB (61%)");
    }

    #[test]
    fn df_rows_tolerate_missing_map() {
        assert!(df_rows_from(Value::Null).is_empty());
        assert!(df_rows_from(serde_json::json!({})).is_empty());
    }
}
