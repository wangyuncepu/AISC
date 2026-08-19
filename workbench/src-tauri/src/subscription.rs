//! 挂账①: fingerprint-walled subscription downloads (Rust transport).
//!
//! Some airports TLS-kill non-whitelisted client stacks (curl/schannel,
//! openssl, Python urllib, .NET …). clash-family apps (clash-verge &co.)
//! fetch with reqwest+rustls + clash UA, so walled sources that whitelist
//! the clash family pass THIS module's exact stack shape while killing the
//! CLI's Python urllib fallback. Live matrix (2026-08-19, user's airport
//! 103.14.76.98): source hardened beyond that — every stack including
//! clash-verge itself and Chrome dies (its own logs show all three update
//! stages failing), while the same airport's domain-fronted endpoint
//! (plain HTTP) passes every stack. On download failure the caller falls
//! back to the Python transport, then the UI's paste-import path.
//!
//! This module downloads with the clash-family UA, captures the
//! `subscription-userinfo` header, then hands body+header to the CLI's
//! `network subscription store-downloaded` so ALL persistence/parsing
//! stays in the Python layer (single source of truth: snapshot, masking,
//! node-name fallback).
//!
//! Proxy note: walled sources are typically refused direct — the request
//! must ride the user's system proxy (clash-family tools register it in
//! WinINET, which reqwest does not read on its own), so the WinINET
//! registry is probed explicitly, with env vars taking precedence.

use std::time::Duration;

use base64::Engine;
use serde_json::Value;

use crate::cli::run_control_input;
use crate::error::WorkbenchError;
use crate::session::resolve_cli;

/// The clash-family UA the whole subscription plane already uses — providers
/// gate payload format on it.
pub const SUBSCRIPTION_UA: &str = "clash-verge/v2.2.0 (aisc)";

const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_BODY_BYTES: usize = 10 * 1024 * 1024;

pub(crate) struct DownloadedSubscription {
    pub body: Vec<u8>,
    pub userinfo: Option<String>,
}

/// Parse a WinINET `ProxyServer` value into an http proxy URL. Accepts both
/// the plain `host:port` form and the per-protocol `http=…;https=…` form
/// (https wins for our https-only fetch; falls back to http's host:port).
pub(crate) fn parse_wininet_proxy_server(raw: &str) -> Option<String> {
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    let chosen = if !raw.contains('=') {
        raw.to_string()
    } else {
        let mut https: Option<String> = None;
        let mut http: Option<String> = None;
        for part in raw.split(';') {
            // Malformed segments (e.g. a trailing ";") must not discard an
            // otherwise-readable proxy.
            let Some((k, v)) = part.split_once('=') else {
                continue;
            };
            let v = v.trim();
            match k.trim().to_ascii_lowercase().as_str() {
                "https" => https = Some(v.to_string()),
                "http" => http = Some(v.to_string()),
                _ => {}
            }
        }
        https.or(http)?
    };
    if chosen.contains("://") {
        Some(chosen)
    } else {
        Some(format!("http://{chosen}"))
    }
}

/// The system http(s) proxy for the downloader: env vars first (explicit
/// user override), then the WinINET registry clash-style tools write.
pub(crate) fn system_http_proxy() -> Option<String> {
    for var in ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"] {
        if let Ok(v) = std::env::var(var) {
            if !v.trim().is_empty() {
                return Some(v);
            }
        }
    }
    #[cfg(windows)]
    {
        use winreg::enums::HKEY_CURRENT_USER;
        use winreg::RegKey;
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        let settings = hkcu
            .open_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings")
            .ok()?;
        let enabled: u32 = settings.get_value("ProxyEnable").ok()?;
        if enabled != 1 {
            return None;
        }
        let server: String = settings.get_value("ProxyServer").ok()?;
        return parse_wininet_proxy_server(&server);
    }
    #[cfg(not(windows))]
    None
}

/// Flatten an error with its cause chain — reqwest's top-level message alone
/// ("error sending request for url …") hides whether the failure is proxy
/// connect, TLS, or read.
fn err_chain(e: &dyn std::error::Error) -> String {
    let mut s = e.to_string();
    let mut src = std::error::Error::source(e);
    while let Some(x) = src {
        s.push_str(&format!(": {x}"));
        src = std::error::Error::source(x);
    }
    s
}

/// Download the subscription (30s timeout, one retry on transient failures).
/// `danger_accept_invalid_certs`: IP-hosted airports almost universally ship
/// self-signed certs; the payload is node-list data persisted by the Python
/// layer (documented tradeoff, mirrors clash-verge's lenient default).
pub(crate) async fn download(url: &str) -> Result<DownloadedSubscription, String> {
    let mut builder = reqwest::Client::builder()
        .user_agent(SUBSCRIPTION_UA)
        .timeout(DOWNLOAD_TIMEOUT)
        .danger_accept_invalid_certs(true)
        .redirect(reqwest::redirect::Policy::limited(5));
    if let Some(proxy_url) = system_http_proxy() {
        match reqwest::Proxy::all(&proxy_url) {
            Ok(proxy) => {
                builder = builder.proxy(proxy);
            }
            Err(_) => {}
        }
    }
    let client = builder.build().map_err(|e| e.to_string())?;

    let mut last_err = String::new();
    for _attempt in 0..2 {
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                if (200..300).contains(&status) {
                    let userinfo = resp
                        .headers()
                        .get("subscription-userinfo")
                        .and_then(|v| v.to_str().ok())
                        .map(|s| s.to_string());
                    let body = resp.bytes().await.map_err(|e| e.to_string())?;
                    if body.is_empty() {
                        return Err("subscription source returned an empty body".into());
                    }
                    if body.len() > MAX_BODY_BYTES {
                        return Err(format!("subscription body exceeds {} bytes", MAX_BODY_BYTES));
                    }
                    return Ok(DownloadedSubscription {
                        body: body.to_vec(),
                        userinfo,
                    });
                }
                last_err = format!("HTTP {status}");
                if (400..500).contains(&status) {
                    break; // deterministic — no retry
                }
            }
            Err(e) => last_err = err_chain(&e),
        }
    }
    Err(last_err)
}

/// Persist a Rust-side download through the CLI's store-downloaded op
/// (all persistence/parsing lives in Python). Returns the CLI envelope data
/// (the secret-free snapshot).
pub(crate) async fn store_downloaded(
    app: &tauri::AppHandle,
    url: &str,
    dl: DownloadedSubscription,
) -> Result<Value, WorkbenchError> {
    let pin = resolve_cli(app).await?;
    let payload = serde_json::json!({
        "url": url,
        "content_b64": base64::engine::general_purpose::STANDARD.encode(&dl.body),
        "userinfo": dl.userinfo,
    });
    let argv = vec![
        "network".into(),
        "subscription".into(),
        "store-downloaded".into(),
        "--format".into(),
        "json".into(),
    ];
    let env = run_control_input(
        &pin,
        argv,
        payload.to_string(),
        Duration::from_secs(30),
        tokio_util::sync::CancellationToken::new(),
    )
    .await?;
    if let Some(err) = env.errors.first() {
        let mut wb = WorkbenchError::map_aisc(&err.code);
        if err.code.starts_with("AISC_ERR_NETWORK_SUBSCRIPTION_") {
            wb.message = err.message.clone();
            wb.retryable = false;
        }
        return Err(wb.with_detail(err.message.clone()));
    }
    Ok(env.data.unwrap_or(Value::Null))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wininet_proxy_forms() {
        assert_eq!(
            parse_wininet_proxy_server("127.0.0.1:7890"),
            Some("http://127.0.0.1:7890".into())
        );
        assert_eq!(
            parse_wininet_proxy_server("http=127.0.0.1:7890;https=127.0.0.1:7891"),
            Some("http://127.0.0.1:7891".into())
        );
        assert_eq!(
            parse_wininet_proxy_server("ftp=x:1;http=y:2"),
            Some("http://y:2".into())
        );
        assert_eq!(parse_wininet_proxy_server("  "), None);
        assert_eq!(
            parse_wininet_proxy_server("http://proxy.example:8080"),
            Some("http://proxy.example:8080".into())
        );
    }
}
