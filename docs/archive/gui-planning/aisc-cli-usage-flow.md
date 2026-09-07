# AISC CLI 当前使用流程与设计优化讨论

> 用途：与 UI/UX 设计师沟通 AISC CLI 当前行为、Workbench 调用链路和后续体验优化方向。
>
> 文档基于 2026 年 8 月 22 日仓库源码、README 和当前 CLI 契约整理。本文描述“当前实现”，不等同于未来设计方案。

## 1. 先说结论

AISC CLI 当前同时承担两类角色：

1. **面向用户的宿主机 CLI**：检查环境、构建镜像、启动容器、进入容器、切换 Provider。
2. **Workbench 的控制面 CLI**：管理 Runtime、Session、Provider、Artifact，并为桌面端提供稳定的 JSON 协议。

因此当前不是一条单一的用户流程，而是两条并行路径：

```text
传统 CLI 用户路径
安装
→ version / doctor
→ build
→ run
→ status / shell / switch
→ stop / restart
```

```text
Workbench 调用路径
选择 Workspace
→ runtime preflight
→ runtime start
→ session open
→ provider / artifact / session list
→ session terminate
→ runtime stop / restart / remove
```

两条路径底层都依赖 Docker 和 Workspace，但对象命名、状态呈现和寻址方式不同。当前最需要设计统一的是“用户看到的对象模型和状态语言”，而不是简单地把所有 CLI 命令做成菜单。

## 2. 当前对象模型

```text
Workspace
└── Runtime
    ├── Session / Tab
    │   ├── Terminal
    │   └── Agent: Claude / Codex / Bash / cc-switch
    ├── Provider
    ├── Artifact
    └── Runtime 状态、日志和诊断

全局或跨 Workspace：
├── AISC data root
├── Network subscription
├── Usage
└── Lifecycle logs
```

### 2.1 对象含义

| 对象 | 当前含义 | 设计上应回答的问题 |
| --- | --- | --- |
| Workspace | 用户打开的代码目录；Runtime 和 Session 的上下文来源 | 用户是在切换项目，还是只是在切换一个运行实例？ |
| Runtime | 一个 Docker 容器及其登记信息；Workbench 通过 UUID v4 标识 | 用户是否需要理解“容器”这个技术概念？ |
| Session | Runtime 内的一次 Agent 进程会话；通常对应一个 Tab | Session 退出后，Tab 是关闭、可恢复还是保留记录？ |
| Agent | `claude`、`codex`、`bash`、`cc-switch` 之一 | Agent 选择和 Session 创建是否应该合并成一个动作？ |
| Provider | 当前 Agent 使用的模型服务配置 | Provider 是全局、Workspace 级还是 Agent 级？ |
| Artifact | Agent 产生或修改的工作区文件事实记录 | 文件本身、文件状态和 Agent 产物记录如何区分？ |

## 3. CLI 入口和输出规则

### 3.1 统一入口

宿主机入口只有 `aisc`，也支持 `python -m aisc`。全局选项可以放在命令前或命令后：

```bash
aisc --format json doctor
aisc doctor --format json
aisc --aisc-root /path/to/bundle version
```

主要全局选项：

| 选项 | 当前行为 | 设计含义 |
| --- | --- | --- |
| `--format text` | 默认，人类可读输出 | 适合终端用户和调试 |
| `--format json` | 输出 `aisc.cli/v1` JSON envelope | Workbench 和脚本使用 |
| `--no-color` | 禁用 ANSI 颜色 | 适合日志和无颜色终端 |
| `--aisc-root PATH` | 显式指定 AISC bundle/resource root | 主要用于便携版、开发和故障恢复 |
| `--events` | 仅 `build`、`run` 支持 JSONL 事件流 | 用于长操作进度，不是所有命令的通用进度接口 |

`--format json` 和 `--events` 互斥。JSON 模式下 stdout 只保留协议数据，Docker 输出转发到 stderr。

### 3.2 交互式与机器命令

| 类型 | 命令 | 当前特点 |
| --- | --- | --- |
| 交互式 | `build`、`run`、`shell`、`switch`、`provider set-key` | 直接使用终端输入输出；部分命令打开向导或 TUI |
| 机器可读 | `version`、`doctor`、`config`、`runtime`、`session`、`artifact` 等 | 支持 JSON envelope |
| 长操作事件 | `build --events`、`run --events` | 输出带 `seq`、`run_id`、事件类型和最终 terminal event 的 JSONL |
| text-only | `session open` | PTY 数据不能和 JSON 混在一起，Agent 的终端输出就是 stdout/stderr |
| Secret 输入 | `cc-switch add/edit`、`network subscription import` | Secret 或订阅 URL 通过 stdin 传递，不进入 argv |

设计上不要假设所有命令都能直接映射为“按钮点击后等待一个 JSON 结果”。交互式会话、长操作和普通查询是三种不同的交互模型。

## 4. 传统 CLI 用户流程

### 4.1 安装后首次验证

```text
安装或解压
→ 新开终端
→ aisc version
→ aisc doctor
→ 根据诊断修复 Docker / 权限 / bundle / 工作区问题
```

常用命令：

```bash
aisc version
aisc doctor
aisc doctor --format json
```

`version` 用于确认 CLI、Python、bundle 和声明依赖版本。`doctor` 是宿主机只读诊断，当前检查 Docker、权限、buildx、TUN、Git、AISC root 和目录可写性；Docker 缺失时还可能进入自动安装引导。

设计重点：

- 首次启动不要让用户先理解 bundle、daemon、buildx、TUN 等术语；
- 诊断结果应按“可继续 / 需要处理 / 可稍后处理”分组；
- 每个失败项都需要有下一步动作，例如重试、打开设置、查看详情或跳过；
- `doctor` 的技术详情适合作为可展开区域，不应成为首屏主任务。

### 4.2 构建镜像

```text
aisc build
→ 解析 AISC root
→ 读取 config/versions.env
→ 解析 cc-switch 版本
→ 生成 Docker build plan
→ Docker preflight
→ 构建镜像
→ 输出完成或失败结果
```

常用命令：

```bash
aisc build
aisc build --tag team-image:2.1.4
aisc build --no-cache --pull
aisc build --dry-run
aisc build --events
```

当前行为：

- 裸 `aisc build` 在交互文本终端中会打开构建向导；
- 指定 `--tag`、`--no-cache`、`--pull` 或 `--dry-run` 时直接按参数执行；
- 默认镜像为 `super-claude:latest`；
- `--dry-run` 展示 Docker 计划且不调用 Docker；
- 文本模式实时输出构建日志；
- JSON 模式将 Docker 输出放到 stderr；
- `--events` 输出 `build.start`、`build.plan`、`build.output`、`build.complete` 等事件。

设计重点：

- “构建镜像”对用户应表现为一次可理解的环境准备，而不是裸 Docker 命令；
- 需要明确区分“准备中、下载中、构建中、已完成、失败、取消”；
- 构建日志应可查看，但不能抢占主流程；
- 已有同名镜像时，应解释“将覆盖现有镜像”及是否建议重新构建；
- 失败页需要区分资源缺失、Docker 不可用、网络下载失败和构建失败。

### 4.3 启动容器

```text
选择工作区
→ 选择镜像
→ 选择网络模式
→ 规划容器参数
→ Docker preflight
→ 创建并启动容器
→ 登记 Runtime/Container
→ 进入交互终端或返回结果
```

常用命令：

```bash
aisc run
aisc run --workspace /path/to/project
aisc run --network proxy
aisc run --keep-alive --label work
aisc run --non-interactive
aisc run --dry-run
```

默认值和重要开关：

| 项目 | 当前行为 |
| --- | --- |
| 镜像 | `super-claude:latest` |
| 工作区 | 当前目录，挂载到容器 `/root/app` |
| 网络 | `direct` |
| 交互 | 文本模式默认 `-it` |
| 生命周期 | 默认容器退出后 `--rm`；`--keep-alive` 保留容器 |
| 容器名 | `<name>-<8位十六进制>`，`--name` 是前缀 |
| 寻址标签 | `--label` 是 AISC registry 标签，不是 Docker label |
| 作用域 | 容器启动后选择 `temporary` 或 `project`，默认 `project` |
| Agent | 容器初始化后可选择 `bash`、`claude`、`codex` 或 `cc-switch`，默认 `bash` |

代理网络额外要求 TUN、`NET_ADMIN` 和可读的 Mihomo 配置。`--profile proxy` 只是旧兼容别名，不是权限 Profile。

设计重点：

- 工作区、镜像、网络和持久化作用域应组成一个“启动摘要”；
- 不要把 `--keep-alive`、`--non-interactive`、`--dry-run` 这种技术参数直接暴露为难以理解的选项；
- `temporary` / `project` 应翻译成用户能理解的持久化选择；
- 容器启动中的实时阶段需要可取消；
- Runtime 冲突、镜像不存在、Docker 未启动和工作区无权限要有不同恢复路径。

### 4.4 运行中的容器管理

```text
aisc run
→ 容器运行中
→ ps / status 查看
→ shell 进入容器
→ switch 或 provider set-key 修改 Provider
→ restart 重新启动
→ stop 停止并清理登记
```

常用命令：

```bash
aisc ps
aisc status
aisc status --label work
aisc shell --label work
aisc switch --label work
aisc switch --label work --quick deepseek
aisc restart --label work
aisc stop --label work
```

容器目标解析顺序：

```text
显式 --name
→ 唯一匹配的 --label
→ registry 默认目标
→ 唯一登记容器
→ 多个候选时要求用户明确选择
```

设计重点：

- “当前 Runtime”必须始终可见，不能让用户记忆容器名；
- 多工作区、多 Runtime 时，label 机制应被 UI 重新表达为项目或工作区上下文；
- `stop`、`restart`、`remove` 的影响范围和是否保留数据要明确；
- stale、exited、missing、running 等状态应有统一语言，而不是分别来自 Docker 和 registry 的技术词。

## 5. Workbench 控制面流程

Workbench 不直接把旧的 `aisc run` 当作全部生命周期接口，而是使用带 UUID 的 Runtime/Session 命令族。

### 5.1 Runtime 启动

```text
Workbench 创建 runtime_id
→ aisc runtime preflight
→ 展示检查结果和推荐动作
→ 用户确认启动
→ aisc runtime start
→ 返回 Runtime snapshot
→ 创建或恢复 Session Tab
```

预检命令：

```bash
aisc runtime preflight \
  --runtime-id <UUID-v4> \
  --workspace /path/to/project \
  --image super-claude:latest \
  --network direct \
  --scope project \
  --owner workbench \
  --format json
```

预检是只读的，主要检查：

- Docker 是否可用；
- Workspace 是否可用；
- 镜像是否存在；
- 网络配置是否满足；
- Runtime 是否有冲突。

返回的数据包括 `can_start`、`recommended_action`、逐项 `checks`、匹配 Runtime 和冲突信息。

启动命令：

```bash
aisc runtime start \
  --runtime-id <UUID-v4> \
  --workspace /path/to/project \
  --image super-claude:latest \
  --network direct \
  --scope project \
  --owner workbench \
  --format json
```

启动结果包含 Runtime ID、容器名/容器 ID、状态、是否 ready、是否复用、镜像、网络和 scope 等信息。

设计重点：

- Preflight 和 Start 必须在视觉上是两个阶段：检查阶段不应让用户误以为已经启动；
- `can_start=false` 时要直接给出推荐动作；
- “复用已有 Runtime”和“创建新 Runtime”应是清晰的二选一或自动策略；
- 启动结果不应只显示容器 ID，应该显示项目、Agent 和下一步动作。

### 5.2 Session / Tab 生命周期

```text
Runtime ready
→ 生成 session_id
→ aisc session open
→ 绑定 Terminal Tab
→ Agent 运行
→ 用户关闭、Agent 退出或异常断开
→ session terminate / list
```

打开会话：

```bash
aisc session open \
  --runtime-id <UUID-v4> \
  --session-id <UUID-v4> \
  --agent claude \
  --workspace /path/to/project
```

允许的 Agent：

```text
claude | codex | bash | cc-switch
```

`session open` 是 text-only 交互命令，CLI 会通过 Docker exec 打开 PTY，Agent 的退出码就是命令退出码。它不支持把终端字节流包装进 JSON。

会话查询和终止：

```bash
aisc session list \
  --runtime-id <UUID-v4> \
  --workspace /path/to/project \
  --format json

aisc session terminate \
  --runtime-id <UUID-v4> \
  --session-id <UUID-v4> \
  --workspace /path/to/project \
  --grace 5 \
  --format json
```

设计重点：

- Tab 的状态应明确区分 starting、ready、running、exited、failed、disconnected、terminating；
- 关闭 Tab、结束 Session、停止 Runtime 是三个不同动作，确认文案和影响范围必须不同；
- Session 退出后是否保留 Tab、输出和 Artifact 记录需要统一规则；
- 终端是主区域，Session 的技术状态应通过 Tab 状态、状态抽屉和可恢复动作表达。

### 5.3 Runtime 运行中管理

```bash
aisc runtime list --workspace /path/to/project --format json
aisc runtime inspect --runtime-id <UUID-v4> --workspace /path/to/project --format json
aisc runtime stop --runtime-id <UUID-v4> --workspace /path/to/project --grace 10 --format json
aisc runtime restart --runtime-id <UUID-v4> --workspace /path/to/project --format json
aisc runtime remove --runtime-id <UUID-v4> --workspace /path/to/project --format json
```

当前语义：

| 命令 | 当前影响 |
| --- | --- |
| `preflight` | 只读检查，不创建 Runtime |
| `start` | 创建或复用容器并登记 Runtime |
| `list` | 列出 Runtime，并与 Docker 状态对账 |
| `inspect` | 查看单个 Runtime |
| `stop` | 停止 Runtime，保留容器和元数据 |
| `restart` | 按原始配置重启 |
| `remove` | 删除容器和 registry；运行中默认拒绝，`--force` 强制删除 |

## 6. Provider、网络、Artifact 和支持流程

### 6.1 Provider

当前存在两层 Provider 接口：

1. **旧的交互路径**

   ```bash
   aisc switch --label work
   aisc switch --label work --quick deepseek
   aisc provider set-key deepseek --label work
   ```

2. **Workbench 的 cc-switch 数据面**

   ```bash
   aisc cc-switch list --runtime-id <UUID-v4> --agent claude --format json
   aisc cc-switch add --runtime-id <UUID-v4> --agent claude --format json
   aisc cc-switch edit <PROVIDER_ID> --runtime-id <UUID-v4> --agent claude --format json
   aisc cc-switch switch <PROVIDER_ID> --runtime-id <UUID-v4> --agent claude --format json
   aisc cc-switch delete <PROVIDER_ID> --runtime-id <UUID-v4> --agent claude --confirm --format json
   aisc cc-switch fetch-models <PROVIDER_ID> --runtime-id <UUID-v4> --agent claude --format json
   ```

新增和编辑请求通过 stdin 传入 JSON，API Key 等 Secret 不放进命令行参数。输出为脱敏 Provider snapshot。

此外：

```bash
aisc provider current \
  --runtime-id <UUID-v4> \
  --agent claude \
  --workspace /path/to/project \
  --format json
```

用于读取当前 Provider、路由模式和认证状态。

设计重点：

- 旧 `switch`、`provider set-key` 与新的 `cc-switch` 是否需要在 UI 中合并；
- 新增 Provider 应区分简单预设模式和自定义模式；
- Secret 的填写、保存成功、验证失败和切换失败需要不同反馈；
- 当前 Provider 必须在 Agent/Session 上下文中可见；
- Provider 删除是高风险动作，需要明确当前使用关系和确认范围。

### 6.2 网络订阅和用量

网络订阅是全局配置，敏感 URL 和完整订阅内容通过 stdin 传递：

```bash
aisc network subscription import
aisc network subscription import-file
aisc network subscription refresh
aisc network subscription show
aisc network subscription clear --confirm
```

查看 Provider 用量：

```bash
aisc usage overview --range today
aisc usage overview --range 7d
aisc usage overview --range 30d --workspace /path/to/project
```

当前可以查看订阅状态、工作区、Provider、请求数、成功数、Token 和费用估算。

设计重点：

- 网络订阅属于“环境配置”，不应与 Runtime 的网络模式混为同一层；
- 订阅 URL、剩余流量、过期时间和代理是否可用是不同状态；
- Usage 更接近监控/成本视图，不应阻塞主终端工作流；
- 空数据、缓存数据和实时数据需要明显区分。

### 6.3 Artifact

Agent 产生或修改文件时，可以记录事实：

```bash
aisc artifact record \
  --runtime-id <UUID-v4> \
  --session-id <UUID-v4> \
  --agent claude \
  --path docs/result.md \
  --action created \
  --kind deliverable \
  --workspace /path/to/project \
  --format json
```

查询：

```bash
aisc artifact list --workspace /path/to/project --format json
aisc artifact inspect --artifact-id <UUID> --workspace /path/to/project --format json
aisc artifact clear-session --runtime-id <UUID-v4> --session-id <UUID-v4> --workspace /path/to/project
```

Artifact registry 是宿主 data root 中的 Session-scoped 事实记录，当前设计上不直接修改 Workspace 文件。

设计重点：

- Artifact 是“Agent 做过什么”的可追踪记录，不等同于文件浏览器；
- 需要区分文件存在状态、Agent 动作和用户可执行动作；
- 产物列表适合与 Explorer 联动，但不应让用户误以为记录本身就是文件；
- rename、delete、missing、duplicate 等状态需要统一呈现。

### 6.4 诊断和生命周期日志

```bash
aisc data-root doctor
aisc data-root migrate --dry-run
aisc data-root migrate
aisc data-root rollback

aisc logs show
aisc logs show --source ui
aisc logs path
```

`data-root` 负责数据根诊断、旧布局迁移和回滚；`logs` 提供跨 CLI、应用和 UI 的 secret-free 生命周期事件尾部。

这些命令更适合放在 Settings / Diagnostics，而不是主工作区一级导航。

## 7. 配置和持久化边界

### 7.1 AISC root 与 data root

这是两个不同概念：

| 概念 | 作用 |
| --- | --- |
| AISC root / bundle | 包含 `VERSION`、`container/Dockerfile`、`config/versions.env` 等构建资源 |
| data root | 保存 Runtime、Session、Artifact、日志等运行时状态 |
| Workspace | 用户代码和项目作用域配置 |

AISC root 查找顺序：

```text
--aisc-root
→ AISC_ROOT
→ 冻结可执行文件旁的 aisc-bundle
→ 当前目录向上查找 Git 仓库
→ editable 安装包源码祖先目录
```

data root 默认位置：

| 平台 | 默认位置 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\AISC\data` |
| Linux / macOS | `$XDG_DATA_HOME/aisc/data`，否则 `~/.local/share/aisc/data` |

`AISC_DATA_ROOT` 可作为绝对路径覆盖，但不能与 Workspace 重叠。当前 Runtime registry 使用 data root 下按 Workspace hash 分隔的目录；旧的 `<workspace>/.aisc` 状态会在过渡期被采纳。

### 7.2 Workspace 配置

```text
内置默认值
→ 用户配置
→ Workspace 配置
```

配置命令：

```bash
aisc config validate --workspace /path/to/project
aisc config effective --workspace /path/to/project
aisc config show --workspace /path/to/project
```

当前配置命令只负责校验和展示合并结果，不负责通过 `defaults.profile` 或 `defaults.network` 改变 `aisc run` 的参数决策；实际运行行为仍由命令行参数控制。

设计重点：

- 设置页需要区分“当前有效值”和“可以改变运行行为的设置”；
- 不能把尚未接入运行决策的配置项设计成已经生效的开关；
- data root、AISC root、Workspace 配置和项目内 `.claude/.codex/.cc-switch` 状态需要有清晰归属。

## 8. 当前体验问题

### P0：信息架构和生命周期

1. `run` 与 `runtime start` 都能启动容器，但面向对象、ID、持久化和返回结果不同。
2. `run/status/shell/switch/stop` 使用 name/label 寻址，Workbench 使用 runtime UUID；用户容易把容器、Runtime、Workspace 混为一谈。
3. `run` 中的 scope、Agent 选择、网络模式和 keep-alive 与 Workbench 的 Runtime/Session 概念没有完全统一。
4. 关闭 Tab、终止 Session、停止 Runtime、删除 Runtime 的影响边界需要明确区分。
5. Preflight、启动中、Ready、Stale、Exited、Failed、Disconnected 等状态目前分散在 CLI、Docker、registry 和 UI。

### P1：操作和反馈

1. 构建、启动、Provider 配置、订阅导入都可能是长操作，但进度模型不统一。
2. `--format json`、`--events`、text-only PTY 是合理的技术边界，但没有转译成统一的产品反馈语言。
3. 多容器寻址依赖 label 和默认目标，适合脚本但不适合普通用户记忆。
4. Provider 旧交互路径和 cc-switch 数据面并存，入口和权限边界不够直观。
5. `data-root`、`logs` 和 `doctor` 能提供恢复信息，但当前更像开发者工具，没有形成用户可理解的恢复向导。

### P2：高级能力

1. Usage、Network、Artifact 和 lifecycle logs 的全局/Workspace/Runtime 归属需要统一。
2. CLI 错误码、UI 状态和用户动作之间需要一套映射表。
3. 复杂操作需要支持取消、重试、查看详情和回到上一步。

## 9. 建议的设计优化方向

### 9.1 统一用户语言，保留技术实现

建议在 UI 中使用：

```text
Workspace 项目
Runtime 运行环境
Session 会话
Agent 助手
Provider 模型服务
Artifact 产物
```

CLI 的 `container`、`registry`、`runtime_id`、`label`、`scope` 等技术字段放入详情层，不作为主要操作标题。

### 9.2 把启动流程设计成一个分阶段流程

建议统一成：

```text
选择项目
→ 选择 Agent / Provider
→ 选择网络和持久化方式
→ 环境预检
→ 启动或复用 Runtime
→ 创建 Session
→ 进入 Terminal
```

每一步都应有：

- 当前动作；
- 可继续条件；
- 失败原因；
- 推荐修复动作；
- 取消或返回路径；
- 技术详情入口。

### 9.3 Runtime 与 Session 分层

建议视觉上：

- Workspace 负责项目切换；
- Runtime 负责运行环境状态和共享资源；
- Session/Tab 负责具体 Agent 工作；
- Terminal 是 Session 的主内容；
- Provider 是当前 Agent 的配置上下文；
- Artifact 是 Session 产生的结果记录。

不要把“关闭 Tab”直接等同于“停止 Runtime”。

### 9.4 统一状态矩阵

建议至少统一以下状态：

```text
Unavailable
Checking
Blocked
Starting
Ready
Running
Stopping
Stopped
Exited
Disconnected
Stale
Failed
Removing
Removed
```

每个状态都需要定义：

1. 用户看到的名称；
2. 颜色和图标；
3. 是否允许继续操作；
4. 主恢复动作；
5. 是否需要确认；
6. 是否保留日志、Session 和 Artifact。

### 9.5 统一长操作反馈

`build`、`runtime start`、`session open`、Provider 保存、订阅刷新建议统一采用：

```text
当前阶段
→ 阶段进度或不确定进度说明
→ 可取消
→ 可展开日志
→ 失败后重试 / 修改设置 / 打开诊断
```

不要强行把 PTY 会话伪装成普通进度条；Agent Terminal 应保留终端交互模型。

### 9.6 把 CLI 技术错误转译为动作

建议 UI 错误结构：

```text
发生了什么
→ 影响是什么
→ 用户现在可以做什么
→ 技术详情
```

例如：

| CLI 情况 | UI 主文案方向 | 推荐动作 |
| --- | --- | --- |
| Docker daemon 不可用 | 无法启动运行环境 | 启动 Docker / 重试 / 打开 Doctor |
| Image not found | 运行镜像尚未准备好 | 构建镜像 / 选择已有镜像 |
| Runtime conflict | 当前项目已有冲突的运行环境 | 查看现有 Runtime / 复用 / 强制移除 |
| Workspace 不可写 | 项目目录无法用于运行 | 选择其他目录 / 查看权限 |
| Provider 未配置 | Agent 尚未配置模型服务 | 添加 Provider / 选择其他 Provider |
| Session exited | Agent 会话已结束 | 查看输出 / 重新打开 / 关闭 Tab |
| Registry stale | 运行记录与 Docker 状态不一致 | 刷新 / 对账 / 清理记录 |

## 10. 建议与设计师重点讨论的问题

1. 用户是否需要看到 Runtime，还是只看到“项目运行环境”？
2. `run` 和 `runtime start` 是否在产品层合并为同一个启动流程？
3. Workspace、Runtime、Session、Tab 的层级和视觉语言如何区分？
4. Agent 选择应发生在 Runtime 启动前，还是 Session 创建时？
5. Provider 是全局设置、Workspace 设置，还是每个 Agent Session 的上下文？
6. “复用已有 Runtime”和“启动新 Runtime”如何表达最容易理解？
7. 关闭 Tab、结束 Session、停止 Runtime、删除 Runtime 的确认层级如何设计？
8. Preflight 是默认展示完整检查，还是只展示“可启动 / 不可启动”？
9. 构建镜像是否应成为首次启动流程的一部分，还是单独的设置任务？
10. 网络订阅、网络模式和 Provider 路由如何避免概念混淆？
11. Artifact 列表与文件 Explorer 应该如何联动？
12. 哪些技术详情需要常驻，哪些应该放进状态抽屉或诊断页？

## 11. 建议的设计交付物

第一阶段优先交付以下内容：

1. Workspace → Runtime → Session 的信息架构图；
2. 首次启动和已有 Runtime 复用流程；
3. Runtime/Session 状态矩阵；
4. 启动失败、Provider 未配置、Docker 不可用、Runtime 冲突的恢复稿；
5. Compact / Standard / Wide 三种窗口布局；
6. WorkspaceBar、Runtime 状态区、Session Tab、Terminal、Status Drawer 的交互稿；
7. 旧 CLI 用户路径和 Workbench 路径的统一命名方案。

第二阶段再细化：

1. Provider 表单和 Secret 状态；
2. Network / Usage；
3. Explorer / Artifact；
4. Settings / Doctor / Logs；
5. 键盘导航、焦点、无障碍和中英文长文案。

## 12. 当前实现参考

核心实现位置：

- CLI 参数树与分发：[src/aisc/cli/main.py](../../src/aisc/cli/main.py)
- JSON envelope 和 JSONL 事件：[src/aisc/cli/output.py](../../src/aisc/cli/output.py)
- 传统构建与运行：[src/aisc/cli/commands/build.py](../../src/aisc/cli/commands/build.py)、[src/aisc/cli/commands/run.py](../../src/aisc/cli/commands/run.py)
- Runtime 生命周期：[src/aisc/cli/commands/runtime.py](../../src/aisc/cli/commands/runtime.py)
- Session 生命周期：[src/aisc/cli/commands/session.py](../../src/aisc/cli/commands/session.py)
- Artifact 事实协议：[src/aisc/cli/commands/artifact.py](../../src/aisc/cli/commands/artifact.py)
- Provider 与 cc-switch：[src/aisc/cli/commands/provider.py](../../src/aisc/cli/commands/provider.py)、[src/aisc/cli/commands/cc_switch.py](../../src/aisc/cli/commands/cc_switch.py)
- 数据根和迁移：[src/aisc/cli/commands/data_root.py](../../src/aisc/cli/commands/data_root.py)
- 面向用户的命令说明：[README.md](../../README.md)
