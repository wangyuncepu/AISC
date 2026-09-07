# R1 计划：serve 通道 + 传输抽象（远程化地基）

> 前置：R0 验收（D-4 全特性本周期）、S0 F1 剥离完成（`a8f73eb`）。
> 目标：为 R2（runtime+终端）/R3（文件面）/R4（机器页）立好协议与传输地基。

## 0. 范围

**做**：

- Python：`aisc serve --stdio` 长驻帧协议服务（ready 横幅 + 请求/响应 + 事件帧类型预留），首批 op = version / doctor / ps
- Rust：`CliTarget` 抽象（`Local(PathBuf)` / `Remote(SshTarget)`）；`run_control*` 新增 target 版入口，**既有 41 调用点零改动**（全 Local，行为零变化）
- Rust：Remote 传输 = per-op `ssh <alias> aisc <argv>` spawn（朴素实现）；serve 长驻通道的 Rust 客户端（stdio 帧编解码）
- 测试：serve 子进程往返单测（Python + Rust 双侧）；Remote 传输用「本地 spawn serve 当远端」模拟；真 SSH 链路手测步骤交用户（WSL↔NAS / Windows↔WSL localhost）

**不做（后续阶段）**：PTY 流接 serve（R2）、事件推送实现/watchdog（R3）、机器配置 UI/settings（R4）、ControlMaster 连接复用优化（R2，per-op ssh 的延迟消除手段）。

## 1. 通道分工（R1 确立的双通道模型）

| 通道 | 形态 | 适用 | 理由 |
| --- | --- | --- | --- |
| **per-op ssh** | 每次 op 起一个 `ssh <alias> aisc <op> --format json` | 低频控制面（version/doctor/ps/生命周期） | 实现最朴素、无状态、故障隔离好；AISC op 频率低（P7 后轮询 30-60s），SSH 握手开销可接受；R2 起 ControlMaster 复用消除重复握手 |
| **serve --stdio 长驻** | 一条 `ssh <alias> aisc serve --stdio` 会话，JSONL 帧多路复用 | 流式/高频面（R2 PTY、R3 FS RPC 与事件推送） | VS Code 同款模型；流式数据不适合一次性进程 |

R1 两条都立起来；R2/R3 按面选择接线。

## 2. serve 帧协议 v1（`--stdio` 模式）

UTF-8、每行一个 JSON（与 `/events` JSONL 家族风格一致）：

```text
serve → 客户端（启动横幅，进程就绪标志——对应 VS Code 的版本配对握手）
  {"type":"ready","serve_protocol":1,"cli_version":"2.1.9.dev0"}

客户端 → serve（请求）
  {"id":"u1","op":"version","args":[]}

serve → 客户端（响应：单帧承载 CLI envelope 对象）
  {"id":"u1","type":"result","ok":true,"envelope":{...}}

serve → 客户端（serve 自身诊断日志，带内；op 的业务 stderr 已在 envelope.errors）
  {"type":"log","level":"info","line":"..."}

（类型预留，R2+ 实现）
  {"type":"event","event":"...","data":{...}}
```

- op 内部强制 `--format json` 语义——serve 只出口 envelope，stdout 无杂散输出（RFC 契约延伸）
- 处理模型：R1 **串行**（逐请求执行），`id` 字段为并发预留
- 生命周期：stdin EOF / SIGINT / SIGTERM → 优雅退出（在飞请求完成或 3s 超时强退）；非 JSON 行/未知 op → `{"id":..,"type":"result","ok":false,"error":"..."}`，进程不退
- 鉴权：**D-7——stdio 模式无 token**。serve 只与 ssh 会话的 stdin/stdout 通话，无监听面，SSH 认证即传输认证（VS Code 同款）。若日后加 TCP 直连模式（局域网无 SSH 场景）必须引入 F2 式 token + 回环绑定，另行裁决

## 3. 实现布局

### Python（`src/aisc/`）

- `cli/commands/serve.py`：`aisc serve [--stdio]`（R1 仅 stdio；无 `--stdio` 参数时报错指引，为 TCP 模式留位）。主循环逐行读 stdin → dispatch → 写响应；envelope 构造复用 `cli/output.py`
- op 表 R1 三项：`version`（`application/version.py`）、`doctor`（`application/doctor.py`）、`ps`（container 列表路径）。直接调 application 层，不穿 argparse
- `cli/main.py` 注册子命令（只读操作，支持 JSON；不交互）

### Rust（`workbench/src-tauri/src/`）

- `cli.rs`：`pub enum CliTarget { Local(PathBuf), Remote(SshTarget) }`；`pub struct SshTarget { host, user, port, key_path, extra_ssh_args }` → `ssh_argv_prefix()` 生成 `["ssh", ...opts..., host]`，op argv 追加在后（远端假定 `aisc` 在 PATH；R4 机器档案落位后支持显式路径）
- `run_control_target(target, argv, timeout, cancel)` / `run_control_input_target(...)`：`Local` 走既有 `run_control_inner`（原函数体不动）；`Remote` 用 ssh argv 前缀同路 spawn。旧签名函数保留为 `Local` wrapper，41 调用点零改动
- `serve.rs`（新）：serve 客户端——spawn（或附着）`serve --stdio` 进程，读 ready 横幅校验 `cli_version` 与本地 Workbench 期待版本的配对，帧编解码（`serde_json` 逐行），请求-响应关联（R1 串行）；真 ssh 接法 = spawn `ssh <alias> aisc serve --stdio` 复用同一客户端（stdio 形状相同）

## 4. 验收清单（AISC-R1-*）

- **A1** `aisc serve --stdio` 存在且 `--help` 正常；文本模式禁用（serve 是机器协议，报错指引）
- **A2** Python 单测：子进程起 serve，喂 version/doctor/ps 三 op 断言 envelope 形状 + ready 横幅 + EOF 退出码
- **A3** Rust：`cargo test` 全绿（Local 通道回归零变化）+ `CliTarget`/ssh argv 单测
- **A4** Rust serve 客户端单测：本地 spawn 真 `aisc serve --stdio`（venv 内）往返三 op；坏帧/unknown op 的错误路径
- **A5** 手测（用户）：①WSL 内 `printf '...\n' | aisc serve --stdio` 直连自测；②真 SSH 链路一例（Windows→WSL localhost 或 WSL→NAS，`ssh <t> aisc serve --stdio` + 手发一帧）——证明跨机可用
- **A6** devlog + 阶段表更新

## 5. 风险

- Windows 目标机的 ssh spawn 差异（OpenSSH client 参数面）——R1 目标限 Linux 远端（R0 已裁定），Windows 远端后续版本
- serve 长驻进程的生命周期管理（Rust 侧持有 stdin 句柄、断连重连）——R1 只做客户端编解码与单次会话，托管策略（保活/重连/复用池）在 R2 随 PTY 面一起定
- doctor 在远端的 Docker 探测可能慢（ssh 往返 × 多探针）——per-op 超时沿用现有 Duration 体系，必要时 R2 调参
