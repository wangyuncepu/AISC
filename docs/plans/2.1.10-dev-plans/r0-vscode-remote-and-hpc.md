# R0 调研：VS Code 远程工作逻辑 × Slurm/PBS 场景 × AISC 可行性

> 状态：初稿（2026-09-07，待用户验收）。
> 调研问题：① VS Code 远程开发的工作逻辑与实现方案；② Slurm/PBS 使用场景的实况；
> ③ 对照 AISC 现状判断「Workbench ↔ 远端机器上的 aisc-cli 通信」是否可行、差在哪。

## 1. VS Code 的三条远程路线

VS Code 官方生态里「远端开发」有三种形态，架构差异本质在于**UI 跑在哪、
数据面走什么通道**：

| 路线 | UI 位置 | 远端组件 | 数据通道 | 代表 |
| --- | --- | --- | --- | --- |
| A. Remote-SSH（拆分式） | 本地原生 | VS Code Server（含 extension host） | SSH 进程隧道，零额外端口 | Remote-SSH 扩展 |
| B. Remote Tunnels（中继式） | 本地或浏览器 | 同 A 的 server | 出站连微软 dev tunnels 中继 | `code tunnel` |
| C. serve-web / code-server（服务式） | 浏览器（远端渲染） | 整个 workbench | HTTP/WebSocket 直连 | code-server、`code serve-web` |

### 1.1 路线 A：Remote-SSH 的完整工作逻辑

这是与 AISC 最相关的模仿对象。核心思想（2019 官方博客）：**VS Code「同时在
两个地方运行」**——把原本单进程的 workbench 拆成两半，重划代码层边界：

- **本地**：渲染器（UI）、主题、语法高亮、键位——「UI 扩展」。
- **远端**：VS Code Server = 不带 UI 的完整后端——extension host、语言服务、
  调试器、文件系统提供者——「workspace 扩展」。Python 补全等直接反映远端
  工具链，路径/二进制兼容问题在远端原地消解。

连接时序（综合官方文档与社区逆向）：

1. 用户 `Remote-SSH: Connect to Host`，扩展用**系统 OpenSSH** 起 `ssh` 子进程
   （因此 `~/.ssh/config`、ProxyJump、跳板、Agent 转发全部原生可用）。
2. 经该 ssh 连接执行 bootstrap：检查远端 `~/.vscode-server/bin/<commit>/`
   是否存在且 commit 匹配；不匹配则下载 server（远端直连 `update.code.visualstudio.com`
   下载，失败可切换为本地下载后经连接传输——`remote.SSH.localServerDownload`）。
3. 以 stdio 模式启动 server，协议握手校验版本（commit）一致。
4. 渲染器经 socket 抽象连接到 **ssh 子进程的 stdin/stdout 隧道**；此后所有
   编辑器协议流量都在这条经过认证的 SSH 会话里，**不开任何额外端口**。
   官方文档原话："All other communication between the server and the VS Code
   client is accomplished through the authenticated, secure SSH tunnel"。
   新版扩展的 server 走 `--stdio` 模式、**不要求 sshd 开 TCP forwarding**；
   社区开源替代（open-remote-ssh）因用 SSH 库的 direct-tcpip 通道反而需要
   `AllowTcpForwarding yes`——stdio 方案对加固环境的可移植性更好。
5. 远端 extension host 起来后打开 workspace；文件、终端、调试、搜索全部
   经远端 server 完成，本地只收渲染数据。
6. 端口转发是**可选叠加**（Ports 面板临时转发 / `~/.ssh/config` 持久
   `LocalForward`），用于访问远端 web 服务——不是连接本身的依赖。

远端最低要求（官方）：SSH server + bash/tar/curl|wget + glibc≥2.17 +
≥1GB RAM——即「能跑 Node 的常规 Linux」。多用户主机可开
`remote.SSH.remoteServerListenOnSocket` 让 server 监听 unix socket 提升隔离。

**工程要点提炼**（对 AISC 有直接参考价值的机制）：

- **按需 bootstrap + 版本对齐**：server 与客户端按 commit 配对，不匹配即
  重装；远端离线/网络受限有本地下载回退路径。
- **stdio 优先于端口**：控制面走 ssh 进程 stdio，规避防火墙/forwarding
  限制；只有数据服务（web 端口）才用转发。
- **认证复用 SSH**：不发明第二套凭据；密码/token 不落盘。
- **UI/服务能力面拆分**：哪些扩展在本地跑、哪些在远端跑有明确分类契约。

### 1.2 路线 B：Remote Tunnels（中继式）

`code tunnel`：远端机器**出站**连接微软 dev tunnels 中继服务；本地 VS Code
桌面（Remote-Tunnels 扩展）或浏览器（vscode.dev）经同一中继连回。优点：
零入站端口、穿 NAT、免暴露 SSH；代价：依赖微软云中继（数据经第三方）、
认证走 GitHub 账号。对 AISC 不采纳——产品哲学是本地凭据自主，引入外部
中继与「凭据只交 cc-switch/官方 CLI」的红线冲突；但哈佛集群的实战（§2）
证明「中继/隧道服务跑在调度器作业里」这个部署形态本身有价值，可换成
自建 SSH 等价物。

### 1.3 路线 C：serve-web / code-server（服务式）

远端把**整个带 UI 的 workbench** 起成 HTTP 服务，浏览器直连。UI 与数据
都在远端，本地只有浏览器。对 AISC 不适用：Workbench 是 Tauri 原生壳 +
WebView，不是可整体服务化的 Web 应用；且浏览器形态会丢终端体验
（哈佛实测 vscode.dev 下 Dev Containers 不可用）。

**结论：AISC 的模仿对象 = 路线 A（Remote-SSH 拆分式）**，B/C 的机制
（中继部署形态、web 端口转发）作为局部借鉴。

## 2. Slurm/PBS 使用场景实况

用户调研诉求（todo.md「调研」节）：「远程调用——增强 cli 的能力，局域网
通信；使用场景主要是 Slurm 工作负载管理器和 PBS 作业管理」。以下为
2025-2026 各超算中心的公开实践（也即「别人怎么在集群上跑 AI 编码
agent / 远程开发」）：

### 2.1 集群环境的硬现实

- **登录节点禁重负载**：Yale YCRC 明文「编码 agent 资源消耗意外地大，
  不要在登录节点跑，要在计算分配内启动」；各中心普遍限制登录会话数
  （哈佛 Cannon 上限 5 个 SSH 会话）。
- **计算节点经调度器分配**：Slurm（sbatch/salloc/srun）或 PBS（qsub/qsub -I）；
  节点临时的、可能无出站网络、共享 FS（NFS/Lustre）。
- **基本没有 Docker**：无 root；哈佛 Dev Containers 只能用 Podman；
  docker-in-docker 不支持。容器化运行时在集群上不可依赖。
- **网络受限**：出站要代理/VPN；微软设备码认证在一些机构被禁。
- **连接韧性是刚需**：哈佛首推「把 tunnel 作为 sbatch 作业提交」——
  网络抖动断连后作业还活着，重连即恢复；交互式 `salloc` + 手起 tunnel
  每换节点要重新认证。
- **SSH 到计算节点**要经登录节点 ProxyCommand（先 ControlMaster 到登录
  节点，再 `salloc` 抢节点 + nc 中转；Windows 客户端不支持该路径）。

### 2.2 业界三种模式（对 AISC 的映射）

| 模式 | 做法 | 出处 | 对 AISC 的含义 |
| --- | --- | --- | --- |
| **M1 agent-on-cluster** | agent 跑在计算分配内（salloc/sbatch 作业里），用户经 SSH/隧道接入 | Yale、Anthropic（long-running Claude 直接用 Slurm 集群） | agent 进程=调度器作业；「runtime」不再是 Docker 容器 |
| **M2 agent-local** | agent 在本地机器，经 SSH 向集群发命令（作业提交、文件操作） | Duke DCC、Aalto Triton 记录的模式之一 | 本地 agent + 远端执行器；不需要远程 CLI |
| **M3 连接服务托管给调度器** | 把「接入服务」（VS Code tunnel）作为 sbatch 作业常驻计算节点 | Harvard Cannon（官方首推） | AISC 的 `aisc serve` 可同样跑在作业里；断连重连语义由调度器兜底 |

**共识规范**：agent 重活在计算分配内跑；用规则约束 agent 的调度器行为
（分区/QOS/资源上限）；连接服务部署要扛断连。

## 3. AISC 现状盘点：本地耦合面清单

对仓库代码逐面核实（2026-09-07 @ `a526fb6`）：

| 面 | 现状 | 远程化的适配度 |
| --- | --- | --- |
| **命令面**（一次性 op） | 8 个 Rust 模块 ~38 处 spawn 本地 pin（runtime.rs 16 处最多），`cli.rs` 统一封装，piped stdin/stdout + JSON envelope | ✅ 高——spawn `(executable, argv)` 换成 `ssh <host> aisc <argv)` 结构上是同构替换；envelope 本就是机器协议（RFC） |
| **终端面**（PTY 流） | `open_session` → `spawn_pipe_session(pin, argv)`（session.rs:424）：sidecar 子进程 stdio 双向流（stdin 写入/stdout+stderr 读出） | ✅ 高——数据面已是「子进程 stdio 流」；换成 ssh 进程即可流式 |
| **终端 resize** | `AISC_RESIZE_FILE` 本地临时文件 + env 传入，sidecar 轮询读（P2/P3 PERF 产物） | ⚠️ 本地 IPC 特有——远程侧读不到本地临时文件，需要 resize 消息经 stdin 带内传（或 ssh 环境下回退旧轮询；P6b 的第二通道本来就是此挂账） |
| **Docker 直连** | `docker_api.rs` Rust 直连本机 named pipe（P4/P6a，稳态 0 spawn） | ⚠️ 远程模式失效——必须降级为「经远端 CLI 中转」；本地模式保留直连优化 |
| **文件面** | `watcher.rs` notify(5) watch 本地 FS；Explorer 缓存；spool 落 `<数据根>/sessions/` | ⚠️ 最大范围放大器——三选：远端 FS API（经通道）/ mutagen 同步（F1 已有）/ 首期砍掉 |
| **svc 网关端口** | 容器 Web 服务经宿主回环 `127.0.0.1:47000-47999` 暴露 | ⚠️ 远端机器的回环——浏览器在本地，需要 ssh -L 动态转发（分配端口时回传建 tunnel） |
| **凭据/Provider** | cc-switch 数据在远端容器/数据根内，本地永不落第二份 | ✅ 哲学天然契合——「本地不保存远端凭据」是本特性卖点 |
| **SSH 基建** | F1：受管 `~/.ssh/config` 别名段、ssh.github.com:443 实战、mutagen 影子目录 | ✅ 直接复用为传输层 |
| **网络服务经验** | F2 host_mcp：Rust 首个本地监听（动态口 + 每进程 token + 白名单） | ✅ 鉴权模式可复制到 serve 模式 |
| **版本协商** | sidecar `cli_version` 门禁 + caps envelope 已存在（KI-3/token 门禁体系） | ✅ 直接对应 VS Code 的 commit 配对机制 |

## 4. 可行性结论

**判定：可行，且架构比 VS Code 当年轻——因为 AISC 的「UI/服务」边界
天生就是拆好的。** 论据：

1. **数据面已是 stdio 进程流**。VS Code 当年要做的大手术是把单进程
   workbench 拆成 renderer/server 两半；AISC 的 Workbench（Tauri UI）与
   aisc CLI（sidecar）**本来就是两个进程、经 stdio + JSON envelope 通信**。
   远程化不改协议，只改「子进程在哪台机器上」：`pin` 换成
   `ssh <alias> aisc ...`。
2. **无扩展生态负担**。VS Code 最复杂的远期资产是「哪些扩展在本地/远端
   跑」的分类契约与双端 marketplace；AISC 没有扩展系统，能力面就是 CLI
   caps envelope——配对机制已存在。
3. **鉴权与凭据模型契合**。SSH 认证即传输认证（VS Code 同款）；token
   模式有 F2 先例；凭据留在远端符合产品红线。
4. **HPC 实战验证了部署形态**（M3）：连接服务跑在调度器作业里、断连重连
   ——`aisc serve` 未来同样可以 sbatch 化。

### 差距与解法（按风险排序）

| # | 差距 | 解法方向 | 风险 |
| --- | --- | --- | --- |
| G1 | resize 走本地临时文件 | stdin 带内 resize 消息（P6b 第二通道顺带落地）；ssh 路径禁用文件回退 | 低，方案已知 |
| G2 | Docker named pipe 直连 | transport 层声明能力：远程模式全部经 CLI 中转；本地保持 P4/P6a | 中——是性能回归点，需要明确降级语义与遥测 |
| G3 | 文件面（watcher/Explorer/spool） | R0 建议三选一裁决：远端 FS API（体验最完整，工作量大）/ mutagen 同步（F1 复用，语义是副本）/ MVP 先砍（终端优先） | 高——决定 R3 体量 |
| G4 | svc 网关端口转发 | 远端 CLI 分配网关口时经协议回传，本地 Rust 对该口建 ssh -L；或 Workbench 打开服务时动态起转发 | 中 |
| G5 | 长驻 serve 模式不存在 | 新增 `aisc serve --stdio`：envelope 请求/响应 + 事件推送复用 /events JSONL（P6b）；连接生命周期、断线重连、多 Workbench 接入 | 中——这是 R1 的主体新代码 |
| G6 | 多机器选择 UI + 机器档案 | 机器管理页（alias 列表、连通性探测、版本配对显示）；F1 受管 ssh config 复用 | 低 |
| G7 | 远端机器前提 | 需远端有 Docker + aisc 可执行文件（VS Code 同款 bootstrap 问题：首连部署/更新 sidecar）| 中——离线回退链已有 S8b/#37 经验可循 |

### MVP 边界建议（R0 立场）

> **已被 D-4/D-5 裁决覆盖（2026-09-07）**：全特性（R1-R4）在 2.1.10 内交付；
> G3 文件面定为远端 FS API（VS Code 权威远端模型）。以下保留作过程记录。

- **R1**：transport 抽象（spawn 面 → trait：Local/Remote）+ `aisc serve --stdio`
  + version/doctor/ps 三命令远程打通 + token 鉴权。
- **R2**：runtime 生命周期 + 终端 PTY 远程流（含 G1 resize 带内化）——
  「远程跑 agent 会话」体验闭环。
- **R3**：文件面（届时三选一裁决）。
- **R4**：svc 端口转发 + 机器管理页（G6）。
- **2.1.10 建议交付 R1+R2**（远程工作站最小可用），R3/R4 视实测重量
  决定本周期收编或推 2.1.11。

## 5. 与 VS Code 的关键差异备忘（防止错误类推）

- VS Code server 是**按需下载的巨型运行时**（Node + 全量后端，commit 配对）；
  AISC sidecar 是**已随 Workbench 发布的静态二进制**（PyInstaller onefile）。
  远端部署问题变成「把 sidecar 推到远端 or 远端自取」——更接近 mutagen
  的 ensure_mutagen_ready 模式（数据根托管副本），比 VS Code 的
  marketplace 依赖简单。
- VS Code 的文件面是「远端 FS provider 一等公民」；AISC 的 Explorer 是
  本地 notify watcher + 缓存。这是 G3 工作量的根源，也是 MVP 建议砍它的
  原因——VS Code 首版 Remote-SSH 同样是先核心后边缘。
- VS Code 用中继（路线 B）解决 NAT 穿透；AISC 场景（自有机器/实验室
  局域网/集群登录节点）SSH 可直达，中继不在需求内。
- **与 F1 SSH 工作区的关系（D-6 修订）**：F1（mutagen 同步，本地代码 +
  远端 runtime）经用户裁决为错误尝试，2.1.10 首阶段剥离封存（见
  f1-strip-plan.md）——本条最初写的「互补并存」作废。远程模式成为唯一
  的 SSH 故事：「远端代码 + 远端 runtime + 本地纯显示」（D-5）。

## 6. Slurm/PBS 判定（D-2 边界确认）

- 集群上**没有 Docker**（M1/M3 实况），而 AISC 的 runtime=Docker 容器
  是全链前提（entrypoint、cc-switch 作用域、toolchain 挂载、svc 网关）。
- agent 上集群的正路是 **runtime 抽象超越 Docker**（runtime=scheduler
  allocation：salloc/sbatch 作业内起 claude/codex，cc-switch 状态放共享
  FS 的工作区目录）。这是一次独立的架构演进，不是「远程 CLI」的增量。
- 但 R1 的 transport 抽象应**与它同向设计**：transport trait 不假设
  「远端=能跑 Docker 的同构机器」，能力探测（caps）里预留 runtime 类型
  字段，避免 2.1.11+ 返工。
- PBS 与 Slurm 同构（qsub/qstat ↔ sbatch/squeue），调研按 Slurm 一并
  覆盖，不单独立项。

## 7. 来源

- 官方：[Remote Development 公告博客（2019-05）](https://code.visualstudio.com/blogs/2019/05/02/remote-development)、
  [Remote-SSH 文档](https://code.visualstudio.com/docs/remote/ssh)、
  [VS Code Server / tunnel CLI 文档](https://code.visualstudio.com/docs/remote/vscode-server)、
  [Remote-SSH 博客（2019-07）](https://code.visualstudio.com/blogs/2019/07/25/remote-ssh)
- 社区逆向：[VSCodium #693（reh server bootstrap、open-remote-ssh 的
  TCP forwarding 依赖）](https://github.com/VSCodium/vscodium/discussions/693)、
  [AWS Toolkit #7061（--stdio server 模式与 sshd 配置）](https://github.com/aws/aws-toolkit-vscode/issues/7061)
- HPC 实践：[Harvard FASRC（sbatch tunnel 首推、登录节点限制、FASSE 无
  salloc）](https://docs.rc.fas.harvard.edu/kb/vscode-remote-development-via-ssh-or-tunnel/)、
  [Yale YCRC AI Coding Tools（agent 跑计算节点）](https://docs.ycrc.yale.edu/ai/aicodingtools/)、
  [Anthropic long-running Claude（Slurm 集群）](https://www.anthropic.com/research/long-running-Claude)、
  [Aalto Triton（agent-on-cluster vs agent-local 两模式）](https://scicomp.aalto.fi/triton/usage/ai-agents/)、
  [Utah CHPC](https://www.chpc.utah.edu/documentation/software/codingagents.php)、
  [NERSC](https://docs.nersc.gov/development/coding-agents/)
- 本仓库代码核实：`workbench/src-tauri/src/{cli,session,pty,runtime,watcher,docker_api}.rs`
  @ `a526fb6`（2026-09-07）
