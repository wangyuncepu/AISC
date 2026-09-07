//! 2.1.10 R3: the remote FS plane over a REAL ssh link (fs.* via the pooled
//! serve session). Gated like serve_ssh.rs — `AISC_TEST_SSH` (user@host:port)
//! only; skipped otherwise.

use base64::Engine;
use workbench_lib::cli::SshTarget;
use workbench_lib::serve::{fs_op, ServePool};

fn ssh_env() -> Option<(String, u16)> {
    let spec = std::env::var("AISC_TEST_SSH").ok()?;
    let (rest, port) = spec.rsplit_once(':')?;
    Some((rest.to_string(), port.parse().ok()?))
}

#[tokio::test]
async fn fs_plane_over_real_ssh_roundtrip() {
    let Some((host, port)) = ssh_env() else {
        eprintln!("skipping: AISC_TEST_SSH not set");
        return;
    };
    let target = SshTarget {
        host,
        port: Some(port),
        key_path: None,
        extra_args: vec!["-o".into(), "StrictHostKeyChecking=accept-new".into()],
    };
    let pool = ServePool::new();

    // A scratch root on the serve process's machine.
    let root = format!("/tmp/aisc-r3-fs-{}", std::process::id());

    fs_op(&pool, &target, "fs.mkdir", &serde_json::json!({ "root": root, "path": "" }))
        .await
        .expect("mkdir root");

    let blob = base64::engine::general_purpose::STANDARD.encode("远程写入内容 remote-write".as_bytes());

    // Contract: write requires an existing parent — sub/ doesn't exist yet.
    let missing_parent = fs_op(&pool, &target, "fs.write",
        &serde_json::json!({ "root": root, "path": "sub/file.txt", "base64": blob })).await;
    assert!(missing_parent.is_err(), "write into a missing parent must fail");

    fs_op(&pool, &target, "fs.mkdir", &serde_json::json!({ "root": root, "path": "sub" }))
        .await
        .expect("fs.mkdir sub");
    fs_op(&pool, &target, "fs.write",
          &serde_json::json!({ "root": root, "path": "sub/file.txt", "base64": blob }))
        .await
        .expect("fs.write");

    let read = fs_op(&pool, &target, "fs.read",
                     &serde_json::json!({ "root": root, "path": "sub/file.txt" }))
        .await
        .expect("fs.read");
    let got = base64::engine::general_purpose::STANDARD
        .decode(read.get("base64").and_then(|v| v.as_str()).unwrap_or_default())
        .unwrap();
    assert_eq!(got, "远程写入内容 remote-write".as_bytes());

    let list = fs_op(&pool, &target, "fs.list",
                     &serde_json::json!({ "root": root, "path": "" }))
        .await
        .expect("fs.list");
    let names: Vec<&str> = list
        .get("entries")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|e| e.get("name").and_then(|n| n.as_str())).collect())
        .unwrap_or_default();
    assert!(names.contains(&"sub"), "entries: {names:?}");

    let escape = fs_op(&pool, &target, "fs.list",
                       &serde_json::json!({ "root": root, "path": "../../etc" })).await;
    assert!(escape.is_err(), "containment must reject .. escapes");

    // delete root itself is refused; cleanup through the /tmp root.
    let root_delete = fs_op(&pool, &target, "fs.delete",
                            &serde_json::json!({ "root": root, "path": "" })).await;
    assert!(root_delete.is_err(), "deleting the root must be refused");
    fs_op(&pool, &target, "fs.delete",
          &serde_json::json!({ "root": "/tmp",
                               "path": root.trim_start_matches("/tmp/") }))
        .await
        .expect("cleanup delete");
}
