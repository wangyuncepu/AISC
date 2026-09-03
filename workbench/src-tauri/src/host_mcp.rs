//! Host-tools MCP server (F2, D-10): the FIRST local listening service in
//! the Workbench backend.
//!
//! Container agents (claude/codex, root + skip-permissions) reach the HOST
//! through `http://host.docker.internal:<port>/mcp` (channel proven by the
//! T-F2a PoC). Every defense is server-side:
//!
//! - **Token auth**: a random per-process token; requests without a matching
//!   `Authorization: Bearer` are refused. The token does travel into the
//!   container (env injection, T-F2c) — the standing threat model accepts
//!   "the container IS the highest-privilege subject"; the token's job is
//!   stopping OTHER local processes from driving the executor.
//! - **Program whitelist**: default EMPTY = the tool set is empty and every
//!   call is refused. An entry = exact program path + optional read-only
//!   preset (subcommand allowlist, e.g. git status/log/diff).
//! - **cwd pinned** to the active workspace (optional relative subpath,
//!   containment-checked — never `..`, never absolute).
//! - **Budgets**: 60s timeout (kill), 256 KiB per stream with a truncation
//!   flag, 4 concurrent execs.
//! - Bound listens: `127.0.0.1` only (the Docker Desktop backend proxies the
//!   container's traffic to the host loopback — T-F2a).

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;

use crate::logging;

/// One whitelist entry (settings `host_tools` section, T-F2d renders it).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HostToolEntry {
    pub name: String,
    /// Exact program path — the exec argv[0] must equal this.
    pub program: String,
    /// Optional read-only preset. Only "git-ro" exists today: the first
    /// subcommand must be one of the read-only git verbs.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub read_only_preset: Option<String>,
}

pub const GIT_RO_PRESET: &str = "git-ro";
const READ_ONLY_GIT_VERBS: [&str; 5] = ["status", "log", "diff", "show", "branch"];

/// Per-stream output budget; beyond it the stream is truncated and flagged.
const OUTPUT_LIMIT: usize = 256 * 1024;
/// Hard wall-clock budget per exec; the child is killed at the deadline.
const EXEC_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(60);
/// Concurrent exec ceiling.
const MAX_CONCURRENT: usize = 4;
/// Request-body ceiling (the JSON-RPC envelope; args lists stay small).
const BODY_LIMIT: usize = 4 * 1024 * 1024;

pub struct HostMcpState {
    token: String,
    port: Mutex<Option<u16>>,
    workspace: Mutex<Option<PathBuf>>,
    whitelist: Mutex<Vec<HostToolEntry>>,
    cancel: CancellationToken,
    permits: Semaphore,
}

impl Default for HostMcpState {
    fn default() -> Self {
        Self::new()
    }
}

impl HostMcpState {
    pub fn new() -> Self {
        Self {
            token: uuid::Uuid::new_v4().simple().to_string(),
            port: Mutex::new(None),
            workspace: Mutex::new(None),
            whitelist: Mutex::new(Vec::new()),
            cancel: CancellationToken::new(),
            permits: Semaphore::new(MAX_CONCURRENT),
        }
    }

    pub fn port(&self) -> Option<u16> {
        *self.port.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// T-F2c: the raw token (rides the CLI argv into the container env;
    /// never logged).
    pub fn token(&self) -> String {
        self.token.clone()
    }

    pub fn set_workspace(&self, path: Option<PathBuf>) {
        *self.workspace.lock().unwrap_or_else(|p| p.into_inner()) = path;
    }

    pub fn workspace(&self) -> Option<PathBuf> {
        self.workspace.lock().unwrap_or_else(|p| p.into_inner()).clone()
    }

    /// Replace the whitelist (called when settings load/save; empty = the
    /// tool set is empty and every call is refused).
    pub fn set_whitelist(&self, entries: Vec<HostToolEntry>) {
        *self.whitelist.lock().unwrap_or_else(|p| p.into_inner()) = entries;
    }

    pub fn whitelist(&self) -> Vec<HostToolEntry> {
        self.whitelist.lock().unwrap_or_else(|p| p.into_inner()).clone()
    }
}

/// Bind `127.0.0.1:0`, record the port, serve until cancelled. Called once
/// from the Tauri setup hook; failures degrade to "no endpoint" (the app
/// itself never depends on this service).
pub async fn serve(state: std::sync::Arc<HostMcpState>) {
    let listener = match TcpListener::bind(("127.0.0.1", 0)).await {
        Ok(l) => l,
        Err(e) => {
            logging::append_event("error", "host_mcp", "bind_failed", None,
                                  json!({ "error": e.to_string() }));
            return;
        }
    };
    let port = listener.local_addr().map(|a| a.port()).ok();
    if let Some(p) = port {
        *state.port.lock().unwrap_or_else(|p| p.into_inner()) = Some(p);
    }
    logging::append_event("info", "host_mcp", "listening", None,
                          json!({ "port": port, "tools": state.whitelist().len() }));
    loop {
        tokio::select! {
            _ = state.cancel.cancelled() => break,
            accepted = listener.accept() => {
                let (stream, _peer) = match accepted {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let st = state.clone();
                tokio::spawn(async move {
                    if let Err(e) = handle_connection(stream, st).await {
                        let _ = e;
                    }
                });
            }
        }
    }
}

/// Minimal HTTP/1.1: one request per connection (Connection: close). The MCP
/// streamable-http clients we target (claude/codex) send keep-alive but
/// handle close fine for a stateless server.
async fn handle_connection(
    mut stream: TcpStream, state: std::sync::Arc<HostMcpState>,
) -> std::io::Result<()> {
    let mut buf: Vec<u8> = Vec::with_capacity(4096);
    let mut chunk = [0u8; 4096];
    // headers end
    let header_end = loop {
        if let Some(i) = find_header_end(&buf) {
            break i;
        }
        if buf.len() > 64 * 1024 {
            respond(&mut stream, 431, "{\"error\":\"headers too large\"}").await?;
            return Ok(());
        }
        let n = tokio::select! {
            r = stream.read(&mut chunk) => r?,
            _ = state.cancel.cancelled() => return Ok(()),
        };
        if n == 0 {
            return Ok(());
        }
        buf.extend_from_slice(&chunk[..n]);
    };

    let head = String::from_utf8_lossy(&buf[..header_end]).to_string();
    let mut lines = head.split("\r\n");
    let request_line = lines.next().unwrap_or_default().to_string();
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_string();
    let raw_path = parts.next().unwrap_or_default().to_string();
    // T-F2c: both auth shapes are accepted — the Authorization header and a
    // `?token=` query param (MCP client URL injection: claude/codex register
    // a plain URL; header support differs across client versions). The token
    // only ever travels into the container (accepted threat model).
    let (path, query) = raw_path.split_once('?').unwrap_or((raw_path.as_str(), ""));
    let query_token = query.split('&').find_map(|kv| {
        let (k, v) = kv.split_once('=')?;
        (k == "token").then(|| v.to_string())
    }).unwrap_or_default();
    let mut content_length: usize = 0;
    let mut auth_ok = false;
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            let k = k.trim().to_ascii_lowercase();
            let v = v.trim();
            if k == "content-length" {
                content_length = v.parse().unwrap_or(0);
            } else if k == "authorization" {
                auth_ok = v == format!("Bearer {}", state.token);
            }
        }
    }

    if method != "POST" || path != "/mcp" {
        respond(&mut stream, 404, "{\"error\":\"not found\"}").await?;
        return Ok(());
    }
    if !auth_ok && query_token != state.token {
        respond(&mut stream, 401, "{\"error\":\"unauthorized\"}").await?;
        return Ok(());
    }
    if content_length > BODY_LIMIT {
        respond(&mut stream, 413, "{\"error\":\"body too large\"}").await?;
        return Ok(());
    }

    // body (may already be partially buffered)
    let mut body: Vec<u8> = buf[header_end + 4..].to_vec();
    while body.len() < content_length {
        let n = tokio::select! {
            r = stream.read(&mut chunk) => r?,
            _ = state.cancel.cancelled() => return Ok(()),
        };
        if n == 0 {
            break;
        }
        body.extend_from_slice(&chunk[..n]);
    }
    body.truncate(content_length);

    let parsed: Value = match serde_json::from_slice(&body) {
        Ok(v) => v,
        Err(_) => {
            respond(&mut stream, 400, "{\"error\":\"invalid json\"}").await?;
            return Ok(());
        }
    };

    // JSON-RPC notification (no "id") -> 202, no body.
    if parsed.get("id").is_none() {
        respond_status_only(&mut stream, 202).await?;
        return Ok(());
    }

    let result = dispatch(&parsed, &state).await;
    let payload = serde_json::to_string(&result.unwrap_or_else(|| json!({ "jsonrpc": "2.0", "id": parsed.get("id").cloned().unwrap_or(Value::Null), "result": {} })))
        .unwrap_or_else(|_| "{\"error\":\"encode\"}".to_string());
    respond(&mut stream, 200, &payload).await?;
    Ok(())
}

/// JSON-RPC method dispatch. Always answers a RESPONSE object (errors ride
/// as JSON-RPC errors, never HTTP 5xx — the agent surfaces them as text).
async fn dispatch(req: &Value, state: &std::sync::Arc<HostMcpState>) -> Option<Value> {
    let id = req.get("id").cloned().unwrap_or(Value::Null);
    let method = req.get("method").and_then(Value::as_str).unwrap_or_default();
    let params = req.get("params").cloned().unwrap_or(json!({}));

    let (result_or_error, is_error) = match method {
        "initialize" => {
            // Echo the client's protocolVersion when present (MCP spec:
            // respond with the version you speak; both 2024-11-05 and
            // 2025-03-26 shapes are served by the same stateless JSON).
            let ver = params.get("protocolVersion").and_then(Value::as_str)
                .unwrap_or("2024-11-05").to_string();
            (json!({
                "protocolVersion": ver,
                "capabilities": { "tools": {} },
                "serverInfo": { "name": "aisc-host", "version": "1.0.0" },
            }), false)
        }
        "ping" => (json!({}), false),
        "tools/list" => (json!({
            "tools": [
                {
                    "name": "host_tools_list",
                    "description": "List the host tool programs the Workbench user has whitelisted (with their read-only preset, if any). Zero-entry = host exec is disabled.",
                    "inputSchema": { "type": "object", "properties": {}, "additionalProperties": false },
                },
                {
                    "name": "host_exec",
                    "description": "Run a whitelisted host program. cwd is pinned to the active workspace (an optional relative subpath is allowed). Returns exit code, stdout, stderr.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "program": { "type": "string", "description": "Exact whitelisted program path" },
                            "args": { "type": "array", "items": { "type": "string" }, "default": [] },
                            "cwd_workspace_relative": { "type": "string", "description": "Optional workspace-relative subdirectory" },
                        },
                        "required": ["program"],
                        "additionalProperties": false,
                    },
                },
            ],
        }), false),
        "tools/call" => {
            let name = params.get("name").and_then(Value::as_str).unwrap_or_default();
            let args = params.get("arguments").cloned().unwrap_or(json!({}));
            match name {
                "host_tools_list" => (host_tools_list(state), false),
                "host_exec" => {
                    let r = host_exec(state, &args).await;
                    // tool errors are CONTENT (isError) so the agent reads them
                    let is_err = r.get("isError").and_then(Value::as_bool).unwrap_or(false);
                    (json!({ "content": [ { "type": "text", "text": r.to_string() } ], "isError": is_err }), false)
                }
                _ => (json!({ "code": -32602, "message": format!("unknown tool: {name}") }), true)
            }
        }
        _ => (json!({ "code": -32601, "message": format!("method not found: {method}") }), true),
    };

    let body = if is_error {
        json!({ "jsonrpc": "2.0", "id": id, "error": result_or_error })
    } else {
        json!({ "jsonrpc": "2.0", "id": id, "result": result_or_error })
    };
    Some(body)
}

fn host_tools_list(state: &std::sync::Arc<HostMcpState>) -> Value {
    Value::String(serde_json::to_string(&state.whitelist()).unwrap_or_default())
}

/// Whitelist + preset + cwd containment + budgets. Never panics; every
/// refusal is a structured JSON object the agent can read.
async fn host_exec(state: &std::sync::Arc<HostMcpState>, args: &Value) -> Value {
    let program = args.get("program").and_then(Value::as_str).unwrap_or_default().to_string();
    let argv: Vec<String> = args.get("args").and_then(Value::as_array).map(|a| {
        a.iter().filter_map(|v| v.as_str().map(String::from)).collect()
    }).unwrap_or_default();
    let cwd_rel = args.get("cwd_workspace_relative").and_then(Value::as_str)
        .unwrap_or_default().to_string();

    let whitelist = state.whitelist();
    let entry = whitelist.iter().find(|e| e.program == program);
    let Some(entry) = entry else {
        return json!({
            "isError": true,
            "error": format!("program not whitelisted: {program:?} — ask the user to add it in Workbench settings (host tools)"),
        });
    };
    if let Some(err) = check_read_only(entry, &argv) {
        return json!({ "isError": true, "error": err });
    }
    let Some(workspace) = state.workspace() else {
        return json!({ "isError": true, "error": "no active workspace on the host side" });
    };
    let cwd = match resolve_cwd(&workspace, &cwd_rel) {
        Ok(c) => c,
        Err(e) => return json!({ "isError": true, "error": e }),
    };

    // Budgets: concurrency gate, then the timed spawn.
    let permit = match state.permits.acquire().await {
        Ok(p) => p,
        Err(_) => return json!({ "isError": true, "error": "executor closed" }),
    };
    let started = std::time::Instant::now();
    let mut cmd = tokio::process::Command::new(&entry.program);
    cmd.args(&argv)
        .current_dir(&cwd)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        // Never flash a console window from a GUI app.
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return json!({ "isError": true, "error": format!("spawn {}: {e}", entry.program) }),
    };
    let mut out_pipe = child.stdout.take();
    let mut err_pipe = child.stderr.take();
    let out_task = tokio::spawn(async move { read_capped(&mut out_pipe).await });
    let err_task = tokio::spawn(async move { read_capped(&mut err_pipe).await });
    let status = tokio::select! {
        s = child.wait() => s,
        _ = tokio::time::sleep(EXEC_TIMEOUT) => {
            let _ = child.start_kill();
            let _ = child.wait().await;
            return json!({
                "isError": true,
                "error": format!("timed out after {}s", EXEC_TIMEOUT.as_secs()),
            });
        }
    };
    let (out, out_trunc) = out_task.await.unwrap_or((Vec::new(), false));
    let (err, err_trunc) = err_task.await.unwrap_or((Vec::new(), false));
    drop(permit);
    let exit_code = status.ok().and_then(|s| s.code()).unwrap_or(-1);

    logging::append_event("info", "host_mcp", "host_exec", None,
                          json!({ "program": entry.program, "exit": exit_code,
                                  "duration_ms": started.elapsed().as_millis() as u64 }));

    json!({
        "exitCode": exit_code,
        "stdout": String::from_utf8_lossy(&out),
        "stdoutTruncated": out_trunc,
        "stderr": String::from_utf8_lossy(&err),
        "stderrTruncated": err_trunc,
        "durationMs": started.elapsed().as_millis() as u64,
    })
}

/// Read a pipe up to OUTPUT_LIMIT bytes; the flag marks truncation.
/// Generic over stdout/stderr child pipes.
async fn read_capped<R: tokio::io::AsyncRead + Unpin>(
    pipe: &mut Option<R>,
) -> (Vec<u8>, bool) {
    let mut data = Vec::new();
    let mut truncated = false;
    if let Some(r) = pipe.as_mut() {
        let mut chunk = [0u8; 8192];
        loop {
            match r.read(&mut chunk).await {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if data.len() + n > OUTPUT_LIMIT {
                        let take = OUTPUT_LIMIT.saturating_sub(data.len());
                        data.extend_from_slice(&chunk[..take]);
                        truncated = true;
                        break;
                    }
                    data.extend_from_slice(&chunk[..n]);
                }
            }
        }
    }
    (data, truncated)
}

/// Read-only preset enforcement. Returns Err(message) on violation.
pub fn check_read_only(entry: &HostToolEntry, argv: &[String]) -> Option<String> {
    match entry.read_only_preset.as_deref() {
        None => None,
        Some(GIT_RO_PRESET) => {
            let first = argv.first().map(String::as_str).unwrap_or_default();
            if READ_ONLY_GIT_VERBS.contains(&first) {
                None
            } else {
                Some(format!(
                    "tool {0:?} is read-only (preset git-ro): first argument must be one of {READ_ONLY_GIT_VERBS:?}, got {first:?}",
                    entry.program
                ))
            }
        }
        Some(other) => Some(format!("unknown read-only preset: {other}")),
    }
}

/// cwd containment: the base is the active workspace; a relative subpath
/// must stay inside (no `..`, no absolute, no UNC).
pub fn resolve_cwd(base: &Path, relative: &str) -> Result<PathBuf, String> {
    if relative.is_empty() {
        return Ok(base.to_path_buf());
    }
    if Path::new(relative).is_absolute() {
        return Err(format!("cwd_workspace_relative must be relative, got {relative:?}"));
    }
    let mut resolved = base.to_path_buf();
    for seg in Path::new(relative).components() {
        match seg {
            std::path::Component::Normal(s) => {
                let s = s.to_string_lossy();
                if s.contains("..") {
                    return Err("cwd_workspace_relative must not contain '..'".to_string());
                }
                resolved.push(s.as_ref());
            }
            _ => return Err(format!("cwd_workspace_relative must be a plain relative path, got {relative:?}")),
        }
    }
    Ok(resolved)
}

fn find_header_end(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

async fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK",
        202 => "Accepted",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        413 => "Payload Too Large",
        431 => "Request Header Fields Too Large",
        _ => "Error",
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.flush().await?;
    Ok(())
}

async fn respond_status_only(stream: &mut TcpStream, status: u16) -> std::io::Result<()> {
    let head = format!("HTTP/1.1 {status} Accepted\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
    stream.write_all(head.as_bytes()).await?;
    stream.flush().await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(program: &str, preset: Option<&str>) -> HostToolEntry {
        HostToolEntry {
            name: program.rsplit(['\\', '/']).next().unwrap_or(program).to_string(),
            program: program.to_string(),
            read_only_preset: preset.map(String::from),
        }
    }

    #[test]
    fn read_only_git_preset_blocks_write_verbs() {
        let e = entry(r"C:\Program Files\Git\bin\git.exe", Some(GIT_RO_PRESET));
        assert!(check_read_only(&e, &["status".into()]).is_none());
        assert!(check_read_only(&e, &["log".into(), "--oneline".into()]).is_none());
        assert!(check_read_only(&e, &["push".into(), "origin".into()]).is_some());
        assert!(check_read_only(&e, &[]).is_some());
        // no preset = unrestricted
        let free = entry("/usr/bin/git", None);
        assert!(check_read_only(&free, &["push".into()]).is_none());
    }

    #[test]
    fn cwd_containment_rejects_escape() {
        let base = Path::new(r"C:\ws");
        assert!(resolve_cwd(base, "").unwrap().eq(base));
        let sub = resolve_cwd(base, "sub/dir").unwrap();
        let names: Vec<String> = sub.components().filter_map(|c| match c {
            std::path::Component::Normal(s) => Some(s.to_string_lossy().to_string()),
            _ => None,
        }).collect();
        assert!(names.iter().any(|n| n == "sub"));
        assert!(names.iter().any(|n| n == "dir"));
        assert!(resolve_cwd(base, "..").is_err());
        assert!(resolve_cwd(base, "a/../b").is_err());
        assert!(resolve_cwd(base, r"C:\other").is_err());
        assert!(resolve_cwd(base, "/abs").is_err());
    }

    #[test]
    fn header_end_finder() {
        assert_eq!(find_header_end(b"POST /mcp HTTP/1.1\r\nA: b\r\n\r\nbody"), Some(24));
        assert_eq!(find_header_end(b"no terminator"), None);
    }

    #[tokio::test]
    async fn dispatch_initialize_and_unknown() {
        let state = std::sync::Arc::new(HostMcpState::new());
        let init = json!({ "jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": { "protocolVersion": "2025-03-26" } });
        let out = dispatch(&init, &state).await.unwrap();
        assert_eq!(out["result"]["protocolVersion"], "2025-03-26");
        assert_eq!(out["result"]["serverInfo"]["name"], "aisc-host");

        let bad = json!({ "jsonrpc": "2.0", "id": 2, "method": "no/such" });
        let out = dispatch(&bad, &state).await.unwrap();
        assert!(out.get("error").is_some());
    }

    #[tokio::test]
    async fn host_exec_refuses_unlisted_program_and_missing_workspace() {
        let state = std::sync::Arc::new(HostMcpState::new());
        // empty whitelist: everything refused
        let r = host_exec(&state, &json!({ "program": "C:/git.exe" })).await;
        assert!(r["isError"].as_bool().unwrap());
        // listed but no workspace set
        state.set_whitelist(vec![entry("C:/tools/echo.exe", None)]);
        let r = host_exec(&state, &json!({ "program": "C:/tools/echo.exe" })).await;
        assert!(r["isError"].as_bool().unwrap());
        assert!(r["error"].as_str().unwrap().contains("workspace"));
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn host_exec_runs_whitelisted_program() {
        let state = std::sync::Arc::new(HostMcpState::new());
        let dir = std::env::temp_dir();
        state.set_workspace(Some(dir.clone()));
        state.set_whitelist(vec![HostToolEntry {
            name: "cmd".into(),
            program: "cmd".into(),
            read_only_preset: None,
        }]);
        let r = host_exec(&state, &json!({
            "program": "cmd", "args": ["/c", "echo", "host_mcp_ok"]
        })).await;
        assert_eq!(r["exitCode"], 0, "body: {r}");
        assert!(r["stdout"].as_str().unwrap().contains("host_mcp_ok"));
    }

    #[cfg(not(windows))]
    #[tokio::test]
    async fn host_exec_runs_whitelisted_program() {
        let state = std::sync::Arc::new(HostMcpState::new());
        let dir = std::env::temp_dir();
        state.set_workspace(Some(dir.clone()));
        state.set_whitelist(vec![entry("/bin/echo", None)]);
        let r = host_exec(&state, &json!({ "program": "/bin/echo", "args": ["host_mcp_ok"] })).await;
        assert_eq!(r["exitCode"], 0, "body: {r}");
        assert!(r["stdout"].as_str().unwrap().contains("host_mcp_ok"));
    }

    /// Socket-level end-to-end: the real serve() loop, a real TCP connection,
    /// raw HTTP bytes. Pins the auth gate (401) and the query-token path.
    #[tokio::test]
    async fn serve_end_to_end_auth_and_tools_list() {
        let state = std::sync::Arc::new(HostMcpState::new());
        state.set_whitelist(vec![entry("C:/tools/git.exe", None)]);
        let server = tokio::spawn(serve(state.clone()));
        // wait for the port to be bound
        for _ in 0..50 {
            if state.port().is_some() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        let port = state.port().expect("server bound a port");
        let token = state.token();

        // No auth -> 401.
        let resp = raw_http(port, "POST /mcp HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}").await;
        assert!(resp.starts_with("HTTP/1.1 401"), "resp: {resp}");

        // Query token + tools/list -> 200 and our tool names.
        let body = r#"{"jsonrpc":"2.0","id":1,"method":"tools/list"}"#;
        let req = format!(
            "POST /mcp?token={token} HTTP/1.1\r\nContent-Length: {}\r\n\r\n{}",
            body.len(), body
        );
        let resp = raw_http(port, &req).await;
        assert!(resp.starts_with("HTTP/1.1 200"), "resp: {resp}");
        assert!(resp.contains("host_exec"), "resp: {resp}");

        // Full call chain: host_tools_list returns the whitelist entry.
        let body = r#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"host_tools_list","arguments":{}}}"#;
        let req = format!(
            "POST /mcp?token={token} HTTP/1.1\r\nContent-Length: {}\r\n\r\n{}",
            body.len(), body
        );
        let resp = raw_http(port, &req).await;
        assert!(resp.starts_with("HTTP/1.1 200"), "resp: {resp}");
        assert!(resp.contains("C:/tools/git.exe"), "resp: {resp}");

        server.abort();
    }

    /// Minimal blocking client: send bytes, read to EOF (Connection: close).
    async fn raw_http(port: u16, request: &str) -> String {
        use tokio::io::AsyncReadExt;
        let mut s = tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .expect("connect");
        s.write_all(request.as_bytes()).await.unwrap();
        let mut buf = Vec::new();
        s.read_to_end(&mut buf).await.unwrap_or(0);
        String::from_utf8_lossy(&buf).to_string()
    }
}
