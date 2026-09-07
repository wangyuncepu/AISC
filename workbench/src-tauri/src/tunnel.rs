//! 2.1.10 R4a: local→remote gateway port tunnels.
//!
//! A remote target's web-gateway ports (`127.0.0.1:47000..` on the REMOTE
//! machine) are unreachable from the local browser. The fix is a plain
//! `ssh -L 127.0.0.1:P:127.0.0.1:P <target> -N` forward per port — same port
//! number on both ends, so the canonical service URL
//! (`http://p<port>.localhost:<host_port>/`) opens unchanged.
//!
//! Lifecycle: one tunnel per (target, port), created on demand before the
//! opener runs, verified by a local TCP probe; ALL tunnels are torn down on
//! target switch/clear (a stale tunnel to the previous machine would shadow
//! the new one on the same port).

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::Mutex;
use std::time::Duration;

use crate::cli::SshTarget;
use crate::error::WorkbenchError;

#[derive(Default)]
pub struct TunnelRegistry(pub Mutex<HashMap<(String, u16), tokio::process::Child>>);

/// The ssh client binary — the SAME deterministic resolution CliTarget uses
/// (Windows: system OpenSSH absolute path; the GUI PATH may front Git's msys
/// ssh with pipe quirks).
pub fn ssh_program() -> std::ffi::OsString {
    #[cfg(windows)]
    {
        const SYS_SSH: &str = r"C:\Windows\System32\OpenSSH\ssh.exe";
        if std::path::Path::new(SYS_SSH).is_file() {
            return SYS_SSH.into();
        }
    }
    "ssh".into()
}

fn target_key(t: &SshTarget) -> String {
    format!("{}:{}:{:?}", t.host, t.port.unwrap_or(22), t.key_path)
}

/// Ensure a tunnel for (target, port) exists and accepts local connections.
/// Idempotent: an existing healthy tunnel is reused; a dead child is
/// replaced. Returns once the local port answers TCP (bounded wait).
pub async fn ensure_gateway_tunnel(
    registry: &TunnelRegistry,
    t: &SshTarget,
    host_port: u16,
) -> Result<(), WorkbenchError> {
    let key = (target_key(t), host_port);

    // Reuse: if the child is alive AND the port answers, done.
    {
        let mut guard = registry
            .0
            .lock()
            .map_err(|_| WorkbenchError::cli_protocol().with_detail("tunnel registry"))?;
        if let Some(child) = guard.get_mut(&key) {
            if child.try_wait().map(|s| s.is_none()).unwrap_or(false)
                && probe_local(host_port, 0)
            {
                return Ok(());
            }
            guard.remove(&key);
        }
    }

    // Spawn `ssh -L 127.0.0.1:P:127.0.0.1:P <opts> <host> -N`
    let mut argv: Vec<String> = vec!["-N".into(), "-L".into()];
    argv.push(format!("127.0.0.1:{host_port}:127.0.0.1:{host_port}"));
    argv.extend(t.client_args());
    argv.push(t.host.clone());

    let mut cmd = tokio::process::Command::new(ssh_program());
    cmd.args(&argv)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| WorkbenchError::cli_protocol().with_detail(format!("tunnel spawn: {e}")))?;

    // Bounded wait for the local forward to answer (ssh handshake + bind).
    let mut ok = false;
    for _ in 0..40 {
        if child.try_wait().map(|s| s.is_some()).unwrap_or(true) {
            return Err(WorkbenchError::cli_protocol().with_detail(
                "tunnel ssh exited — check the machine's reachability",
            ));
        }
        if probe_local(host_port, 25) {
            ok = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    if !ok {
        let _ = child.kill().await;
        return Err(WorkbenchError::cli_timeout().with_detail("tunnel port never answered"));
    }

    if let Ok(mut guard) = registry.0.lock() {
        guard.insert(key, child);
    }
    Ok(())
}

/// Tear down every tunnel (target switch/clear; Workbench shutdown).
pub fn close_all_tunnels(registry: &TunnelRegistry) {
    if let Ok(mut guard) = registry.0.lock() {
        for (_, mut child) in guard.drain() {
            #[cfg(windows)]
            {
                // tree-kill: ssh may have inherited console children
                use std::os::windows::process::CommandExt;
                if let Some(pid) = child.id() {
                    let _ = std::process::Command::new("taskkill")
                        .args(["/PID", &pid.to_string(), "/T", "/F"])
                        .creation_flags(0x0800_0000)
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::null())
                        .status();
                }
            }
            #[cfg(not(windows))]
            {
                let _ = child.start_kill();
            }
        }
    }
}

/// Is anything answering on 127.0.0.1:port? (timeout_ms per attempt)
fn probe_local(port: u16, timeout_ms: u64) -> bool {
    let addr = format!("127.0.0.1:{port}");
    // Blocking connect with a short-lived socket; 0 timeout = instant check.
    use std::net::ToSocketAddrs;
    let Ok(mut addrs) = addr.to_socket_addrs() else {
        return false;
    };
    let Some(a) = addrs.next() else { return false };
    let dur = Duration::from_millis(if timeout_ms == 0 { 1 } else { timeout_ms });
    TcpStream::connect_timeout(&a, dur).is_ok()
}
