# AISC Workbench 实施计划

> 状态：**MVP 执行基线（Proposed）**  
> 前置规范：[05-cli-gui-contract.md](./05-cli-gui-contract.md)  
> 原则：以可运行的端到端纵切替代“先做完后端，再做完前端”

## 一、交付范围

MVP 交付一个 AISC Workbench Preview，完成：

1. 选择工作区并执行环境预检。
2. 以显式 image/network/scope 创建一个可持久 runtime。
3. 在同一 runtime 内打开 Claude、Codex、Bash 和 cc-switch Session。
4. 正确处理终端输入输出、resize、信号和关闭。
5. 持续展示 workspace、runtime、活动 Agent、Provider、network 和 scope 状态。
6. 在 GUI/CLI 并行操作、Docker 不可用和 GUI 崩溃后可对账、恢复布局或安全清理。

MVP 不交付活 PTY 恢复、分屏、资源图表、内置编辑器、Provider 完整 GUI 编辑器和插件系统。

## 二、目标代码结构

```text
src/aisc/
├── cli/commands/
│   ├── runtime.py
│   └── session.py
├── domain/models.py
└── adapters/
    ├── docker_.py
    └── container_registry.py

container/
├── entrypoint.sh
└── aisc-session-wrapper

workbench/
├── src-tauri/
│   ├── src/
│   │   ├── cli.rs
│   │   ├── error.rs
│   │   ├── history.rs
│   │   ├── pty.rs
│   │   ├── runtime.rs
│   │   └── session.rs
│   └── capabilities/
├── src/
│   ├── components/
│   ├── features/
│   │   ├── startup/
│   │   ├── terminal/
│   │   └── runtime/
│   ├── stores/
│   └── types/
└── package.json
```

Workbench 作为同一仓库中的独立 Tauri 工程，不将 Node/Rust 依赖混入 Python CLI 的 `pyproject.toml`。

## 三、Phase 0：CLI 契约与容器基础

**目标：** 在不创建 GUI 的情况下，证明 runtime/session 模型可以端到端运行。

### S0.1 现有行为特征测试

**修改：**

- 为当前 `run --non-interactive`、`run --keep-alive`、registry schema、scope wrapper 增加特征测试。
- 新增命令不得破坏旧 `aisc run/shell/switch/stop` 的公开行为。

**测试落点：**

- `tests/features/test_runtime_compat.py`
- `tests/test_container_registry.py`
- `tests/test_cc_switch_runtime.py`

**DoD：** 兼容基线在 Linux/Windows Python 测试中稳定通过。

### S0.2 Runtime 控制面

**修改：**

- 实现只读 `runtime preflight` 与 `runtime start/list/inspect/stop/restart/remove`。
- preflight 固定输出 docker/workspace/image/network/runtime_conflict checks；start 在 workspace lock 内重验，不接受客户端回传结论。
- 实现 runtime ID、Docker labels、配置指纹和幂等重试。
- registry 向后兼容增加 `runtime_id`、`owner`、`scope`、`config_fingerprint`。
- 将 `.containers.lock` 实现为 POSIX `fcntl.flock` / Windows `msvcrt.locking` 的 fail-closed 跨进程锁；registry snapshot read 与 write 均遵守锁协议。
- 以 canonical workspace hash 的独立锁串行化 project Runtime 冲突检查、Docker 创建和 registry commit，并固定 workspace lock -> registry lock 顺序。
- 将 registry 写入移到 Docker 创建成功之后；失败和取消路径清理部分资源。
- entrypoint 支持无 TTY、显式 scope、可健康检查的 idle runtime 模式；ready 前原子写入不含密钥的 `/run/aisc/runtime-context.json`。

**测试落点：**

- `tests/test_runtime_commands.py`
- `tests/features/test_runtime_json_contract.py`
- `tests/features/test_runtime_preflight_no_side_effects.py`
- `tests/features/test_registry_lock_cross_platform.py`
- `tests/integration/docker/test_runtime_lifecycle.py`
- `tests/integration/docker/test_runtime_start_race.py`

**DoD：** 从空 Docker 状态执行 start 到 remove 全链路通过，每个 JSON envelope 和进程退出码一致；POSIX/Windows 多进程 registry 写入不丢失，同一 workspace 并发 start 只有一个 project Runtime 成功。

### S0.3 Session 数据面

**修改：**

- 新增容器内 `aisc-session-wrapper`。
- 实现 `session open/list/terminate`。
- Claude/Codex/Bash/cc-switch 使用受控 argv，从 runtime context 重建 scope 环境，不依赖 `docker exec` 继承 PID 1。
- Agent 配置在每次 Session 打开时重新读取；环境变量通过 exec environment 安全传递，不使用 shell/eval，不写入 Session 元数据。
- 在 `/run/aisc/sessions` 原子维护 `0600` Session record；实现 PID/PGID/start ticks 身份校验、TERM 宽限期、KILL fallback 和 wait/reap。

**测试落点：**

- `tests/test_session_commands.py`
- `tests/integration/docker/test_session_scope.py`
- `tests/integration/docker/test_session_termination.py`
- `tests/integration/docker/test_session_pid_reuse.py`

**DoD：** 四种 Session 在 project/temporary scope 均可启动；Runtime 启动后 Provider 变更对新 Session 生效且不泄密；terminate 后宿主与容器内均无残留进程。

### S0.4 Provider 与 capability

**修改：**

- `version --format json` 增加 Workbench capabilities。
- 实现 `provider current --runtime-id --agent --format json`。
- 为 Claude/Codex 分别返回 Provider、route mode 和 auth status，不读出密钥。

**DoD：** 无 Provider、Claude 代理、Codex 官方直连三种 fixture 返回正确状态，secret scan 通过。

### S0.5 Build event contract

**修改：**

- 为现有 `build --events` 增加 `aisc.build-events/v1` capability。
- 将 Docker/BuildKit 输出实时封装为有序 `build.output` JSONL，而不是结束后一次性回放 stderr。
- 固定 complete/failed/cancelled terminal event 与退出码；取消时回收 CLI 和 Docker 子进程。
- Workbench 只将不透明 build output 显示在本次启动界面，不解析、不持久化。

**测试落点：**

- `tests/features/test_build_events_contract.py`
- `tests/integration/docker/test_build_cancellation.py`

**DoD：** 成功、失败、取消流均满足 [05-cli-gui-contract.md](./05-cli-gui-contract.md) 第 4.1 节，慢消费者有背压且无无界内存增长。

### Phase 0 验收门

- [ ] [05-cli-gui-contract.md](./05-cli-gui-contract.md) 第十二节全部通过。
- [ ] 现有 Python 单元、特征、打包测试无回归。
- [ ] Linux Docker E2E 自动通过，Windows Docker Desktop 完成手工契约测试。
- [ ] `runtime`、`session`、`providerStatus`、`buildEvents` capability 与实现逐项匹配。
- [ ] 不通过此门禁止开始多标签和完整启动 UI。

## 四、Phase 1：Tauri + PTY 垂直切片

**目标：** 用最小 UI 证明 `Workbench -> PTY -> aisc session open -> Agent` 完整链路。

### S1.1 工程脚手架

- 创建 `workbench/` Tauri 2 + Vue 3 + TypeScript 工程。
- 仅加入 xterm.js、FitAddon 和最小状态库；不在此切片引入主题系统、Radix 全套组件或快捷键编辑器。
- Tauri capabilities 只允许 Workbench 需要的命名 command。

### S1.2 结构化 CLI runner

- `cli.rs` 实现 CLI discovery/pinning：保存路径、进程 PATH、平台已知安装位置和用户选择；多安装冲突必须确认。
- `cli.rs` 实现 argv-only process runner、timeout、cancellation、stdout 大小上限和 `aisc.cli/v1` envelope 校验。
- 启动时做 capability negotiation，不支持时显示阻塞页而不是崩溃。
- error code 映射为 Workbench domain error，保留脱敏 technical details。

### S1.3 PTY supervisor

- 每 Session 独立持有 master/writer/reader/child/cancellation token。
- 先建立 Tauri Channel 再启动子进程，不丢失首屏输出。
- 输出以 byte chunk + seq 传递，前端以 `Uint8Array` 写入 xterm.js。
- `ResizeObserver` 节流调整 PTY，标签变为可见时重新 fit。
- close 按 terminate -> close PTY -> wait/reap 顺序完成。

### S1.4 最小端到端 UI

- UI 仅包含工作区路径、“启动 Bash”、终端区域和“停止 Runtime”。
- 当前阶段不做首页、多标签、Provider UI 或资源监控。

### Phase 1 验收门

- [ ] Linux 和 Windows 实机上 Bash Session 可交互，可 resize，可确定性关闭。
- [ ] Claude 与 Codex 至少各完成一次登录/输入/Ctrl+C/退出 smoke test。
- [ ] 连续输出 10 MB、中文/emoji、1 MB 粘贴和 100 次 resize 不乱码、不丢序、不崩溃。
- [ ] 快速连续开关 50 个 Session 后无孤儿宿主或容器内进程。

## 五、Phase 2：产品核心闭环

**目标：** 完成从打开工作区到安全结束工作的 MVP 主路径。

### S2.1 启动与预检

- 工作区选择器、最近列表和 canonical path 验证。
- 实现 hard gate/config gate/warning 分类。
- 快速启动在一个确认界面展示推断值，不静默创建工作区或 runtime。
- 镜像缺失时用 `aisc build --events` 提供可取消进度。

### S2.2 Runtime 与 Session 状态

- 实现 [03-lifecycle-contract.md](./03-lifecycle-contract.md) 的状态机和事件 reducer。
- 一个 workspace 默认一个 project runtime，多 Session 共享该 runtime。
- 实现 Claude/Codex/Bash/cc-switch 标签，Tab 只是 Session 视图。
- 实现关闭 Session、停止 Runtime、退出 Workbench 三种不同操作。

### S2.3 最小可观察性

- 常驻显示 workspace、runtime state 和活动 Agent。
- 次级显示活动 Agent 的 Provider/route mode、network 和 scope。
- 侧栏只包含配置、精确 ID、Session 列表和启动诊断；不做 CPU/内存图表。

### S2.4 历史与对账

- 以 schema-versioned、原子写入的 Workbench history 保存 workspace/runtime ID/标签元数据。
- `history.rs` 使用跨平台进程锁和 expected revision，在锁内 reload/merge/atomic replace；多窗口只 patch 自己拥有的 workspace/layout。
- 启动时调用 `runtime list`对账，将历史与实际状态合并，不直接读写 CLI registry。
- 恢复标签时创建新 Session，文案明确不是原 Agent 会话续接。

### Phase 2 验收门

- [ ] 首次启动、快速启动、恢复布局三条主路径通过。
- [ ] Docker 未运行、CLI 过旧、镜像缺失、workspace 无权限均显示稳定可操作错误。
- [ ] GUI 外 `aisc runtime stop/remove` 后，Workbench 在轮询周期内显示真实状态。
- [ ] 崩溃后重启可发现 runtime，不自动删除或停止它。
- [ ] 两窗口并发更新 history 不丢 workspace/tab，revision conflict 有界重试并保留可恢复错误。

## 六、Phase 3：稳定性、安全与可访问性

### S3.1 异常与并发

- 覆盖 Docker daemon 重启、runtime OOM/意外退出、CLI 外部操作、启动取消和两个 Workbench 窗口竞态。
- 状态更新使用 observed_at/revision 拒绝过期结果覆盖新状态。
- 所有进程、timer、listener 和 channel 有确定性 cleanup。

### S3.2 安全

- Tauri CSP/capabilities/opener 限制通过安全审查。
- 日志、history、crash report 执行 secret scan，不持久化 PTY scrollback。
- workspace 路径、URL 打开、大段粘贴和破坏性操作有显式边界。

### S3.3 可访问性

- 全部应用操作可键盘完成，终端键与应用快捷键有明确路由优先级。
- 状态不只依赖颜色，状态变化使用节流的 `aria-live`。
- Windows/Linux 使用 Ctrl，macOS 使用 Command 的平台默认，MVP 不做 OS 级全局快捷键。

### Phase 3 验收门

- [ ] 安全检查清单、secret scan、进程泄漏检查通过。
- [ ] 主路径键盘和屏幕阅读器 smoke test 通过。
- [ ] 连续运行 8 小时、10 个 Session 和高输出场景无无界内存增长。

## 七、Phase 4：打包与 Preview 发布

### S4.1 依赖与安装体验

- 安装包检测 AISC CLI 与 Docker，不绑定或静默安装 Docker。
- AISC CLI 缺失/过旧时提供平台对应的官方安装/升级路径。
- 从 Finder/Dock、开始菜单和 Linux desktop entry 启动均验证 CLI discovery；覆盖升级后 pinned executable 重新协商且不误用另一安装。
- Linux 文档明确 WebKitGTK 与 Docker 权限；Windows 检查 WebView2/Docker Desktop；macOS 完成签名与 notarization。

### S4.2 发布门

- Linux x86_64、Windows x86_64、macOS arm64 均运行同一契约 smoke suite。
- 安装、覆盖升级、卸载不破坏 AISC CLI 配置、workspace 或运行中 runtime。
- 签名、公证、版本协商和回滚文档完成后才发布 Preview。

## 八、测试矩阵

| 层级 | 覆盖 | 阻断门 |
|---|---|---|
| Python 单元 | runtime/session 规划、registry、错误映射 | 每个 PR |
| CLI 契约 | JSON envelope、退出码、幂等与密钥泄漏 | 每个 PR |
| Docker 集成 | runtime lifecycle、scope、session terminate | Linux CI + release 实机 |
| Rust 单元 | CLI parser、state reducer、history migration、error mapping | 每个 PR |
| Vue 组件 | startup gate、tabs、status、可访问性 | 每个 PR |
| Tauri 端到端 | PTY、resize、close、崩溃对账 | nightly/release |
| 平台实机 | ConPTY、Docker Desktop、签名安装包 | release gate |

## 九、每个切片的通用 Definition of Done

- 实现与本切片的规范文档一致，不依赖未声明的文本输出或 Docker 内部细节。
- 正常、失败、取消和重试路径均有测试。
- 新增状态、错误码和持久化字段有向后兼容策略。
- 不在命令行、JSON、日志、history 或 crash report 中泄漏密钥。
- 子进程、PTY、listener、timer、channel 和临时文件全部有 cleanup 证据。
- 更新相关文档与手工验证清单。

## 十、开始实现前的最终决策

以下决策在本计划中已固定，实现时不再默认重新打开：

1. 产品名称为 AISC Workbench。
2. CLI 是唯一 Docker/registry 控制面。
3. 一个 workspace 默认一个 project runtime，多 Session 共享它。
4. Session 以 portable-pty 运行 `aisc session open`。
5. MVP 只恢复布局，不恢复活 PTY。
6. MVP 不直接读取 Provider 密钥，不实现完整 Provider GUI 编辑器。
7. MVP 不做资源图表、Docker Dashboard 或 IDE 功能。
8. 不用“7 周”作为发布承诺；只有通过阶段验收门才进入下一阶段。
