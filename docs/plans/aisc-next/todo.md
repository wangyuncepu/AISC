# AISC Next — 想法与遗留问题

> 轻量 backlog：记录**暂不实现**的想法和**跨阶段遗留**的已知问题。
> 每个条目：来源、日期、上下文/现象、下一步归属阶段。实现时移入对应阶段的
> `00-overview.md` / `acceptance.md`，并在本文件标记完成。

## 想法 / Ideas

### ISO-1 离线安装版做成 ISO 形式

- **来源**：用户，2026-08-16。
- **内容**：离线 NSIS 安装包（当前 `-offline-setup.exe`，内置 Docker Desktop 安装器）
  之外，再产出一个 **ISO 镜像**（含 setup.exe + Docker Desktop Installer.exe + 可选
  WSL 前置组件 + 安装说明），便于 U 盘 / 企业内网批量离线安装。
- **现状**：仅记录，**不实现**。已有 `scripts/build-installer.ps1 -Mode offline`
  产出离线 setup.exe，ISO 可在其上叠一层（如 oscdimg / cdrtfe）打包。
- **归属**：Stage 6 或发布流程（REL-*）评估后再定。

## 遗留问题 / Known issues

### KI-1 向导环境步骤无法实时识别 Docker 就绪（跨阶段遗留）

- **来源**：用户手测，2026-08-16（第 2 轮复测仍复现）。
- **现象**：点击「启动 Docker」→ Docker Desktop 正常启动、引擎可达（同一台机器
  shell 中 `docker version --format {{.Server.Version}}` 返回 `29.7.2`，exit 0）；
  但「欢迎使用 AISC Workbench」环境步骤**始终显示 engine starting**，自动轮询与
  「重新检测」都不反映 ready。手动点「稍后配置」跳过后功能正常。
- **已做修复（未解决）**：
  - `engine_reachable()` 加 `CREATE_NO_WINDOW`（消除探测黑框闪烁）；
  - 移除 180s 阻塞轮询 → 启动后持续 5s 自动轮询；
  - 「重新检测」按钮永不禁用（原被 `loading` 禁用 ≈ 4/5 时间无响应）；
  - env readiness CLI 走全发现（pin > sidecar > PATH），CLI 显示已修复。
- **环境事实（查因线索）**：`C:\Program Files\Docker\Docker\resources\bin` 在
  **Machine PATH**（`GetEnvironmentVariable('Path','Machine')` 含之）；
  `C:\Program Files\Docker\Docker\Docker Desktop.exe` 存在且可手动启动；
  系统 PATH 中 `docker` 解析正常。
- **待查假设（下一个开发阶段重点查因）**：
  1. GUI 进程内 `tokio::process::Command::new("docker")`（CreateProcessW 裸名
     PATH 搜索）是否与 shell 行为不一致 / spawn Err；
  2. `engine_reachable` 仅判 exit code，`docker version` 在无控制台/无 tty 环境下
     是否返回非零或 hang（4s 超时被吞）；
  3. 引擎就绪语义是否应改 `docker info`（版本存在 ≠ daemon 真正响应）而非
     `docker version --format Server.Version`；
  4. 前端 store 状态陈旧 / 自动轮询门控是否有残余 bug。
- **建议**：Stage 6 为 `engine_reachable` 增加诊断（区分 spawn 失败 / 非零退出 /
  超时，并暴露给「诊断」按钮）；必要时在安装应用里打印探测细节。
- **归属**：Stage 6（A-ONB02 续，或 REL-01 诊断）。
