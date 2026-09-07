# R2 计划：runtime 生命周期 + 终端 PTY 远程流（远程体验闭环）

> 前置：R1 完成（serve 帧协议 + CliTarget/ServeSession，`669520c`）。
> 目标：远程模式下「选机器 → 起 runtime → 开 bash/claude 会话」全链路可用。

## 0. 关键事实（代码盘点 @ `669520c`）

- PTY 数据面现状：Rust `spawn_pipe_session` 起 sidecar `aisc session open`（pipes
  stdio）→ Docker SDK `open_interactive`（exec_create tty → socket 原始流：
  drain 线程 sock→stdout / forward 线程 stdin→sock / resize 线程文件轮询→
  `exec_resize`，`docker_gateway.py:554-740`）。
- **resize = G1 的根源**：`AISC_RESIZE_FILE` 本地文件 + env，远程侧读不到。
- runtime 生命周期：Rust `runtime.rs` 16 个 `run_control` 调用点 + lease 直写；
  P6a 后热轮询走 Rust 直连 Docker named pipe（`docker_api.rs`）——远程失效（G2）。

## 1. D-8 双路径裁决（2026-09-07）

**本地保持 `spawn_pipe_session` 直连不动；远程走 serve PTY 流帧。**

- 本地 PTY 直连是 B-05 十三轮手测打磨的稳定面 + P2/P3 性能优化的载体，
  零风险不动。
- serve PTY 路径的 **resize 天然带内**（客户端 `pty.resize` 帧 → serve 调
  `exec_resize`）——G1 与 P6b 第二通道随 serve 路径一并落地，本地路径的
  resize 文件机制保持不变。
- 双路径在 Rust 侧汇合于 `PtyEvent` 通道抽象：serve PTY 客户端产出与
  pipe 模式相同的事件流，`session.rs` 以最小改动按 target 分流。
- 代价声明：serve 路径字节流经 JSON 帧（base64 膨胀 ~33%），远程终端吞吐
  受一层封包开销——局域网场景可接受（VS Code 同款取舍）。

## 2. serve 协议 v1.1 扩展（追加式，不破坏 v1）

```text
客户端 → serve（流控制帧，独立于 op 请求）
  {"type":"pty.input","sid":"<uuid>","data":"<base64>"}
  {"type":"pty.resize","sid":"<uuid>","cols":80,"rows":24}
  {"type":"pty.kill","sid":"<uuid>"}

serve → 客户端（流事件帧）
  {"type":"pty.output","sid":"<uuid>","data":"<base64>"}
  {"type":"pty.exit","sid":"<uuid>","exit_code":0}

新 op：session.open
  ← {"id","op":"session.open","args":{runtime_id,session_id,agent,
      workspace,resume_conversation_id}}
  → result 帧（envelope.data 含 session_id/agent/exec 状态）之后，
    该 sid 的流帧持续到达直至 pty.exit
```

语义：op result 只表示「exec 已建立/失败」；流生命周期独立。sid 即
session_id（Workbench 生成 UUID v4）。kill = 断流（close socket + 停泵），
容器内进程处置与现状 pipe 模式杀 sidecard 的语义一致。

## 3. 实现布局

### R2a Python：流化 + serve PTY op

- `docker_gateway.py`：新增 `open_interactive_stream(container, argv, env,
  on_output) -> InteractiveStreamHandle{write/resize/close_stdin/kill/
  wait_exit}`——exec_create/exec_start/socket 原语（read_sock/send_all/
  shutdown_write）从现有 open_interactive 提出为模块级函数复用；现有
  fd 转发实现改为在 open_interactive 内部用 handle 组装（行为零变化），
  单测锚定。
- `cli/commands/serve.py`：`session.open` op（调 application/session 的
  open 逻辑 + stream 句柄注册表）；主循环分发 pty.* 帧（快操作，串行
  dispatch 不阻塞）；每会话输出泵线程 → 帧写锁串行化 stdout；SIGTERM
  时杀全部活跃 session。

### R2b Rust：ServeSession 全双工 + PTY 桥接

- `serve.rs` 重构：常驻读任务 + 帧分发（result → pending request oneshot；
  pty.* → 订阅通道）；`request` 与 PTY 并行不互吞。写方向锁串行化。
- `ServePtySession`：对接 `session.rs` 的注册逻辑（Starting→Running→
  exit 状态机、spool、close 语义）——产出 `PtyEvent` 与 pipe 模式同形。
- `session.rs`：`open_session` 按 target 分流（Local → `spawn_pipe_session`
  原样；Remote → serve PTY）。resize 带内。

### R2c 机器 target + runtime 路由（per-op ssh）

- settings 新增 `remoteMachines: [{name, host, user?, port?, keyPath?}]`
  （只读字段，UI 归 R4；R2 手测经 settings.json 手编）+ Rust 侧
  `ActiveTarget` 状态（默认 local，测试期可切）。
- `runtime.rs`/`lease.rs` 调用点经 `run_control_target` 路由；**G2 降级**：
  target=Remote 时禁用 `docker_api` 直连（poll 全走 CLI），能力探测明示。
- lease 直写（P5b）同样 target 路由。

### R2d 收口

手测（WSL 双端真链路：远程 preflight → build/起 runtime → 开 bash 会话 →
打字/resize/exit 全闭环）+ devlog + 阶段表。

## 4. 验收（AISC-R2-*）

- A1 serve PTY 单测（Python）：open→output 泵→input 回环→resize 调用→exit
  帧（fake executor stream）
- A2 open_interactive 流化重构零回归（既有 session 单测全绿）
- A3 Rust ServeSession 全双工单测（request 与 pty 帧并发不互吞）
- A4 Rust PTY 桥接（fake serve 端 duplex 驱动 PtyEvent 序列）
- A5 手测：真 SSH 链路会话闭环（打字可见、resize 生效、exit 收尾）
- A6 devlog/阶段表

## 5. 风险

- serve 输出泵与主循环的写竞争——帧写锁 + 逐帧 flush
- base64+JSON 封包吞吐：大输出（cat 大文件）时的帧粒度（攒批 16-64KB/帧）
- Python 侧线程生命周期（会话泄漏：exit 后泵线程必须 join；serve 退出时
  全量清理）
- runtime.rs 16 点路由改造的回归面——Local 路径必须 bit 级不变（测试锚定）
