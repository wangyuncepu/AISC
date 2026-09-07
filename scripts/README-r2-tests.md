# R2 远程会话自动化测试（2026-09-07）

三层自动化（真 SSH + 真容器 + 真 GUI 进程），重跑前提：

1. WSL：`sudo /usr/bin/sshd -p 2222 -D -o ListenAddress=127.0.0.1 -o PasswordAuthentication=yes &`
2. WSL：`sudo ln -sf ~/AISC/.venv/bin/aisc /usr/local/bin/aisc`（远端 PATH 解析）
3. 测试容器：`RTID=$(python3 -c "import uuid;print(uuid.uuid4())"); docker run -d --name aisc-e2e-r2 --label io.aisc.runtime-id=$RTID super-claude:latest sleep 3600 && docker exec aisc-e2e-r2 sh -c 'mkdir -p /run/aisc/sessions && printf "{\"runtime_id\":\"'$RTID'\"}" > /run/aisc/runtime-context.json'`
4. Rust 真 SSH 集成：`cd workbench/src-tauri && AISC_TEST_SSH=dev@localhost:2222 AISC_TEST_RUNTIME_ID=$RTID cargo test --test serve_ssh`
5. UI 面自动化（Windows dev 起在 CDP 9223：`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9223 --remote-allow-origins=*' npm run tauri dev`；Windows settings.json 配 remoteMachines wsl 条目）：
   `RTID=$RTID .venv/bin/python scripts/r2-ui-cdp-test.py`

## R3（远端 FS 面）
- 真 SSH fs 集成：`cd workbench/src-tauri && AISC_TEST_SSH=dev@localhost:2222 cargo test --test serve_fs_ssh`
- UI 面 CDP（Explorer 远程浏览/预览/建文件/watcher）：`RTID 无需`，其余同 R2 前提，` .venv/bin/python scripts/r3-ui-cdp-test.py`
