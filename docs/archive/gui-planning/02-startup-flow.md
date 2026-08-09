# AISC Workbench MVP 启动流程

> 状态：**UX 规范（Proposed）**  
> Domain 依赖：[03-lifecycle-contract.md](./03-lifecycle-contract.md)  
> CLI 依赖：[05-cli-gui-contract.md](./05-cli-gui-contract.md)

## 一、目标与非目标

启动流程必须同时满足：

1. 已知工作区的日常启动只需一次确认。
2. 首次启动不静默选择目录、创建文件、启动容器或 Agent。
3. 技术阻塞与可忽略警告有明确区别。
4. 用户在启动前能看到 workspace、Agent、image、network 和 scope 摘要。
5. 任何失败都能回到可操作状态，不留下未报告的容器或过期 UI。

启动流程不负责：

- 自动安装 Docker 或修改系统权限。
- 自动停止“可能冲突”的其他容器。
- 自动创建 `~/aisc-workspace` 或将任意当前目录视为工作区。
- 自动执行 workspace 内的脚本、包安装或未信任命令。

## 二、启动场景

### 2.1 首次启动

条件：没有有效 Workbench history，也没有 `--workspace` 启动参数。

```text
启动应用
  → 发现并验证 AISC CLI
  → 检查 capability
  → 显示工作区选择页
  → 用户选择目录
  → 执行 workspace/runtime 预检
  → 显示启动摘要
  → 用户确认
  → 创建 Runtime 和第一个 Session
```

首次启动不使用无界面 Quick Start。

### 2.2 Quick Start

条件：已知 canonical workspace，存在用户曾确认的启动偏好。

```text
打开工作区
  → 并行预检和 Runtime 对账
  → 显示单页摘要（推断值可编辑）
  → [启动] / [更改设置]
  → 复用匹配 Runtime 或创建新 Runtime
  → 打开默认 Agent Session
```

Quick Start 的“Quick”表示一次确认，不表示静默执行。

### 2.3 Resume Layout

条件：history 中存在该 workspace 的 runtime ID 与 Tab 元数据。

```text
读取 history
  → aisc runtime list 对账
  → 显示 Runtime 真实状态和上次 Tab 列表
  → [恢复布局] / [空白打开] / [选择其他工作区]
  → 如需先 restart/create Runtime
  → 为选中的 Tab 创建新 Session
```

界面必须显示：“恢复标签布局会启动新的 Agent 会话，不会续接上次终端内容。”

### 2.4 Explicit Setup

用于新 workspace、自定义 image、proxy network、temporary scope 或替换现有 Runtime。它与 Quick Start 使用同一个表单模型，只是默认展开高级字段。

## 三、应用启动状态机

```text
boot
  → discovering_cli
  → negotiating_capabilities
      ├── unsupported → blocked_upgrade
      └── supported
          → loading_history
          → reconciling_runtimes
              ├── no known workspace → workspace_picker
              ├── known workspace → launch_summary
              └── recoverable layout → resume_prompt

workspace_picker
  → preflight
  → launch_summary
  → starting_runtime
  → opening_session
  → workspace_ready

any async state
  ├── cancel → previous stable state
  └── fail → actionable_error → retry/change/back
```

稳定界面状态：

- `blocked_upgrade`
- `workspace_picker`
- `launch_summary`
- `resume_prompt`
- `workspace_ready`
- `actionable_error`

异步过程必须有 operation ID 和 cancellation token。旧 operation 完成时不得覆盖新界面状态。

## 四、环境预检

### 4.1 分类

| 分类 | 语义 | 用户能否继续 |
|---|---|---|
| Hard gate | 必然导致 Workbench 主路径失败 | 不能 |
| Config gate | 当前配置无法启动，可修改配置或执行用户确认的修复 | 修复后继续 |
| Warning | 可启动，但功能可能不完整 | 可以 |
| Info | 用于解释上下文 | 可以 |

### 4.2 检查矩阵

| 检查 | 来源 | 类别 | 操作 |
|---|---|---|---|
| AISC CLI 路径有效且唯一 | 绝对路径执行 `version --format json` | Hard gate | 选择 CLI 或显示安装说明 |
| Workbench capability | version payload | Hard gate | 显示升级 AISC |
| Docker CLI/daemon/权限 | `aisc doctor --format json` + `runtime preflight` | Hard gate | 启动 Docker 或修复权限 |
| workspace 存在且可读写 | Workbench path check + `runtime preflight` | Hard gate | 重新选择或修复权限 |
| image 存在 | `aisc runtime preflight` | Config gate | 选择其他 image 或确认构建 |
| proxy 配置可用 | network=proxy 时 `runtime preflight` | Config gate | 改为 direct 或配置 proxy |
| 已有冲突 project Runtime | `aisc runtime preflight` | Config gate | 复用、停止替换或取消 |
| Provider/auth | 复用 running Runtime 时 `aisc provider current`；新 Runtime 在 ready 后检查 | Warning | 打开 cc-switch/登录，或继续 |
| Git 仓库/分支 | 可选宿主检查 | Info | 仅展示，不阻塞 |

规则：

- Hard gate 不提供“跳过检查”。
- 构建镜像必须由用户点击，使用 `aisc build --events`，可取消且显示真实日志。
- Workbench 不通过匹配 Docker 原始错误文本决定状态，只消费稳定 AISC error code。
- 预检可并行，但每一项必须独立显示 pending/running/pass/warn/fail。
- 首次创建 Runtime 前没有合法 runtime ID，Workbench 不查询或猜测 Provider；启动摘要显示“将在 Runtime 就绪后检查”，Session 打开前后均不得因此成为 hard/config gate。
- preflight 是只读快照；用户确认后 `runtime start` 必须重新验证 workspace/image/proxy 与冲突，UI 不把较早 preflight 当成锁或授权。

### 4.3 AISC CLI discovery

Workbench 不能假设从 Finder、Dock、开始菜单或桌面图标启动时继承交互 shell 的 `PATH`。候选顺序为：

1. 启动参数 `--aisc-cli PATH`。
2. `settings.json` 中用户上次确认的绝对路径。
3. Workbench 进程 `PATH` 中的 `aisc`/`aisc.exe`。
4. 平台已知安装位置：Linux `${XDG_BIN_HOME:-$HOME/.local/bin}/aisc`；macOS `/usr/local/bin/aisc` 与用户 bin；Windows `%LOCALAPPDATA%\Programs\AISC\aisc.exe`、`%LOCALAPPDATA%\AISC\aisc.exe`。
5. 用户通过原生文件选择器指定的 executable。

选择规则：

- 显式参数或已保存路径是 pinned candidate；失效/不兼容时显示 hard gate，不静默换成另一套 AISC。
- 没有 pin 且只发现一个兼容安装时可选择它；发现多个不同安装时要求用户确认，不按版本号猜测。
- 候选必须是平台可执行的 regular file/symlink target，并通过 `version --format json` 和 capability negotiation；只保存确认后的绝对路径。
- 本进程后续所有 control/PTY 命令使用同一个绝对 executable，不再做 PATH 查找；文件身份或路径变化后重新协商。

## 五、工作区选择

### 5.1 候选来源

按优先级展示，不自动确认：

1. `aisc-workbench --workspace PATH` 显式启动参数。
2. Workbench history 中用户曾打开的最近/固定 workspace。
3. 从终端启动 Workbench 时的 cwd，作为建议项显示。
4. 用户通过原生目录选择器选择的目录。

从桌面图标启动时的进程 cwd 不具有产品语义，不用作自动 workspace。

### 5.2 路径规则

- 选择后立即 canonicalize，历史中只保存 canonical absolute path。
- 目录必须存在、可读，对 project scope 还必须可写。
- 符号链接、Windows drive/UNC 和路径大小写归一化通过平台测试明确。
- Workbench 不因选择目录而自动创建 `.aisc/`、`.claude/`、`.codex/` 或 `.cc-switch/`；这些写入只能在用户确认 runtime start 后由 AISC 执行。

## 六、启动配置解析

### 6.1 Runtime 值优先级

```text
本次界面显式选择
  > Workbench 中该 workspace 上次确认的启动配置
  > Workbench 全局偏好
  > 内置默认值
```

内置默认：

```text
image   = super-claude:latest
network = direct
scope   = project
```

Workbench 不把 AISC 尚未接入 `run` 决策的配置字段当作已生效默认值。当 CLI 未来提供结构化 effective runtime defaults 后，再通过 capability 升级本优先级。

### 6.2 Agent 值优先级

```text
本次界面显式选择
  > 该 workspace 上次使用的 Agent
  > Workbench 全局 default_agent
  > claude
```

`.claude/` 或 `.codex/` 目录的存在不足以表示用户偏好，不用于自动选择 Agent。

## 七、启动摘要

摘要屏必须在一个视图中显示：

```text
Workspace  /home/user/project
Agent      Claude Code
Runtime    Reuse running | Start new | Restart stopped
Image      super-claude:latest
Network    Direct
State      Project (saved in workspace)

[Start Claude]  [Change settings]  [Cancel]
```

文案用“State: Project/Temporary”或经用户研究确认的名称，主路径不单独使用未解释的 `scope`。高级详情可显示原始参数。

按钮行为：

- `Start`：只在所有 hard/config gate 通过时启用。
- `Change settings`：就地展开 image/network/state，不跳转到全局设置页。
- `Cancel`：回到 workspace picker/recent list，不产生副作用。

## 八、Runtime 启动进度

Runtime start 不使用伪进度百分比。界面展示真实阶段：

```text
Validating workspace
Checking Docker and image
Creating container
Initializing project state
Starting cc-switch services
Waiting for runtime readiness
Opening Claude session
```

如 CLI 尚不提供子阶段事件，Workbench 只显示“Starting runtime”和经过时间，不猜测内部进度。

取消语义：

1. 用户点击 Cancel 后立即禁用重复点击并显示“Cancelling”。
2. Tauri 取消 CLI 子进程并等待其返回。
3. 调用 `runtime inspect` 确认是否已创建资源。
4. 如 Runtime 已创建，显示真实状态和保留/删除选项，不静默删除。

## 九、持久化 Schema

文件位置由 Tauri `app_config_dir` 解析。以下 JSON 均是有效 JSON，不使用注释。

### 9.1 `settings.json`

```json
{
  "schema_version": 1,
  "aisc_cli_path": null,
  "default_agent": "claude",
  "default_runtime": {
    "image": "super-claude:latest",
    "network": "direct",
    "scope": "project"
  },
  "quit_behavior": "ask_if_sessions_running",
  "restore_layout_prompt": true,
  "remember_window_bounds": true
}
```

### 9.2 `history.json`

```json
{
  "schema_version": 1,
  "revision": 7,
  "workspaces": [
    {
      "path": "/home/user/project",
      "last_used_at": "2026-08-02T12:30:00Z",
      "pinned": false,
      "last_agent": "claude",
      "runtime": {
        "runtime_id": "0e7b7e3b-5c97-4d20-9292-bca647cc940a",
        "image": "super-claude:latest",
        "network": "direct",
        "scope": "project"
      },
      "layout": {
        "active_tab_id": "f0df9f94-fbd8-48aa-88d0-14794173879d",
        "tabs": [
          {
            "tab_id": "f0df9f94-fbd8-48aa-88d0-14794173879d",
            "agent": "claude",
            "title": "Claude",
            "position": 0
          },
          {
            "tab_id": "13533298-01fb-42c2-9bb9-b21f41adefd3",
            "agent": "bash",
            "title": "Bash",
            "position": 1
          }
        ]
      }
    }
  ],
  "window": {
    "width": 1200,
    "height": 800,
    "maximized": false
  }
}
```

强制要求：

- 写入使用同目录临时文件 + fsync + atomic replace。
- `settings.json` 与 `history.json` 分别使用 app config dir 中的跨进程 lock file；锁实现必须覆盖 POSIX/Windows，获取失败或超时不得无锁写入。
- history save 在锁内重新读取磁盘 revision，与调用方 `expected_revision` 比较；一致才写入 `revision + 1`，不一致返回 conflict，由调用方 reload/merge 后有界重试。
- merge 只更新本窗口拥有的 workspace/layout 记录；最近列表、pin 和其他 workspace 的更新不能被整文件旧快照覆盖。窗口几何采用最后一次成功提交值。
- schema 不支持时保留原文件，显示可恢复错误，不用默认值覆盖。
- 文件不包含 Session ID、PTY PID、scrollback、Provider 密钥或认证片段。
- `aisc_cli_path` 为 `null` 或用户确认的绝对 executable 路径；迁移/升级后失效时保留原值并回到 CLI hard gate。

## 十、错误 UI 契约

每个错误界面包含：

1. 用户可理解的一句话摘要。
2. 基于稳定 error code 的一到两个操作。
3. 默认折叠的脱敏技术详情：error code、run ID、CLI version、exit code、stderr 摘要。
4. 明确的 Retry/Back，不将用户困在加载屏。

映射示例：

| Error code | 摘要 | 主操作 |
|---|---|---|
| `AISC_ERR_DOCKER_UNAVAILABLE` | Docker 尚未可用 | 重试检查 |
| `AISC_ERR_PERMISSION_DENIED` | AISC 无法访问 Docker 或工作区 | 查看修复指南 |
| `AISC_ERR_IMAGE_NOT_FOUND` | 所选镜像不存在 | 构建镜像 / 更换镜像 |
| `AISC_ERR_CAPABILITY_UNSUPPORTED` | AISC CLI 版本不支持 Workbench | 升级 AISC |
| `AISC_ERR_RUNTIME_CONFLICT` | 工作区已有不兼容 Runtime | 使用已有 / 停止替换 |
| `AISC_ERR_RUNTIME_NOT_READY` | Runtime 初始化未完成 | 重试等待 / 查看诊断 |
| `AISC_ERR_STATE_LOCK_TIMEOUT` | 另一个 AISC/Workbench 操作正在更新 Runtime 状态 | 等待后重试 / 刷新状态 |

Workbench 不通过 `contains("already in use")` 等文本匹配翻译错误。

## 十一、性能和反馈目标

不把 Docker/image/entrypoint 冷启动时间承诺为固定 3 或 5 秒。MVP 验收可控的用户体验指标：

- 用户操作后 100 ms 内出现状态反馈。
- 本地 settings/history 加载不阻塞首屏。
- 互不依赖的预检并行执行，单项显示自身进度。
- Runtime/Agent 启动显示经过时间、取消和技术详情。
- 记录实测 p50/p95，在 Linux/Windows/macOS 分开设定优化基线。

## 十二、可访问性

- 工作区选择、摘要、错误和恢复对话框均可全键盘操作。
- 焦点移动顺序与视觉顺序一致，Esc 只取消当前非破坏流程。
- Hard gate/error 使用 `role="alert"`，进度变化使用节流的 `aria-live="polite"`。
- 不依赖颜色区分 pass/warn/fail，同时显示图标和文本。

## 十三、验收场景

### 首次启动

- [ ] 无 history 时不自动选择 cwd、不创建目录、不启动容器。
- [ ] 选择 workspace 后显示全部 hard/config gate 和启动摘要。
- [ ] 取消摘要不产生文件或 Docker 副作用。

### Quick Start

- [ ] 已知 workspace 在一个摘要屏中可一次确认启动。
- [ ] 用户可在原地修改 Agent/image/network/state，不进入多步向导。
- [ ] Hard gate 失败时 Start 不可用，且无“强制跳过”。

### Resume Layout

- [ ] running/stopped/not_found/unknown Runtime 分别显示正确操作。
- [ ] 恢复布局创建新 Session ID，不把 history Tab 显示为已运行。
- [ ] 孤儿 Session 默认保留并询问处理，不自动删除。

### 故障与取消

- [ ] CLI 缺失/过旧、Docker 不可用、image 缺失、proxy 缺失、workspace 无权限有稳定错误动作。
- [ ] 从桌面环境启动时无需 shell PATH；零个、一个、多个和已失效 pinned CLI 均进入确定的 discovery 结果。
- [ ] Runtime start/build 取消后通过 inspect 报告真实剩余资源。
- [ ] 旧异步 operation 的返回不覆盖新 workspace 的界面状态。
- [ ] 两个窗口同时更新不同 workspace/history 时不丢记录；同 revision 写入冲突会 reload/merge，不绕过 lock。
