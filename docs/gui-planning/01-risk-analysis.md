# AISC Workbench MVP 风险登记

> 状态：**实施基线（Proposed）**  
> 基线日期：2026-08-02  
> 用途：将未知项变成可验证的阶段门，而不是用乐观假设推进 UI

## 一、使用规则

本文件只登记会改变架构、MVP 范围或发布判断的风险。实现过程中发现新风险时，必须补充触发条件、负责人、验证证据和阻断门。

概率与影响使用 `高 / 中 / 低`。风险状态使用：

- `Open`：尚无足够证据。
- `Mitigating`：缓解方案已进入实现或测试。
- `Accepted`：残余风险已被明确接受，并记录适用平台或限制。
- `Closed`：阶段门已有可重复证据。

以下情况不得仅凭手工演示关闭风险：涉及 registry 兼容、进程清理、密钥泄漏、状态竞态或跨平台 PTY 的风险。

## 二、P0：开始产品 UI 前必须关闭

| ID | 风险与触发信号 | 概率 / 影响 | 缓解与关闭证据 | Owner / 阻断门 |
|---|---|---|---|---|
| R-01 | **持久 Runtime 不可行或初始化不完整。** 无 TTY 启动时 entrypoint 跳过 scope/cc-switch 初始化，idle PID 1 不健康，`runtime start` 在 ready 前返回，或 `docker exec` 丢失动态 scope 环境。 | 中 / 高 | 增加显式 idle 模式与 ready check；ready 前原子写入非秘密 runtime context，Session 从 context 重建环境；在 `project`、`temporary`、`direct`、`proxy` 组合上执行 Docker E2E；验证取消或失败不留下错误 registry 记录。 | CLI/Runtime；Phase 0 |
| R-02 | **Session wrapper 无法确定性终止进程树。** 关闭 Tab 后 Agent、子 shell 或 `docker exec` 任一侧仍存活，PID/PGID 复用导致误杀。 | 高 / 高 | wrapper 以 session UUID 记录 PID/PGID 和启动身份；执行 TERM、宽限期、KILL、幂等重试；测试正常退出、Ctrl+C、挂起、fork 子进程、runtime stop 与宿主崩溃清理。 | CLI/Runtime；Phase 0 |
| R-03 | **PTY 链路在平台间行为不一致。** ConPTY/Unix PTY 出现首屏丢失、乱码、resize 失效、EOF 或 Ctrl+C/Ctrl+Z 语义不同。 | 高 / 高 | 先完成最小真实链路；以 byte chunk + sequence 传输；Linux 与 Windows 实机验证 Agent 登录、中文/emoji、1 MB 粘贴、连续输出、100 次 resize 和 50 次快速开关。macOS 在 Preview 门补齐。 | Desktop/PTY；Phase 1 |
| R-04 | **CLI 契约或 registry 迁移破坏现有 AISC。** JSON 混入人类输出、退出码不一致、旧记录无法读取、并发写丢失，或新命令静默改变旧命令语义；当前 `.containers.lock` 在 Windows 上会静默退化为无锁。 | 高 / 高 | 固定 `aisc.cli/v1` envelope、capability 与稳定错误码；registry 保持 map schema、原子替换，并实现 POSIX/Windows fail-closed 文件锁；建立旧 fixture、双进程竞态和现有命令回归测试。Workbench 不直接读写 registry。 | CLI/Compatibility；Phase 0 |

Phase 0/1 的 Go 条件不是“可以启动一次 Agent”，而是 R-01 至 R-04 的自动化与实机证据分别满足 [05-cli-gui-contract.md](./05-cli-gui-contract.md) 和 [06-implementation-plan.md](./06-implementation-plan.md) 的验收门。

## 三、P1：产品闭环与 Preview 前必须关闭

| ID | 风险与触发信号 | 概率 / 影响 | 缓解与关闭证据 | Owner / 阻断门 |
|---|---|---|---|---|
| R-05 | **异步刷新覆盖更新状态。** 较早的 inspect/poll 在 stop、restart 或新观察之后返回，UI 回退到旧状态；错误被误建模为 Runtime `error`。 | 高 / 高 | 每个 Runtime 使用本地 revision、request sequence 和 `observed_at` 排序；控制操作后强制 inspect；失败保留“观察状态 + 独立操作错误”；用乱序响应和外部 CLI 操作测试 reducer。 | Desktop/State；Phase 2/3 |
| R-06 | **同一 workspace 的并发创建绕过唯一性。** 两个窗口或 GUI/CLI 同时为 canonical workspace 创建 `project` Runtime，共享 `.claude/.codex/.cc-switch` 并相互污染。 | 中 / 高 | canonicalize 后以 workspace hash 跨进程锁覆盖冲突检查、Docker 创建和 registry commit；Docker label/registry 双重对账；冲突返回 `AISC_ERR_RUNTIME_CONFLICT`；POSIX/Windows 双进程竞态测试只能有一个成功。 | CLI/Runtime；Phase 0/3 |
| R-07 | **Provider 展示错误或泄密。** 将 Claude 状态用于 Codex、切换后仍显示旧路由、`not_configured` 被误判，或输出/日志包含 key/token 片段。 | 中 / 高 | Provider snapshot 以 `(runtime_id, agent)` 为键；只读取 id/name、route mode、auth status、observed time；切换后失效缓存；fixtures 与日志/history/crash report 执行 secret scan。 | CLI + Desktop/State；Phase 2/3 |
| R-08 | **启动流程暴露过多容器概念或产生隐式副作用。** 用户为常用项目反复配置，Quick Start 静默创建目录/runtime，或警告阻断正常终端使用。 | 中 / 中 | 执行 Hard/Config/Warning/Info 分级；Quick Start 只保留一次可见确认；持久化非秘密选择；对首次、恢复、缺镜像、旧 CLI、Docker 不可用和取消路径做 UX/E2E 验收。 | Product/UI；Phase 2 |
| R-09 | **Tauri 边界扩大为任意本地执行能力。** 前端可拼接 shell、读取任意文件、打开不受控 URL，路径或终端内容进入日志。 | 中 / 高 | 后端只暴露命名 command 与受控 enum；全部进程使用 argv；限制 capability、CSP、opener、路径和 payload；安全测试证明前端不能调用任意命令，日志与持久化通过 secret scan。 | Desktop/Security；Phase 3 |
| R-10 | **终端吞吐造成卡顿或无界内存。** 高频全局事件、无限队列、大段粘贴或不可见 Tab 持续渲染导致 UI/后端内存增长。 | 高 / 中 | 使用有序 byte channel、背压、粘贴上限、终端 scrollback 上限和不可见 Tab 渲染策略；10 MB 连续输出、10 Session、8 小时 soak 与内存趋势检查通过。 | Desktop/PTY + UI；Phase 1/3 |
| R-11 | **History 损坏或多窗口覆盖。** 非原子写入、旧 schema，或两个窗口同时基于同一 revision 写整文件，导致启动失败、更新丢失或误恢复 Session。 | 中 / 中 | schema-versioned JSON、跨进程锁内的 expected-revision compare/reload/owned-patch merge、原子替换、损坏隔离与 migration fixtures；只恢复布局并创建新 Session。 | Desktop/Persistence；Phase 2/3 |
| R-12 | **安装包依赖与签名在目标平台失败。** WebView2/WebKitGTK、Docker Desktop 权限、ConPTY、macOS 签名/公证或 GUI 启动环境缺少 shell PATH，导致行为只在开发机有效。 | 高 / 高 | discovery pin 经过验证的 AISC 绝对路径并处理多安装冲突；三平台从桌面入口运行同一 capability/PTY smoke suite；验证安装、覆盖升级、卸载、签名、公证和依赖提示；卸载不得停止 Runtime 或删除 AISC/workspace 数据。 | Release；Phase 4 |

## 四、持续控制的产品风险

| ID | 风险 | 控制规则 | 检查点 |
|---|---|---|---|
| R-13 | **范围蔓延为通用终端、Docker Dashboard 或 IDE。** | 新功能只有在直接服务“项目 → Runtime → Agent Session”闭环且普通终端无法提供该上下文时才进入 MVP。资源图表、文件树、编辑器、插件、分屏、全局快捷键和完整 Provider 编辑器保持延期。 | 每个切片评审、Phase 2 门 |
| R-14 | **诊断能力诱发隐私泄漏。** | 不记录 PTY 输入输出、环境、key/token/cookie 或可恢复密钥片段；技术详情只包含命令名、run ID、稳定错误码、版本、退出码、耗时和脱敏 stderr 摘要。 | 每个 PR、Phase 3 secret scan |
| R-15 | **取消与重试留下半成品资源。** | 每个可取消操作定义资源提交点；重试复用同一 runtime UUID；取消后 inspect 并报告实际资源，不靠 Workbench 猜测或直接清理 Docker。 | Phase 0 CLI E2E、Phase 2 UX E2E |

## 五、风险关闭记录要求

关闭风险的 PR 或发布清单必须附：

1. 对应风险 ID 和测试用例路径。
2. 自动测试结果；必须实机验证的项目附平台、版本和步骤。
3. 仍存在的限制、受影响平台以及用户可见文案。
4. 若选择接受风险，记录接受人、原因、复查版本；不得用“后续优化”代替处理结论。

阶段门的唯一清单位于 [06-implementation-plan.md](./06-implementation-plan.md)。本文件解释为什么这些门存在，不建立第二套发布标准。
