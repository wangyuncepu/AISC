# AISC Workbench MVP 总览

> 产品决策：**Accepted**  
> 实施基线：**Proposed**  
> 基线日期：2026-08-02  
> 目标产物：AISC Workbench Preview

## 一、如何使用本文档集

`docs/gui-planning/` 是 AISC Workbench MVP 的单一规划入口。文档职责如下：

| 文档 | 职责 | 规范性 |
|---|---|---|
| [00-overview.md](./00-overview.md) | 产品决策、MVP 边界、架构概览和文档导航 | 产品 SSOT |
| [01-risk-analysis.md](./01-risk-analysis.md) | 风险登记、缓解措施和阶段门 | 说明性 |
| [02-startup-flow.md](./02-startup-flow.md) | 首次启动、快速启动、恢复布局和环境检查 | UX 规范 |
| [03-lifecycle-contract.md](./03-lifecycle-contract.md) | Workspace/Runtime/Session/Tab 状态机与不变量 | Domain 规范 |
| [04-observability.md](./04-observability.md) | 状态模型、刷新、降级和 MVP 展示 | UI 状态规范 |
| [05-cli-gui-contract.md](./05-cli-gui-contract.md) | CLI 控制面、PTY 数据面和稳定错误契约 | 技术 SSOT |
| [06-implementation-plan.md](./06-implementation-plan.md) | 代码切片、依赖、测试和 Definition of Done | 执行基线 |

冲突处理顺序：

1. 产品范围冲突以本文档为准。
2. Runtime/Session 状态冲突以 `03-lifecycle-contract.md` 为准。
3. CLI/PTY 行为冲突以 `05-cli-gui-contract.md` 为准。
4. 伪代码和 UI 示意均为非规范性，不得覆盖不变量与验收门。

## 二、产品定位

**正式名称：** AISC Workbench（AISC 工作台）

**一句话定义：** 面向容器化 AI 编程 Agent 的桌面开发工作台，让用户围绕项目启动、观察和管理 Claude Code、OpenAI Codex 及后续 Agent。

AISC Workbench 不是：

- AISC 命令的图形包装。
- 与 Windows Terminal/Tabby 竞争主题和标签功能的通用终端。
- 重做 Claude/Codex 交互层的聊天应用。
- Docker Dashboard 或不完整的 IDE。

AISC Workbench 的独特价值是把普通终端不理解的 AISC 上下文变成可见、可操作、可恢复的产品状态：

- 当前 workspace 与文件边界。
- Agent Session 属于哪个 runtime。
- runtime 的 image、network、scope 和真实存活状态。
- 活动 Agent 实际使用的 Provider、路由模式和认证状态。
- 多个 Agent 是否共享并修改同一工作区。

## 三、对象模型

```text
AISC Workbench
└── Workspace
    ├── Runtime
    │   ├── immutable config: workspace/image/network/scope
    │   ├── Docker container
    │   └── zero or more Sessions
    │       ├── Claude
    │       ├── Codex
    │       ├── Bash
    │       └── cc-switch
    └── UI layout
        └── Tabs (Session views)
```

核心不变量：

1. Workspace 是一级对象，Session 是二级对象，Tab 只是 UI 视图。
2. 一个 Session 只属于一个 Runtime，不在 Runtime 之间迁移。
3. 同一 canonical workspace 在 MVP 中最多一个 `project` Runtime。
4. Session 继承 Runtime 的 image/network/scope，不单独申请这些配置。
5. Runtime 停止时其中所有 Session 终止。
6. 关闭 Tab 不等于停止 Runtime。
7. Workbench 历史只保存工作区和布局元数据，不保存终端 scrollback 或密钥。

## 四、设计原则

1. **Terminal-first, not terminal-only**：保留 Agent CLI 原生交互，GUI 负责启动、上下文、状态与生命周期。
2. **Project-first**：用户首先进入项目，再选择 Agent；新增 Agent 不改变信息架构。
3. **让隐式状态可见**：只展示真实、有来源、有观察时间的状态；过期时显示 stale/unknown。
4. **渐进披露**：新用户看到人类可理解的 Environment，高级用户再展开容器 ID、原始错误和实际命令。
5. **始终保留逃生舱**：提供 Bash、cc-switch、原始诊断和命令详情，不把用户锁进点击流程。
6. **安全且不意外破坏**：不静默创建工作区、构建镜像、停止容器或持久化终端内容。

## 五、MVP 用户闭环

```text
启动 Workbench
  → 选择已知工作区或打开新目录
  → 能力协商和环境预检
  → 确认 Agent + Runtime 摘要
  → 启动或复用 Runtime
  → 打开 Agent Session
  → 持续观察当前上下文
  → 关闭 Session、保留 Runtime 或显式停止 Runtime
  → 下次启动对账 Runtime 并恢复布局
```

关键语义：

- **Quick Start** 是“显示推断结果后一次确认”，不是无界面静默启动。
- **Resume Layout** 是重建标签并打开新 Session，不是重连原 PTY。
- **Close Session** 只确定性结束一个 Agent/Shell 会话。
- **Stop Runtime** 会结束该 Runtime 中的全部 Session，必须明确确认。
- **Quit Workbench** 默认保留 Runtime 运行，不做崩溃时不可依赖的自动清理承诺。

## 六、MVP 范围

### 6.1 必须交付

- 工作区选择、最近历史和 canonical path 验证。
- AISC CLI capability、Docker、workspace、image 和 proxy 配置预检。
- 显式 Agent、scope、network 和 image 摘要。
- Runtime preflight/start/list/inspect/stop/restart/remove 及崩溃后对账。
- Claude、Codex、Bash、cc-switch 多 Session 标签。
- PTY byte stream、resize、Ctrl+C/Ctrl+Z/EOF、中文输入、粘贴与确定性关闭。
- Workspace、Runtime、活动 Agent、Provider route、Network、Scope 最小可观察性。
- schema-versioned 的 GUI 偏好与布局历史，原子写入和迁移。
- Linux x86_64、Windows x86_64、macOS arm64 的契约 smoke test 与发布检查。

### 6.2 明确不做

- 活 PTY 跨 Workbench 重启恢复。
- 分屏、远程 SSH、插件系统和终端录制。
- 文件浏览器、内置编辑器、Git 历史和调试器。
- Provider 密钥读取/展示和完整 Provider GUI 编辑器。
- CPU/内存/网络图表和 Docker Dashboard。
- 全量快捷键自定义、大量主题和 OS 级 global shortcut。
- 同一 workspace 的多个 project Runtime。

## 七、技术架构决策

### 7.1 技术栈

| 层 | 选型 | 责任 |
|---|---|---|
| Desktop shell | Tauri 2 + Rust | 进程、PTY、本地文件、窗口与安全边界 |
| UI | Vue 3 + TypeScript + Vite | 工作区、标签、状态、错误与设置 |
| Terminal | xterm.js + FitAddon + SearchAddon | VT 渲染、搜索和选择 |
| PTY | portable-pty | 宿主交互子进程和跨平台 PTY |
| Container control | AISC CLI | Docker、registry、scope、Provider 与稳定错误的唯一控制面 |

MVP 不在 Workbench 引入 Bollard。Docker 性能不是此边界的主要瓶颈，避免双控制面比减少一次 CLI 进程更重要。

### 7.2 控制面与数据面

```text
结构化控制：
Vue -> Tauri invoke -> aisc runtime/provider ... --format json -> aisc.cli/v1

长任务进度：
Vue <- Tauri Channel <- aisc build --events <- aisc.cli/v1 JSONL

交互终端：
xterm.js <-> Tauri Channel <-> portable-pty <-> aisc session open <-> docker exec PTY
```

- Workbench 不直接写 `<aisc-root>/.aisc/containers.json`。
- Workbench 不从 AISC 人类文本推断状态；普通控制命令使用 JSON envelope，长任务只使用已协商的 JSONL event contract。
- Workbench 不向前端暴露任意 shell 或任意文件读写。
- 终端输出以 bytes + sequence 传递，不通过高频全局字符串 Event。

## 八、状态所有权

| 状态 | 唯一 writer | Workbench 获取方式 |
|---|---|---|
| Docker 容器与 AISC registry | AISC CLI | `aisc runtime ... --format json` |
| Runtime 实际状态 | Docker，由 AISC CLI 观察 | inspect/list 轮询与操作结果 |
| Session 宿主 PTY | Tauri backend | 内存 supervisor + Session event |
| Session 容器内进程 | AISC session wrapper | `session list/terminate` |
| Provider/路由 | cc-switch | `aisc provider current` 脱敏元数据 |
| GUI 偏好与布局 | Workbench | Tauri app config dir 中的 schema-versioned JSON |

缓存从不是 source of truth。每个外部状态必须带 `observed_at`；过期或查询失败时显示 `stale/unknown`。

## 九、持久化边界

Workbench 使用 Tauri 平台 `app_config_dir`，而不硬编码 Linux 路径。

只持久化：

- schema version。
- UI 偏好（主题、字体、窗口尺寸）。
- 最近 workspace canonical paths。
- runtime ID 与不含密钥的配置摘要。
- Tab 顺序、Agent 类型和活动 Tab ID。

不持久化：

- API key、token、cookie 和 OAuth 凭据。
- PTY scrollback、用户输入和 Agent 输出。
- 实时资源指标和过期 runtime 状态。

配置必须原子写入，启动时校验 schema，未来版本必须通过显式 migration 升级。

## 十、实施顺序与发布门

实施不使用日历周数作为完成承诺，而使用可验证的阶段门：

1. **Phase 0 - CLI 契约**：runtime/session/provider 契约在无 GUI 情况下通过 Docker E2E。
2. **Phase 1 - PTY 垂直切片**：最小 Tauri UI 在 Linux/Windows 完成真实 Agent 交互、resize 和关闭。
3. **Phase 2 - 产品闭环**：启动、多 Session、状态、历史和对账主路径通过。
4. **Phase 3 - 稳定与安全**：并发、故障、负载、可访问性和 secret scan 通过。
5. **Phase 4 - Preview 发布**：三平台安装/升级/卸载、签名和 smoke suite 通过。

详细代码落点、测试和 DoD 见 [06-implementation-plan.md](./06-implementation-plan.md)。

## 十一、开始编码的充要条件

当且仅当以下条件满足时，可进入 Workbench UI 功能实现：

- [ ] `05-cli-gui-contract.md` 的命令名、输出 schema、错误码和关闭语义获得批准。
- [ ] Runtime idle 模式、Session scope wrapper 和确定性 terminate 通过 Docker 实验。
- [ ] Workbench 不直接操作 Docker/registry 的边界得到保留。
- [ ] MVP 不恢复活 PTY、不做资源 Dashboard 和不读取 Provider 密钥的边界得到保留。
- [ ] Phase 0 兼容测试证明新 CLI 契约不破坏现有 AISC 命令。
