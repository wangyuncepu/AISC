# 低配机器 Docker 性能优化批次规格（PERF，2.1.9 周期）

> 规约产物（对齐 opt-batch-spec 体例）：本文 = PRD + 实施计划 + 约束清单合一。
> 事实基础：2026-09-05 两路只读探针（宿主侧轮询/进程风暴 + 容器侧后台负载），
> 全部结论带 文件:行号 证据（§事实基线）；设计方案经独立 Plan agent 校验。
> 状态：**规格冻结待实施**。排期：用户点名开启后按批次依赖推进。

## 背景与用户裁决（2026-09-05）

用户开题：「docker 在低配置的机器上导致机器负载很大，整体应用使用非常
卡顿」。画像校准：**8GB 内存级 且 弱 CPU/慢盘复合**；卡顿全场景（空闲时
整机卡 / 操作 Workbench 时 UI 卡 / 多工作区明显变卡 / 首次启动·构建特别
卡 / 启动终端和 agent 都很慢）。

| 决策点 | 裁决 |
|---|---|
| 低配模式启用方式 | **自动应用 + 弹窗告知**（doctor 检测低配即自动启用并一次性通知；唯一保留确认的步骤：`.wslconfig` 写入需 `wsl --shutdown` 会停运行中容器——弹确认框） |
| 轮询取舍 | **温和拉长**（活跃 5s 不动；后台 25→60s、失焦 15→30s；空闲再拉长） |

**Out（明确不做/缓做）**：sidecar onefile→onedir（P10 记档，P6a 后重评）；
resize 第二通道事件驱动改造（P6b 二期）；终端技术栈更换；provider 轮询
Rust 化（P6b 后继候选）。

## 事实基线（探针实证）

### 进程开销（宿主侧）
- PyInstaller onefile 每次 spawn = **~750ms 纯进程开销**（bootloader 解包
  %TEMP% + AV 扫描 + Python 启动 + import 链），CLI 业务本身 p50 仅
  ~210-250ms；冷启首跑吃全量 AV 扫描（VERSION_TIMEOUT 45s，cli.rs L28-34）
- 活跃工作区 5s 轮询 tick = **2 次 aisc.exe**（inspect + 无条件跟随的
  services）+ **5-6 次 docker.exe 子进程** + 2 次 TCP 探测；慢引擎单 tick
  1.5-2.8s → **占空比 40-60%**
- spawn 速率实测：均值 42-60/h，**峰值 555-609/h**（aisc.log run_id 配对）
- **runtime/provider/services 命令层硬编码 RealDockerExecutor（docker CLI
  子进程链），绕过了已存在且 AutoGateway 默认 prefer_sdk 的 SdkGateway**
  （runtime.py L12/81/181）
- O6 退避梯子（5→10→20s）**只覆盖活跃工作区 focused 一档**；provider
  15s/60s、背景工作区 25s、blurred 15s、sync 15s、env 5s、lease 15s 全固定

### lease 心跳（O6b 挂账）
- 每 15s spawn 完整 aisc.exe，Python 侧只做「取锁-读 JSON-写一个
  lease_last_seen_at 字段」（零 Docker）= **每工作区 240 spawn/h**；
  隐藏窗口不停（lease.rs L3-6）；TTL=45s 跨实例契约

### 会话税（与「启动终端/agent 慢」直接相关）
- 每会话整个生命周期：watch_resize **每 0.1s 读 resize 文件** + 主线程
  **每 0.2s exec_inspect HTTP 轮询** = 每会话每秒 5 Docker API + 10 文件读
  （docker_gateway.py L671-686/L695-722）；exec socket EOF 本身即退出信号
  （轮询疑似冗余保险）
- 容器侧：claude/codex wrapper 每次启动 spawn node 做 env-inject；statusLine
  每渲染 spawn node；**每条 shell 命令 spawn python3 记 SQLite 历史**

### 容器与资源
- 容器 docker run **无 --memory/--cpus**（runtime.py L1140-1246）；idle 常驻
  4-5 进程；O5 巡检每 60s spawn 一次完整 cc-switch CLI 只为查健康
  （entrypoint L528-571，健康路径就一次 status）
- WSL2 默认吃宿主 ~50% 内存；doctor wsl-memory 仅 advisory；KI-1 有
  settings-store.json 原子保键写入先例（runtime.rs L1241-1283）
- 冷启动：daemon 就绪等待最多 40×CLI spawn（上限 10s）；entrypoint 一次性
  .claude/.codex 全量 cp -rL（慢盘 29s）+ node -e ×3 + python3 脚本 ×6+；
  镜像 2.6GB/66 层
- Rust 直连 Docker named pipe 先例：env.rs L136-157（/_ping 零子进程）

## spawn 消灭三层次的排序裁决

| 层次 | 单位收益 | 风险 | 关系 |
|---|---|---|---|
| ① tick 合并（P1） | 每 tick 省 1 aisc.exe + 1-2 docker.exe | 低 | ③ 前必须先回答「tick 消费什么数据」 |
| ② SDK 进命令层（P4） | 调用内 docker.exe 子进程 5-6→0 | 中 | 独立惠及控制操作；是 ③ 的降级路径组成 |
| ③ Rust 直连 pipe（P6a） | 稳态 tick 0 spawn | 高 | 架构终局；①②使 ③ 的 parity 面最小、回退基线最稳 |

三层各自独立 commit、独立可回退；③ 失败时回退到的正是 ①② 优化过的路径。

## P 项明细

### 第一波：快赢（无跨域契约变更）

**P1 · tick 合并：`runtime status` 单命令**［S-M］
- CLI 新子命令（独立命令，不动 inspect/services 旧契约）：一次调用内共享
  docker ps/inspect 结果，组装 `{snapshot, services|null}`；**services 为
  best-effort 嵌套字段**——内部 3s deadline，超时/失败 → null（不拖垮
  snapshot、不污染 backoff 慢信号；保持「不可用是合法观测」语义）
- Rust 新 command `runtime_status`（仿 runtime_inspect/runtime_services 的
  argv+envelope 模式）；前端 refreshRuntime 单次调用拆分喂
  applyRuntimeSnapshot + webServices——**一次观测一个 seq 一个 observed_at**
- 触点：cli/commands/runtime.py、application/runtime.py + web_gateway.py、
  cli/main.py、runtime.rs、ipc.ts、workspaceRuntime.ts、契约文档 05 §5.x。
  **sidecar 重建 + 三处同步**
- 验证：pytest fake executor 断言 docker 调用 ps/inspect 各 1 次；vitest
  拆分应用 + seq + services=null 不影响 fresh；aisc.log cli_exit tick 份额
  对比（-50%）

**P2 · 会话税：EOF 驱动退出 + resize 降频**［S-M］
- exec_inspect 0.2s 轮询 → drain 线程 EOF Event 驱动 + 收尾单查取退出码 +
  「EOF 但仍 Running」（后台进程占 exec pty 边角——轮询比纯 EOF 强的唯一
  场景）回退 1s 慢轮询 + 5s 保底间隔。**退出判据仍是 exec_inspect.
  Running==false，语义零变化；稳态 API 5/s→~0**
- watch_resize 0.1s→0.25s（resize 感知阈值 200-300ms 内、拖拽分屏不迟滞；
  env `AISC_RESIZE_POLL` clamp 0.05-1.0 可调）
- 触点仅 docker_gateway.py；回退 env `AISC_EXEC_POLL=legacy` 保留一版本。
  sidecar 重建
- 验证：adapter 三例单测（EOF 退出 / EOF-but-Running 慢轮询 / EOF 不来保底）；
  空闲会话 CPU/网络归零；`sleep 999 &` 边角；退出码正确入 session_exit

**P3 · 容器内 spawn 削减三件套**［M］（镜像链全规约）
- 3a shell 历史：每命令 1 python3 → 内存 TSV spool（转义防注入）+ 批量
  flush（每 20 条 / precmd 距上次 >60s / EXIT；`append` 子命令保留兼容）。
  丢数据窗口 <20 条（容器被 kill）——best-effort UX 可接受，注释说明
- 3b env-inject：每次 agent 启动 1 node → **mtime 缓存**（stat %Y 比对
  stamp，命中零 spawn；cc-switch 重写 settings 必更新 mtime）。**不选纯
  bash JSON 解析**（镜像无 jq；bash 解析对引号/转义/嵌套脆弱，注入错一个
  provider 即断流）；entrypoint node -e ×3 合并为 1 次三行输出
- 3c 巡检：每 60s 1 cc-switch CLI → `kill -0 $(cat pidfile)` 快检 + **每第
  5 轮真 `daemon status`** 捕捉 alive-but-hung（最终就绪/健康判据仍是真
  status，不误放行）。60/h→~12/h
- 触点：aisc-zshrc / aisc-bashrc / lib/aisc_bash_history.py / lib/env-inject.sh
  / entrypoint.sh / claude-wrapper / codex-wrapper。**vendor-refresh + 镜像
  重建 + 容器内验证 + wrapper 三副本同步**（STALE 教训）。双 rc 防漂移测试
  沿用 help-heredoc 范式
- 验证：容器内连续 25 条命令后 SQLite 批量记录；kill -9 daemon → 5min 窗内
  恢复（回归 O5 验证法）；wrapper 二次启动计时

### 第二波：结构性

**P5 · lease 心跳 Rust 直写（O6b 清偿）**［P5a 实验 S / P5b 主方案 M］
- **P5a 互操作实验先行**（独立 commit 纯测试）：双向钉死 Python 自研锁
  （msvcrt.locking byte[0,1) / POSIX fcntl.flock）与 Rust fs4 是否互斥——
  Windows 同为 LockFile 字节区间锁大概率互通；**POSIX flock/fcntl 互不相通
  是经典陷阱，必须实测**。测试落 pytest + cargo 双圈（互 spawn 对端）
- **P5b（成立时）**：Rust 心跳对齐 Python 全语义——fs4 同锁（有界重试 3s，
  **拿不到锁跳拍**，TTL 45s 吸收两拍）+ 校验 workbench_instance_id/lease_id
  （不匹配先走一次 CLI heartbeat 复核再发 workspace-lease-conflict，
  lease.rs L130-151 语义原样）+ storage::atomic_replace 只更新
  lease_last_seen_at；**claim/release/inspect 留 Python**（低频重操作）；
  env `AISC_LEASE_HEARTBEAT=cli` 一键回退；lease JSON 双端 parse 向量
  fixture 防漂移（仿 7a hash-vectors）
- 兜底（证伪时）：无锁 + mtime 守卫（写前 stat，mtime<5s 跳拍避开 claim
  窗口）；残余竞争后果最坏 lease_id 回退 → release 不匹配 → TTL 过期 +
  reconcile 收敛，可恢复
- **每工作区 -240 spawn/h**
- 验证：P5a 双向测试；cargo 单测（跳拍/冲突/写后 Python inspect 读到 fresh）；
  开工作区 30 分钟 aisc.log 无 lease spawn；双实例抢注 conflict 照发

**P4 · SDK 执行器进命令层**［M-L］
- 命令层 11 处 `executor or RealDockerExecutor()` → `executor or
  default_executor()` 工厂（AutoGateway prefer_sdk 已内建 + GBK 安全工厂
  hotfix）；`run_captured` 自由 argv 保留 CLI 子进程（build 等低频重操作），
  `["exec", ...]` 前缀映射 SDK exec（provider 链 15s 一次的 docker exec 是
  唯一高频自由 argv）；env `AISC_DOCKER_EXECUTOR=cli` 一键回退
- 错误码等价矩阵（D4-08 挂账）按 op 补齐断言：NOT_FOUND /
  DAEMON_UNREACHABLE / 超时三态（docker_gateway.py L500-516 有映射先例）
- **aisc.exe 体内 docker.exe 子进程链 5-6→0**。sidecar 重建
- 验证：pytest 等价性（SDK fake vs CLI fake 的 result 字段一致 + backend
  诊断=sdk）；真机冒烟 start/stop/inspect/list；aisc.log docker 子进程计数
  归零（除 build/exec 残留）

**P7 · 退避覆盖扩展 + 背景降级（纯前端）**［S-M］
- provider 轮询挂 pollBackoff 梯子（15→30→60s，O4 trace 耗时作慢信号）；
  背景工作区 25→60s（切回立即 inspect 兜底）；失焦 15→30s；syncPoll 补
  visibility/focus gate；env 5s 自轮确认「就绪即停」现状
- **lease cadence 不动**（TTL 跨实例契约；背景 ≠ 未使用，拉长心跳=邀请
  另一实例抢注；成本已由 P5 归零）
- 验证：vitest（pollBackoff 复用 + interval 行为 + visibility gate）；双
  工作区背景 10 分钟 spawn 计数对比

### 第三波：架构项

**P6a · 热轮询 Rust 直连 named pipe**［L］
- Rust 极简 Engine HTTP 客户端：复用 env.rs pipe transport，扩展三只读端点
  （`GET /containers/json?filters=<label>`、`GET /containers/<id>/json`、
  /_ping 响应头 API-Version 协商，pin 最低 v1.41）
- 新 Tauri command `runtime_poll_light`：data_root 直读 registry（Rust
  mirror 已有）+ 一次 containers API → RuntimeSnapshot 兼容 payload
  （running/exited→running/stopped；pipe 不通→unknown+stale，对齐
  inspect_runtime 语义）；web_access 探测省略，每 6 次 light tick 附带一次
  完整观测补齐
- useRuntimePolling tick 走 light；**控制操作后的立即刷新仍走完整 CLI
  保真**；**任何失败自动降级回 P1+P4 优化后的 CLI 路径（最坏=现状）**
- **稳态 tick 0 spawn——「空闲卡」根治项**；Python 零改动（无 sidecar 重建）
- 验证：cargo 集成（真实引擎条件跳过）；parity 手测脚本（同刻 light vs CLI
  对比）；外部 docker stop 后 UI ≤1 tick 更新；aisc.log 稳态 cli_exit 归零；
  10 分钟空闲整机 CPU 对比
- **P6b（二期记档）**：`GET /events` 流式订阅替代轮询 + Tauri 事件推送 +
  resize 第二通道 + 会话通道重构合并评估

### 第四波：产品化

**P8 · 低配模式（用户裁决：自动应用 + 弹窗告知）**［M-L］
- settings 新 `performance.lowSpec`（**doctor 检测物理内存 ≤8GB 自动置 on +
  一次性通知**说明改了什么/为何；可手动关）+ `performance.
  containerMemory/Cpus`（默认 3g/1.5 可调）。聚合三件：
- ① docker run `--memory/--max-cpus` 注入（Rust runtime_start → CLI 新
  flag → start_runtime argv）。**只影响新容器**；开启后设置页提示「重建
  容器后生效」（沿用「镜像更新不可见」提示先例）
- ② `.wslconfig` 保键原子合并（INI；memory/processors/swap 仅缺失才补，
  用户既有键绝不覆盖；corrupt 不碰——复用 KI-1 suppress_docker_dashboard
  三原则）。**此步弹确认框**（明示 wsl --shutdown 将停所有 WSL 实例与运行
  中容器），确认才执行——自动裁决下唯一保留的人工环节（destructive）
- ③ 容器内低配档：patrol 60→180s（env 化，随 P3c 合并）；statusLine 轻量
  bash 版替换 claude-hud 的每渲染一 node——**实施前单独请用户裁决**
- 风险注记：--memory 上限把「整机卡」风险转移为「容器内 cgroup OOM」（O5
  的 cc-switch daemon OOM 先例）——默认值保守（3g），通知里明说
- 验证：pytest（argv 含/不含限额双态 + wslconfig 合并保键——doctor 现有
  8 测试扩展）；cargo（settings 默认值/flag 传递）；8G 机手测——新容器
  HostConfig.Memory 有值、WSL VM 内存前后对比、限额下 claude 会话无异常

**P9 · 冷启动残余**［S-M］（镜像链）
- daemon 就绪等待 40×CLI spawn → pidfile `kill -0` 快检 + 指数退避
  （0.25/0.5/1/2s）+ 每 4 次采样一次真 `daemon status`（**最终就绪仍以真
  status 为准**，hung-but-alive 不误放行）
- entrypoint python3 脚本 ×6+ 相邻合并审计（catalog-sync 与 preset
  providers 相邻段优先）；逐个实证归属后再动
- 验证：假 FV → restart 注入（spawn 计数日志对比）；二次冷启动 ≤1.9s
  基线不回归；vendor-refresh + 镜像链全规约

**P10 ·（backlog 记档）sidecar onefile→onedir**：P6a 后 spawn 仅存低频
控制操作（有 UI 进度），750ms 毛刺暴露面大减；onedir 代价（安装体积/三处
同步链/NSIS 改动）届时重评。

## 批次依赖与收益数学

```
第一波（并行三泳道）: P1(Python) ∥ P3(镜像) ∥ P5a(实验) → P2
第二波: P5b → P4 → P7(纯前端随时插)
第三波: P6a（依赖 P1 的 tick 数据答案 + P4 降级路径就绪）
第四波: P8 → P9
```

**spawn 数学（活跃单工作区，验证目标）**：基线 ~555-609/h → P1 后 tick
份额减半（约 -200/h）→ P5 后再 -240/h（lease 归零）→ P6a 后稳态 tick
归零（残留 provider 轮询 + 控制操作）。多工作区叠加由 P7 背景档 + P5
per-workspace 直写收敛。

## 全局约束（对齐 opt-batch §G）

develop 分支纪律；每 P 项独立 commit + devlog；commit 前核对 staged 清单
覆盖 message 全部文件（35043e7 教训）；动刀前复核行号（探针有 ±7 行漂移
记录）；契约文档 05-cli-gui-contract 同步 P1/P8 新 flag；i18n 双语（P8）；
**不动既有不变式**：lease TTL=45s/stale-fresh 语义/会话退出判据/
streamCursor 单调/resize 语义；上游 cc-switch 只绕不改（status 判据保持
输出前缀匹配）；P1/P2/P4 后 sidecar 重建+三处同步；P3/P9 后
vendor-refresh+镜像重建+容器内验证+wrapper 三副本同步；门禁四矩阵
（cargo/vitest/vue-tsc/pytest）+ vite。
