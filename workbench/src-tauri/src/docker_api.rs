//! PERF P6a (D-13): minimal Docker Engine HTTP client over the raw
//! transport (Windows named pipe / unix socket), plus the light snapshot
//! assembly for the steady-state poll path — ZERO aisc.exe / docker.exe
//! spawns per tick (P1+P4 remain the fallback path: any failure here falls
//! back to the merged CLI `runtime status`).
//!
//! Transport facts (env.rs KI-6 precedent): the engine speaks HTTP/1.1 over
//! `\\.\pipe\docker_engine` (Docker Desktop) or `/var/run/docker.sock`
//! (native); `Connection: close` terminates the body by EOF, so no
//! content-length parsing is needed.

use serde_json::Value;

use crate::error::WorkbenchError;

const REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(4);

/// Percent-encode a query component (RFC 3986 unreserved only).
fn percent_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// `/containers/json?all=1&filters={"label":["io.aisc.runtime-id=<rid>"]}`
pub fn containers_by_runtime_url(runtime_id: &str) -> String {
    let filters = format!(r#"{{"label":["io.aisc.runtime-id={runtime_id}"]}}"#);
    format!(
        "/containers/json?all=1&filters={}",
        percent_encode(&filters)
    )
}

/// Split a raw HTTP response into (status_code, body). `Connection: close`
/// means the read side ran to EOF, so the body is everything after the
/// header terminator.
pub fn parse_http_response(raw: &str) -> Option<(u16, &str)> {
    let (head, body) = raw.split_once("\r\n\r\n")?;
    let status_line = head.lines().next()?;
    // "HTTP/1.1 200 OK"
    let code = status_line.split(' ').nth(1)?;
    let code: u16 = code.parse().ok()?;
    Some((code, body))
}

/// Parse `/containers/json` output filtered to one runtime id →
/// `(container_name, short_id, docker_state)`; `None` = no match.
pub fn parse_containers_json(body: &str) -> Option<(String, String, &'static str)> {
    let arr: Vec<Value> = serde_json::from_str(body).ok()?;
    let first = arr.first()?;
    let id = first["Id"].as_str()?;
    let name = first["Names"][0].as_str().unwrap_or("").trim_start_matches('/');
    let running = first["State"].as_str() == Some("running");
    Some((
        name.to_string(),
        id.chars().take(12).collect(),
        if running { "running" } else { "stopped" },
    ))
}

// ---------------------------------------------------------------------------
// Raw transport (Windows named pipe / unix socket)
// ---------------------------------------------------------------------------

async fn raw_get(path: &str) -> Result<String, String> {
    #[cfg(windows)]
    {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::windows::named_pipe::ClientOptions;
        let mut client = ClientOptions::new()
            .open(r"\\.\pipe\docker_engine")
            .map_err(|e| format!("pipe open: {e}"))?;
        let req = format!(
            "GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"
        );
        client
            .write_all(req.as_bytes())
            .await
            .map_err(|e| format!("pipe write: {e}"))?;
        let mut buf = Vec::new();
        tokio::time::timeout(REQUEST_TIMEOUT, client.read_to_end(&mut buf))
            .await
            .map_err(|_| "engine request timed out".to_string())?
            .map_err(|e| format!("pipe read: {e}"))?;
        Ok(String::from_utf8_lossy(&buf).into_owned())
    }
    #[cfg(not(windows))]
    {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let mut stream = tokio::net::UnixStream::connect("/var/run/docker.sock")
            .await
            .map_err(|e| format!("socket connect: {e}"))?;
        let req = format!(
            "GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"
        );
        stream
            .write_all(req.as_bytes())
            .await
            .map_err(|e| format!("socket write: {e}"))?;
        let mut buf = Vec::new();
        tokio::time::timeout(REQUEST_TIMEOUT, stream.read_to_end(&mut buf))
            .await
            .map_err(|_| "engine request timed out".to_string())?
            .map_err(|e| format!("socket read: {e}"))?;
        Ok(String::from_utf8_lossy(&buf).into_owned())
    }
}

/// One GET; `Err` on transport trouble, non-200 mapped to `Err` too (the
/// caller falls back to the CLI path — a partial success would be worse).
pub async fn engine_get(path: &str) -> Result<String, String> {
    let raw = raw_get(path).await?;
    match parse_http_response(&raw) {
        Some((200, body)) => Ok(body.to_string()),
        Some((code, _)) => Err(format!("engine returned {code}")),
        None => Err("malformed engine response".into()),
    }
}

// ---------------------------------------------------------------------------
// Light snapshot assembly (pure; the transport only feeds it)
// ---------------------------------------------------------------------------

/// Read the container registry entry (`containers.json` in the workspace
/// state dir) for one runtime id → the meta object, or None.
pub fn registry_entry_for(
    registry_json: &str,
    runtime_id: &str,
) -> Option<Value> {
    let root: Value = serde_json::from_str(registry_json).ok()?;
    let containers = root["containers"].as_object()?;
    containers
        .values()
        .find(|e| e["runtime_id"].as_str() == Some(runtime_id))
        .cloned()
}

/// The registry's `containers.json` path for a workspace.
pub fn registry_file_for(
    root: &crate::data_root::ResolvedDataRoot,
) -> std::path::PathBuf {
    root.workspace_dir().join("containers.json")
}

fn now_iso_utc() -> String {
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = d.as_secs() as i64;
    let days = secs.div_euclid(86_400);
    let sod = secs.rem_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let dd = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{y:04}-{m:02}-{dd:02}T{:02}:{:02}:{:02}Z",
        sod / 3600,
        (sod % 3600) / 60,
        sod % 60
    )
}

/// Assemble the light RuntimeSnapshot payload. Docker-unavailable parity
/// with `inspect_runtime` (unknown + stale + registry unknown). web_access
/// is deliberately absent — the store's light apply preserves the last full
/// observation's gateway fields (TS type marks it optional/legacy-absent).
pub fn light_snapshot(
    runtime_id: &str,
    registry_json: Option<&str>,
    docker: Option<(String, String, &'static str)>, // (name, short_id, state)
) -> Value {
    let observed_at = now_iso_utc();
    let entry = registry_json.and_then(|j| registry_entry_for(j, runtime_id));

    let (state, container_name, container_id, registry_state) = match (&docker, &entry) {
        (Some((n, id, st)), _) => (
            *st,
            n.clone(),
            id.clone(),
            if entry.is_some() { "registered" } else { "missing" },
        ),
        (None, Some(e)) => (
            // Docker shows nothing but the registry does: the CLI path
            // distinguishes not_found (registry entry dead too) from
            // stopped — the light path cannot tell, report stopped and let
            // the periodic full refresh settle the nuance.
            "stopped",
            e["container_id"].as_str().unwrap_or("").to_string(),
            {
                let cid = e["container_id"].as_str().unwrap_or("");
                cid.chars().take(12).collect()
            },
            "registered",
        ),
        (None, None) => ("not_found", String::new(), String::new(), "not_found"),
    };

    let e = entry.unwrap_or(Value::Null);
    serde_json::json!({
        "runtime_id": runtime_id,
        "state": state,
        "config": {
            "workspace": e["workspace"].as_str().unwrap_or(""),
            "image": e["image"].as_str().unwrap_or(""),
            "network": e["network"].as_str().unwrap_or("direct"),
            "scope": e["scope"].as_str().unwrap_or("project"),
        },
        "owner": e["owner"].as_str().unwrap_or(""),
        "config_fingerprint": e["config_fingerprint"].as_str().unwrap_or(""),
        "container_name": container_name,
        "container_id": container_id,
        "registry_state": registry_state,
        "observed_at": observed_at,
        "stale": false,
    })
}

/// `Err` = transport/parse trouble (caller falls back to the CLI path);
/// `Ok(snapshot)` with unknown+stale = engine genuinely unreachable —
/// a valid observation, same as the CLI path produces.
pub async fn poll_light(
    workspace: &std::path::Path,
    runtime_id: &str,
) -> Result<Value, WorkbenchError> {
    let url = containers_by_runtime_url(runtime_id);
    let registry_json = crate::data_root::resolve_data_root(workspace)
        .ok()
        .and_then(|root| {
            let p = registry_file_for(&root);
            std::fs::read_to_string(p).ok()
        });

    let body = match engine_get(&url).await {
        Ok(b) => b,
        Err(_) => {
            // Engine unreachable: parity with inspect_runtime's unknown.
            return Ok(serde_json::json!({
                "runtime_id": runtime_id,
                "state": "unknown",
                "config": {"workspace": "", "image": "", "network": "direct", "scope": "project"},
                "owner": "",
                "config_fingerprint": "",
                "container_name": "",
                "container_id": "",
                "registry_state": "unknown",
                "observed_at": now_iso_utc(),
                "stale": true,
            }));
        }
    };
    let docker = parse_containers_json(&body);
    Ok(light_snapshot(runtime_id, registry_json.as_deref(), docker))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_encodes_label_filter() {
        let url = containers_by_runtime_url("550e8400-e29b-41d4-a716-446655440000");
        assert!(url.starts_with("/containers/json?all=1&filters="));
        assert!(url.contains("%7B%22label%22"));
        assert!(!url.contains('{') && !url.contains('"'));
    }

    #[test]
    fn http_response_splits_status_and_body() {
        let raw = "HTTP/1.1 200 OK\r\nApi-Version: 1.44\r\n\r\n[{\"Id\":\"abc\"}]";
        let (code, body) = parse_http_response(raw).unwrap();
        assert_eq!(code, 200);
        assert_eq!(body, "[{\"Id\":\"abc\"}]");
        assert!(parse_http_response("garbage").is_none());
    }

    #[test]
    fn containers_json_parses_running_and_short_id() {
        let body = r#"[{"Id":"0123456789abcdef0123","Names":["/aisc-wb-1"],"State":"running","Labels":{"io.aisc.runtime-id":"r1"}}]"#;
        let (name, id, state) = parse_containers_json(body).unwrap();
        assert_eq!((name.as_str(), id.as_str(), state), ("aisc-wb-1", "0123456789ab", "running"));
        let stopped = body.replace("running", "exited");
        assert_eq!(parse_containers_json(&stopped).unwrap().2, "stopped");
        assert!(parse_containers_json("[]").is_none());
    }

    #[test]
    fn registry_entry_finds_by_runtime_id() {
        let reg = r#"{"default":"","containers":{"aisc-wb-1":{"runtime_id":"r1","image":"super-claude:latest","workspace":"/w","network":"direct","scope":"project","owner":"workbench","config_fingerprint":"sha256:x","container_id":"0123456789abcdef"},"other":{"runtime_id":"r2"}}}"#;
        let e = registry_entry_for(reg, "r1").unwrap();
        assert_eq!(e["image"], "super-claude:latest");
        assert!(registry_entry_for(reg, "zzz").is_none());
    }

    #[test]
    fn light_snapshot_shapes_docker_and_registry_missing() {
        // Docker sees it, registry too → registered/running
        let reg = r#"{"containers":{"c":{"runtime_id":"r1","image":"i","workspace":"/w","network":"direct","scope":"project","owner":"o","config_fingerprint":"f","container_id":"cid1234567890"}}}"#;
        let snap = light_snapshot("r1", Some(reg), Some(("aisc-wb-1".into(), "abc123".into(), "running")));
        assert_eq!(snap["state"], "running");
        assert_eq!(snap["registry_state"], "registered");
        assert_eq!(snap["config"]["image"], "i");
        assert!(snap.get("web_access").is_none(), "light omits gateway");

        // Docker-only → registry_state missing (parity with inspect)
        let snap = light_snapshot("r1", None, Some(("x".into(), "y".into(), "stopped")));
        assert_eq!(snap["registry_state"], "missing");

        // Neither → not_found
        let snap = light_snapshot("r1", None, None);
        assert_eq!(snap["state"], "not_found");
    }
}
