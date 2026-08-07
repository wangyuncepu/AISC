//! Workbench domain error + AISC CLI error code mapping.
//!
//! Spec refs:
//! - 05-cli-gui-contract.md §八 - stable AISC error codes
//! - 02-startup-flow.md §十 - error code -> UI summary/action mapping
//! - 03-lifecycle-contract.md §十 - WorkbenchError shape + action enum
//!
//! Workbench routes UI by `code` only; it never string-matches CLI messages
//! (05 §八). `message` is a short user-facing summary; `technical_detail`
//! carries redacted diagnostics (exit code, run_id, stderr excerpt).

use serde::Serialize;

/// Recovery action surfaced to the UI. Baseline from 03 §十 plus `ChooseCli`
/// for the CLI discovery hard gate (02 §四.3: "选择 CLI 或显示安装说明").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Retry,
    Refresh,
    UpgradeCli,
    StartDocker,
    BuildImage,
    ChooseWorkspace,
    ChooseCli,
    None,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkbenchError {
    pub code: String,
    pub message: String,
    pub technical_detail: Option<String>,
    pub retryable: bool,
    pub action: Action,
}

impl WorkbenchError {
    fn new(code: &str, message: &str, retryable: bool, action: Action) -> Self {
        Self {
            code: code.to_string(),
            message: message.to_string(),
            technical_detail: None,
            action,
            retryable,
        }
    }

    pub fn with_detail(mut self, detail: impl Into<String>) -> Self {
        self.technical_detail = Some(detail.into());
        self
    }

    // -- Workbench transport / protocol errors (WB_ERR_*) --

    pub fn cli_not_found() -> Self {
        Self::new(
            "WB_ERR_CLI_NOT_FOUND",
            "未找到兼容的 AISC CLI",
            false,
            Action::ChooseCli,
        )
    }

    pub fn cli_timeout() -> Self {
        Self::new(
            "WB_ERR_CLI_TIMEOUT",
            "AISC CLI 响应超时",
            true,
            Action::Retry,
        )
    }

    pub fn cli_cancelled() -> Self {
        Self::new(
            "WB_ERR_CLI_CANCELLED",
            "操作已取消",
            false,
            Action::None,
        )
    }

    pub fn cli_protocol() -> Self {
        Self::new(
            "WB_ERR_CLI_PROTOCOL",
            "AISC CLI 输出不符合协议",
            false,
            Action::UpgradeCli,
        )
    }

    pub fn capability_unsupported() -> Self {
        Self::new(
            "WB_ERR_CAPABILITY_UNSUPPORTED",
            "AISC CLI 版本不支持 Workbench",
            false,
            Action::UpgradeCli,
        )
    }

    pub fn settings_error() -> Self {
        Self::new(
            "WB_ERR_SETTINGS",
            "Workbench 配置读取失败",
            false,
            Action::None,
        )
    }

    pub fn input_too_large() -> Self {
        Self::new(
            "WB_ERR_INPUT_TOO_LARGE",
            "输入超过大小上限",
            false,
            Action::None,
        )
    }

    // -- AISC error code mapping (AISC_ERR_*) --

    /// Map a stable AISC CLI error code (from envelope `errors[].code`) to a
    /// Workbench domain error. Unknown codes fall back to a generic retryable
    /// error carrying the raw code.
    pub fn map_aisc(code: &str) -> Self {
        let (message, retryable, action) = match code {
            "AISC_ERR_CAPABILITY_UNSUPPORTED" => {
                ("AISC CLI 版本不支持 Workbench", false, Action::UpgradeCli)
            }
            "AISC_ERR_RUNTIME_NOT_FOUND" => ("Runtime 不存在", false, Action::Refresh),
            "AISC_ERR_RUNTIME_NOT_RUNNING" => ("Runtime 未运行", false, Action::Refresh),
            "AISC_ERR_RUNTIME_CONFLICT" => {
                ("工作区已有不兼容 Runtime", false, Action::None)
            }
            "AISC_ERR_RUNTIME_NOT_READY" => {
                ("Runtime 初始化未完成", true, Action::Retry)
            }
            "AISC_ERR_SESSION_NOT_FOUND" => ("Session 不存在", false, Action::Refresh),
            "AISC_ERR_SESSION_FAILED" => ("Session 启动失败", true, Action::Retry),
            "AISC_ERR_PROVIDER_STATUS_FAILED" => {
                ("Provider 状态检查失败", false, Action::None)
            }
            "AISC_ERR_STATE_LOCK_TIMEOUT" => {
                ("另一个操作正在更新 Runtime 状态", true, Action::Retry)
            }
            "AISC_ERR_SCOPE_INVALID" => ("Runtime scope 无效", false, Action::None),
            "AISC_ERR_NETWORK_INVALID" => ("network 配置无效", false, Action::None),
            "AISC_ERR_WORKSPACE_INVALID" => {
                ("workspace 路径不可读写", false, Action::ChooseWorkspace)
            }
            "AISC_ERR_INVALID_AGENT" => ("agent 类型无效", false, Action::None),
            "AISC_ERR_INVALID_SESSION_ID" => {
                ("session ID 非 UUID v4", false, Action::None)
            }
            "AISC_ERR_INVALID_RUNTIME_ID" => {
                ("runtime ID 非 UUID v4", false, Action::None)
            }
            "AISC_ERR_DOCKER_UNAVAILABLE" => ("Docker 尚未可用", true, Action::Retry),
            "AISC_ERR_PERMISSION_DENIED" => {
                ("AISC 无法访问 Docker 或工作区", false, Action::None)
            }
            "AISC_ERR_IMAGE_NOT_FOUND" => ("所选镜像不存在", false, Action::BuildImage),
            _ => ("AISC CLI 返回错误", true, Action::Retry),
        };
        Self::new(code, message, retryable, action)
    }
}

/// Redact likely-secret material from a stderr/technical blob before it enters
/// `technical_detail`. Defense-in-depth: the CLI is designed not to leak, this
/// only catches accidental env-var dumps and token shapes.
pub fn redact(input: &str) -> String {
    const MAX: usize = 4096;
    let (body, truncated) = truncate_char_safe(input, MAX);

    let mut out = String::with_capacity(body.len());
    for line in body.lines() {
        out.push_str(&redact_line(line));
        out.push('\n');
    }
    if truncated {
        out.push_str("…<truncated>");
    } else if out.ends_with('\n') {
        out.pop();
    }
    out
}

fn truncate_char_safe(s: &str, max: usize) -> (&str, bool) {
    if s.len() <= max {
        return (s, false);
    }
    let mut end = max;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    (&s[..end], true)
}

const SECRET_KEY_HINTS: &[&str] = &[
    "key", "token", "secret", "password", "passwd", "cookie", "auth", "credential",
];

fn redact_line(line: &str) -> String {
    let bytes = line.as_bytes();
    let mut out = String::with_capacity(line.len());
    let mut i = 0;
    let mut verbatim_from = 0;
    macro_rules! flush_verbatim {
        () => {
            if i > verbatim_from {
                out.push_str(&line[verbatim_from..i]);
            }
        };
    }
    while i < bytes.len() {
        // `sk-…` style long tokens (Anthropic/OpenAI keys). Checked before the
        // ident branch so the leading 's' is not swallowed as an identifier.
        if bytes[i] == b's' && i + 3 <= bytes.len() && &bytes[i..i + 3] == b"sk-" {
            let mut j = i + 3;
            while j < bytes.len() && is_token_char(bytes[j]) {
                j += 1;
            }
            if j - i > 12 {
                flush_verbatim!();
                out.push_str("sk-<redacted>");
                i = j;
                verbatim_from = i;
                continue;
            }
        }
        // env-like `IDENT=VALUE`: redact value when IDENT looks like a secret.
        if bytes[i].is_ascii_alphabetic() || bytes[i] == b'_' {
            let id_start = i;
            while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                i += 1;
            }
            if i < bytes.len() && bytes[i] == b'=' {
                let ident = &line[id_start..i];
                let id_lower = ident.to_ascii_lowercase();
                if SECRET_KEY_HINTS.iter().any(|h| id_lower.contains(h)) {
                    flush_verbatim!();
                    out.push_str(ident);
                    out.push_str("=<redacted>");
                    i += 1; // skip '='
                    while i < bytes.len() && !bytes[i].is_ascii_whitespace() {
                        i += 1;
                    }
                    verbatim_from = i;
                    continue;
                }
            }
            // Not a secret env pair: leave the identifier in the verbatim run.
            continue;
        }
        i += 1;
    }
    flush_verbatim!();
    out
}

fn is_token_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'-' || b == b'_'
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn map_known_codes_route_action() {
        assert_eq!(
            WorkbenchError::map_aisc("AISC_ERR_CAPABILITY_UNSUPPORTED").action,
            Action::UpgradeCli
        );
        assert_eq!(
            WorkbenchError::map_aisc("AISC_ERR_RUNTIME_CONFLICT").action,
            Action::None
        );
        assert_eq!(
            WorkbenchError::map_aisc("AISC_ERR_WORKSPACE_INVALID").action,
            Action::ChooseWorkspace
        );
        assert_eq!(
            WorkbenchError::map_aisc("AISC_ERR_IMAGE_NOT_FOUND").action,
            Action::BuildImage
        );
        assert_eq!(
            WorkbenchError::map_aisc("AISC_ERR_STATE_LOCK_TIMEOUT").action,
            Action::Retry
        );
        assert!(!WorkbenchError::map_aisc("AISC_ERR_SCOPE_INVALID").retryable);
        assert!(WorkbenchError::map_aisc("AISC_ERR_RUNTIME_NOT_READY").retryable);
    }

    #[test]
    fn map_unknown_code_is_retryable_and_carries_code() {
        let e = WorkbenchError::map_aisc("AISC_ERR_SOMETHING_NEW");
        assert_eq!(e.code, "AISC_ERR_SOMETHING_NEW");
        assert!(e.retryable);
        assert_eq!(e.action, Action::Retry);
    }

    #[test]
    fn transport_errors_have_distinct_codes() {
        assert_eq!(WorkbenchError::cli_not_found().code, "WB_ERR_CLI_NOT_FOUND");
        assert_eq!(WorkbenchError::cli_timeout().action, Action::Retry);
        assert_eq!(WorkbenchError::cli_cancelled().action, Action::None);
        assert_eq!(WorkbenchError::cli_protocol().code, "WB_ERR_CLI_PROTOCOL");
        assert_eq!(
            WorkbenchError::capability_unsupported().code,
            "WB_ERR_CAPABILITY_UNSUPPORTED"
        );
    }

    #[test]
    fn redact_env_var_secret() {
        let s = "ANTHROPIC_API_KEY=sk-ant-abc123def456 ANTHROPIC_AUTH_TOKEN=xyz";
        let r = redact(s);
        assert!(!r.contains("sk-ant-abc123def456"));
        assert!(!r.contains("xyz"));
        assert!(r.contains("ANTHROPIC_API_KEY=<redacted>"));
        assert!(r.contains("ANTHROPIC_AUTH_TOKEN=<redacted>"));
    }

    #[test]
    fn redact_keeps_non_secret_env() {
        let r = redact("PATH=/usr/bin:/bin HOME=/home/user");
        assert!(r.contains("PATH=/usr/bin:/bin"));
        assert!(r.contains("HOME=/home/user"));
    }

    #[test]
    fn redact_truncates_long_input() {
        let s = "X".repeat(10_000);
        let r = redact(&s);
        assert!(r.len() < 5000, "redact output must be bounded, got {}", r.len());
        assert!(r.ends_with("<truncated>"));
    }

    #[test]
    fn redact_sk_token_inline() {
        let r = redact("token: sk-ant-verylongtokenvalue123");
        assert!(r.contains("sk-<redacted>"));
        assert!(!r.contains("verylongtokenvalue123"));
    }
}
