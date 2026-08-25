# 容器内 Web 服务访问 — 验收台账

> 计划：`docs/plans/container-service-access.md` · 合同：`decisions.md`
> 分支：`svc-container-web-access`（2026-08-25）
> 状态：**自动化门禁全绿；Windows Docker Desktop 实机手测待用户执行**

## 1. 阶段交付与提交

| 阶段 | 提交 | 内容 |
|---|---|---|
| svc-0 合同冻结 | `9ab76bd` | 常量/双 schema/URL builder/错误码；Python 权威 + Rust/TS 镜像；三端同 fixture 解码（阶段门）；decisions.md |
| svc-1 容器侧 | `cf82492` | `aisc-web-gateway`（asyncio 字节泵 45871）+ expose/unexpose/list 三件套；manifest 0600/0700 原子写；Dockerfile 装配（py_compile 冒烟 + CR 剥离）；entrypoint 全模式启动；vendor/checksums 刷新 |
| svc-2 宿主生命周期 | `716ff2a` | host port 分配器（bind 探测 + 冲突重试）；`--publish 127.0.0.1:<host>:45871/tcp`；registry 可选元数据（不入 fingerprint）；reuse 复用映射 + heal；inspect `web_access`；`runtime services [list/expose/unexpose]`；能力 `runtimeServices`；事件 |
| svc-3 Agent 合同 | `1303151` | global-claude.md 服务启动 checklist（同一文件生成 CLAUDE.md/AGENTS.md）；静态测试禁止"容器 localhost 当用户 URL"示例 |
| svc-4 Workbench | `52f833c` | 能力协商扩展（classify 矩阵 +10 行矩阵项）；RuntimeSidebar「Web 服务」区（语义 key、reason i18n、复制/受限打开）；`runtime_services` + `open_runtime_service_url`（后端重生成 URL + 字节级校验 + 字符集门 + 无任意 opener 插件）；store 缓存/降级/清理 |
| svc-5 run 路径 | `08aeb55` | plan_run 分配端口（dry-run 也展示）；RunPlan publish；captured 路径冲突重试（argv 由 replaced plan 重建，不叠 publish）；RunResult `web_gateway` 元数据；text 模式一行提示；`--rm` 成功后 GC 清注册 |
| svc-6 验证 | `77cdb9e` | 集成测试 + 台账 |
| 修复轮 | `caa26d5` | Dockerfile py_compile 移层（首次镜像构建 `python3: not found`）；Python 3.14 argparse 嵌套子命令 required 语义修复（父层改可选+dispatch 校验）；集成测试支持 `AISC_CLI_EXECUTABLE` |

## 2. 自动化证据（本机，2026-08-25）

| 门禁 | 结果 |
|---|---|
| `python -m pytest tests/` | **879 passed, 69 skipped**（skip=平台/环境门控） |
| 其中 svc 专项 | test_web_services 25 / test_web_gateway 23+1skip / test_runtime_services 26 / test_agent_contract 6 |
| `npx vue-tsc --noEmit` | 通过（0 错误） |
| `npx vitest run` | **366 passed (45 files)**（含 runtimeWebServices 6 + sidebar svc-4 5 项） |
| `cargo test --offline` | lib **225** + 集成（cli_fixtures 7 / web_services 4 / …）全绿 |
| 本地已知怪癖 | pty_supervisor 3 例需 `SH="C:/Program Files/Git/bin/sh.exe"`（记忆挂账，非本次改动） |
| sidecar | build-cli.ps1 重建，`runtimeServices` 能力已广播；已同步 `src-tauri/binaries/` + `target/debug/`（14:16:09） |
| vendor/checksums | 已随 svc-1/svc-3 刷新（1508 files checksummed） |

## 3. CI（推送后）

预期：cli-sidecar（pytest 全量 + 集成跳过/运行按环境）、Workbench CI（cargo+vitest+vue-tsc）、
Bundle/NSIS 按 path filter。container/ 改动后已手动跑过 `tools/vendor-refresh.sh`；
若 Bundle/NSIS 未触发需 `gh workflow run` 手动补跑（记忆规程）。

`tests/integration/docker/test_web_services.py`：真实 Docker 端到端（start→publish→
expose→容器内 loopback 服务经网关 200→未注册 404→目标未监听 502→坏 Host 400→
unexpose→stop 后 `runtime_not_running`→restart 映射不漂移）。

**2026-08-25 本机实跑记录**：Docker Desktop 29.7.2 已装机；镜像已用新 sidecar
rebuild（gateway/helper 镜内冒烟通过）；`AISC_CLI_EXECUTABLE=dist/aisc-*.exe
python -m pytest tests/integration/docker/test_web_services.py` **PASSED**
（44.7s，全链路真实容器/真实 publish/真实网关转发）。其余 docker 集成用例本机
因 venv 无 `aisc` 入口跳过（Windows 既有限制，CI Linux venv 覆盖）。

## 4. 待用户手测清单（Windows Docker Desktop）

前提：Docker Desktop 可用（本机当前未安装——需先安装）；镜像需重建以打入 svc-1：

```powershell
# 1) 重建镜像（打入 gateway/helper）
aisc build --tag super-claude:latest
# 2) dev 模式（新 sidecar 已同步 target/debug）
cd workbench; npm run tauri dev
```

| # | 场景 | 预期 |
|---|---|---|
| M1 | Workbench 启动 runtime | 侧栏「Web 服务」区出现，网关就绪 + 端口（47000..47999） |
| M2 | bash tab 内 `python3 -m http.server 3000 --bind 127.0.0.1 &` + `aisc-web-expose 3000 --name "docs preview"` + `aisc-web-list` | 固定输出行 `aisc web service registered: port=3000 name="docs preview"` |
| M3 | 侧栏服务行「打开」 | 默认浏览器打开 `http://p3000.localhost:<host>/` 可访问（目录列表 200） |
| M4 | 服务行「复制」 | 剪贴板为 canonical URL |
| M5 | M2 服务关闭后刷新 | 打开 → 网关 502 `AISC_WEB_TARGET_UNAVAILABLE` 错误页 |
| M6 | 未注册端口直接拼 URL | 404 `AISC_WEB_PORT_NOT_EXPOSED` |
| M7 | `aisc-web-unexpose 3000` 后刷新 | 服务行消失；URL 404 |
| M8 | 停止 runtime → 侧栏 | 服务区显示"运行时未运行"，无死链 |
| M9 | 重启 runtime | URL 端口不变（映射复用，不漂移） |
| M10 | Claude/Codex tab 里让 Agent 起 Web 服务（按 CLAUDE.md/AGENTS.md checklist） | Agent 注册端口并告知用户从侧栏打开，不输出容器 localhost 当用户 URL |
| M11 | Vite dev server（HMR/WebSocket） | 页面可开、HMR 生效（字节泵透传 upgrade） |
| M12 | `aisc run`（text） | 启动前打印一行网关 URL 合同；`--format json` 含 `web_gateway` |
| M13 | 旧 runtime（重建前创建）inspect | `web_access.state=unavailable, reason=legacy_runtime`，不崩 |

## 5. 安全检查对照（§9.4）

- [x] gateway 仅容器内 `0.0.0.0:45871`；宿主仅 `127.0.0.1:<host>` publish（argv 由
      `docker_publish_argv` 单点生成，测试断言形态）
- [x] 未注册端口 404 / 目标外不可达（gateway 只连 `127.0.0.1:<port>`，代码路径无其它目标）
- [x] Host 校验严格正则（含 FQDN 尾点/端口后缀/大小写；重复 Host 拒绝）
- [x] manifest fail closed（malformed/异名文件 → 503，svc-1 测试覆盖）
- [x] UI 打开仅后端重生成 + 字节级 canonical 比对 + 字符集门（Rust 测试覆盖拒绝样例）
- [x] 日志/事件不含 path/query/header/body（gateway 只记 peer/target port/code；host CLI
      事件字段=ports/state）

## 6. 回滚

按阶段独立回滚（计划 §11）；svc-2 回滚前停止创建带 publish 的 runtime；
svc-4 回滚 UI 打开保留复制。registry 新字段全部 optional，旧 runtime 不转换，
restart/recreate 后才获得网关。

## 7. 结论

自动化门禁全绿、合同三端一致、端到端集成测试就位。待 M1-M13 实机手测 PASS 后
合并 develop。
