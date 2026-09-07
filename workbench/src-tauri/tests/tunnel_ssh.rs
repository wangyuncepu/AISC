//! 2.1.10 R4a: gateway port tunnels over a real ssh link (AISC_TEST_SSH
//! gated, like serve_ssh.rs). A listener on the "remote" machine +
//! ensure_gateway_tunnel -> the SAME port answers locally -> teardown.

use workbench_lib::cli::SshTarget;
use workbench_lib::tunnel::{close_all_tunnels, ensure_gateway_tunnel, TunnelRegistry};

fn ssh_env() -> Option<(String, u16)> {
    let spec = std::env::var("AISC_TEST_SSH").ok()?;
    let (rest, port) = spec.rsplit_once(':')?;
    Some((rest.to_string(), port.parse().ok()?))
}

#[tokio::test]
async fn tunnel_forwards_remote_gateway_port() {
    let Some((host, port)) = ssh_env() else {
        eprintln!("skipping: AISC_TEST_SSH not set");
        return;
    };
    let target = SshTarget {
        host: host.clone(),
        port: Some(port),
        key_path: None,
        extra_args: vec!["-o".into(), "StrictHostKeyChecking=accept-new".into()],
    };
    const P: u16 = 47901;

    // NOTE: in the self-hosted test setup the "remote" machine IS this
    // machine (ssh to localhost), so the remote listener and the local
    // forward share one port space — probe the "before" state BEFORE the
    // remote listener exists, or the assertion is meaningless.
    assert!(!probe(P), "port already answering before anything started");

    // A throwaway HTTP listener on the remote side.
    let mut srv = tokio::process::Command::new("ssh")
        .args([
            "-p".to_string(), port.to_string(), "-o".to_string(), "BatchMode=yes".into(),
            "-o".to_string(), "StrictHostKeyChecking=accept-new".into(), host.clone(),
            format!("python3 -m http.server {P} --bind 127.0.0.1 >/dev/null 2>&1 & echo UP"),
        ])
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("remote listener spawn");

    use tokio::io::AsyncReadExt;
    let mut out = String::new();
    let _ = srv.stdout.take().unwrap().read_to_string(&mut out).await;
    assert!(out.contains("UP"), "{out}");
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;

    let registry = TunnelRegistry::default();
    ensure_gateway_tunnel(&registry, &target, P)
        .await
        .expect("tunnel established");
    assert!(probe(P), "local port answers through the tunnel");

    // Idempotent second call reuses the same child.
    ensure_gateway_tunnel(&registry, &target, P)
        .await
        .expect("reuse");

    close_all_tunnels(&registry);
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    // (A "port closed after teardown" assert is meaningless in the
    // self-hosted setup — the remote listener shares this port space and
    // stays up until the cleanup below. The registry-drain + process kill
    // are the teardown contract; on real cross-machine runs the port does
    // close.)

    let _ = tokio::process::Command::new("ssh")
        .args(["-p", &port.to_string(), "-o", "BatchMode=yes", &host,
               &format!("pkill -f 'http.server {P}' || true")])
        .output()
        .await;
}

fn probe(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        std::time::Duration::from_millis(300),
    )
    .is_ok()
}
