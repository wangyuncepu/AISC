//! Agent conversation discovery IPC (v2.1.8 T4, design §1f).
//!
//! Two captured commands over the T3 CLI surface — no PTY, no Channel:
//!   conversation_list      → `aisc conversation list --format json`
//!   conversation_preflight → `aisc conversation preflight --format json`
//!
//! Envelope errors flow through `WorkbenchError::map_aisc`; the three
//! `AISC_ERR_CONVERSATION_*` codes carry their Chinese mappings in
//! error.rs. Per design §1c the RESUME action itself is NOT an IPC — the
//! frontend orchestrates preflight → createTab → open_session with
//! `resume_conversation_id`.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use tauri::AppHandle;
use tokio_util::sync::CancellationToken;

use crate::cli::{run_control, Envelope};
use crate::error::WorkbenchError;
use crate::runtime::envelope_error;
use crate::session::resolve_cli;

/// Captured discovery commands are file scans — fast, but a cold first
/// call may also pin/locate the sidecar; a bounded 30s keeps the UI
/// responsive while tolerating cold paths.
const CONVERSATION_TIMEOUT: Duration = Duration::from_secs(30);

/// D-5 (decisions.md): conversation ids are provider-native — Codex ships
/// time-ordered UUIDv7, so any RFC-4122 version is accepted. Non-UUID
/// garbage is still rejected.
pub(crate) fn is_conversation_uuid(id: &str) -> bool {
    let b = id.as_bytes();
    if b.len() != 36 {
        return false;
    }
    for (i, ch) in b.iter().enumerate() {
        match i {
            8 | 13 | 18 | 23 => {
                if *ch != b'-' {
                    return false;
                }
            }
            _ => {
                if !ch.is_ascii_hexdigit() {
                    return false;
                }
            }
        }
    }
    true
}

// -- argv builders (pure, unit-testable; cf. session.rs / runtime.rs) --

fn conversation_list_argv(workspace: &str) -> Vec<String> {
    vec![
        "conversation".into(),
        "list".into(),
        "--workspace".into(),
        workspace.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn conversation_preflight_argv(
    workspace: &str,
    conversation_id: &str,
    agent: &str,
) -> Vec<String> {
    vec![
        "conversation".into(),
        "preflight".into(),
        "--workspace".into(),
        workspace.into(),
        "--conversation-id".into(),
        conversation_id.into(),
        "--agent".into(),
        agent.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn conversation_delete_argv(
    workspace: &str,
    conversation_id: &str,
    agent: &str,
) -> Vec<String> {
    vec![
        "conversation".into(),
        "delete".into(),
        "--workspace".into(),
        workspace.into(),
        "--conversation-id".into(),
        conversation_id.into(),
        "--agent".into(),
        agent.into(),
        "--format".into(),
        "json".into(),
    ]
}

fn conversation_rename_argv(
    workspace: &str,
    conversation_id: &str,
    agent: &str,
    title: &str,
) -> Vec<String> {
    vec![
        "conversation".into(),
        "rename".into(),
        "--workspace".into(),
        workspace.into(),
        "--conversation-id".into(),
        conversation_id.into(),
        "--agent".into(),
        agent.into(),
        "--title".into(),
        title.into(),
        "--format".into(),
        "json".into(),
    ]
}

// -- wire types (TS mirrors in workbench/src/types/index.ts) --

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationSummary {
    pub conversation_id: String,
    pub agent: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub last_at: Option<String>,
    #[serde(default)]
    pub message_count: Option<u64>,
    #[serde(default)]
    pub file_size: u64,
    #[serde(default)]
    pub resumable: bool,
    #[serde(default)]
    pub unavailable_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationListResult {
    #[serde(default)]
    pub conversations: Vec<ConversationSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationPreflightResult {
    pub conversation_id: String,
    pub agent: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationDeleteResult {
    pub deleted: bool,
    pub conversation_id: String,
    pub agent: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationRenameResult {
    pub renamed: bool,
    pub conversation_id: String,
    pub agent: String,
    pub title: String,
}

// -- commands --

#[tauri::command]
pub async fn conversation_list(
    app: AppHandle,
    workspace: String,
) -> Result<ConversationListResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let argv = conversation_list_argv(&workspace);
    let env: Envelope = run_control(&pin, argv, CONVERSATION_TIMEOUT, CancellationToken::new())
        .await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<ConversationListResult>(data)
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("conversation list parse: {e}")))
}

#[tauri::command]
pub async fn conversation_preflight(
    app: AppHandle,
    workspace: String,
    conversation_id: String,
    agent: String,
) -> Result<ConversationPreflightResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let argv = conversation_preflight_argv(&workspace, &conversation_id, &agent);
    let env: Envelope = run_control(&pin, argv, CONVERSATION_TIMEOUT, CancellationToken::new())
        .await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<ConversationPreflightResult>(data)
        .map_err(|e| {
            WorkbenchError::cli_protocol()
                .with_detail(format!("conversation preflight parse: {e}"))
        })
}

/// v2.1.8 T4 手测反馈 #4: delete a conversation's session file. The confirm
/// dialog lives in the frontend; this is a captured CLI pass-through.
#[tauri::command]
pub async fn conversation_delete(
    app: AppHandle,
    workspace: String,
    conversation_id: String,
    agent: String,
) -> Result<ConversationDeleteResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let argv = conversation_delete_argv(&workspace, &conversation_id, &agent);
    let env: Envelope = run_control(&pin, argv, CONVERSATION_TIMEOUT, CancellationToken::new())
        .await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<ConversationDeleteResult>(data)
        .map_err(|e| {
            WorkbenchError::cli_protocol()
                .with_detail(format!("conversation delete parse: {e}"))
        })
}

/// v2.1.8 T4 手测反馈 #2: set a conversation's Workbench display title
/// (override map under the workspace runtime dir; provider titles untouched).
#[tauri::command]
pub async fn conversation_rename(
    app: AppHandle,
    workspace: String,
    conversation_id: String,
    agent: String,
    title: String,
) -> Result<ConversationRenameResult, WorkbenchError> {
    let pin = resolve_cli(&app).await?;
    let argv = conversation_rename_argv(&workspace, &conversation_id, &agent, &title);
    let env: Envelope = run_control(&pin, argv, CONVERSATION_TIMEOUT, CancellationToken::new())
        .await?;
    if let Some(e) = envelope_error(&env) {
        return Err(e);
    }
    let data = env.data.unwrap_or(Value::Null);
    serde_json::from_value::<ConversationRenameResult>(data)
        .map_err(|e| {
            WorkbenchError::cli_protocol()
                .with_detail(format!("conversation rename parse: {e}"))
        })
}

// -- tests --

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_argv_shape() {
        let argv = conversation_list_argv("C:/ws");
        assert_eq!(argv[0], "conversation");
        assert_eq!(argv[1], "list");
        assert!(argv.contains(&"--format".into()));
        let i = argv.iter().position(|a| a == "--workspace").unwrap();
        assert_eq!(argv[i + 1], "C:/ws");
    }

    #[test]
    fn preflight_argv_shape() {
        let argv = conversation_preflight_argv("/ws", "24b70882-2d45-4cec-a9e2-66f8c012481f", "codex");
        assert_eq!(argv[1], "preflight");
        let i = argv.iter().position(|a| a == "--conversation-id").unwrap();
        assert_eq!(argv[i + 1], "24b70882-2d45-4cec-a9e2-66f8c012481f");
        let i = argv.iter().position(|a| a == "--agent").unwrap();
        assert_eq!(argv[i + 1], "codex");
    }

    #[test]
    fn conversation_uuid_accepts_any_rfc4122_version() {
        // v4 (Claude) and v7 (Codex) both pass; garbage does not.
        assert!(is_conversation_uuid("24b70882-2d45-4cec-a9e2-66f8c012481f"));
        assert!(is_conversation_uuid("01a04ca9-d3f6-7021-b9e7-50d48d818c65"));
        assert!(!is_conversation_uuid(""));
        assert!(!is_conversation_uuid("not-a-uuid"));
        assert!(!is_conversation_uuid("24b708822d454ceca9e266f8c012481f"));
    }
}
