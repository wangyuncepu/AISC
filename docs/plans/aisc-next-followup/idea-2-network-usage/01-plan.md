# IDEA-2 实施计划：mihomo 订阅导入 + 「网络与用量」面板 + Provider token 统计

> 状态：已规划（2026-08-19 用户批准）。分支 `idea-2-network-usage`。
> 本文是实施主计划；数据契约见 `02-data-contracts.md`（usage 相关字段为初版假设，
> **2a 探针轮冻结**）。

## 1. 背景与范围

用户 2026-08-19 拍板启动（原 `../todo.md` IDEA-2 条目扩容）：

1. 在适合的位置加入 mihomo 订阅导入（容器 TUN 模式用）；
2. 新增与设置同层级的面板；
3. 面板展示 mihomo 订阅用量、余量；
4. 统计 provider 的 token 用量。

### 用户决策（2026-08-19）

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 订阅刷新后如何生效 | **自动重建**：fingerprint 纳入订阅内容哈希（仅 network=proxy），刷新后下次启动走既有 runtime_conflict 引导重建容器。与挂账「容器随镜像同步更新」同族机制（本轮只做订阅维度） |
| D2 | token 统计范围 | **全部工作区聚合**：运行中容器实时取数 + 已停止工作区用缓存快照；面板可切换单工作区 |
| D3 | 导入入口 | **面板 + 向导内嵌表单**：onboarding network 步（container_tun 分支）内嵌完整导入表单；表单组件面板/向导两处复用 |

## 2. 已核实事实（探索结论，2026-08-19）

1. **容器是配置转换唯一事实源**：`container/mihomo-build-config.js` 接受
   clash-yaml / SIP008 JSON / base64 / URI 列表任意订阅格式，自行强制注入
   TUN/DNS/回环规则（`stripTopBlock` + 固定 tun 块 + `ensureLoopbackRules`）。
   → 宿主只需存储 + 刷新 + 挂载**原始订阅文件**，无宿主侧配置合成。
2. **缺口①**：Rust `start_runtime`（`workbench/src-tauri/src/runtime.rs:538-583`）
   从不传 `--proxy-config` → Workbench 起 proxy 容器只带 NET_ADMIN/TUN 设备、
   无配置挂载，entrypoint 直接跳过 mihomo。
3. **缺口②**：mihomo 配置路径是前数据根时代的 `<aisc_root>/.claude/mihomo/config.yaml`
   （仓库根相对；`aisc build` 向导 curl 写此处，wizard.py:98-123），不在
   Stage 7 数据根 `%LOCALAPPDATA%\AISC\data` 下。
4. **缺口③**：Rust crate 无任何 HTTP 客户端依赖；Python 有可注入 urllib
   transport 先例（`cc_switch_resolver.py:57-75`，UA/超时/错误映射/TTL 缓存）。
   Stage 2 架构即「CLI 是数据面」→ **下载归 Python CLI，Rust 零新依赖**。
5. **订阅用量标准**：`subscription-userinfo` 响应头
   `upload=..; download=..; total=..; expire=..`（字节 / Unix 秒；
   `total=0`=不限量；`expire` 可缺失）。现状：向导 curl 丢弃全部响应头，无人捕获。
6. **cc-switch v5.10.1（容器内）自带用量体系**：会话日志扫描（无需代理）+
   代理请求日志双源；按供应商统计（请求数/成功率/总 Token/估算费用）+
   180 行模型定价预置；`cc-switch.db` schema v16、带
   `cc-switch.db.session-usage.lock`。claude 侧代理 entrypoint 自动启用
   （entrypoint.sh:393）；codex 路由随切换方向开/关（adapter `op_switch`）。
   **usage 表名仓库内未探测过 → 2a 探针冻结契约**。
7. **宿主直读 bind-mount 的 WAL SQLite 在 Windows 文件共享下锁语义不可靠**
   → usage 走容器内 adapter 新操作（docker exec + 只读 SQLite，照
   `op_list` 模式），与 Stage 8 Path B 一致；宿主永不直接开库。
8. **设置同层面板接入点**（照 `SETTINGS_TAB_ID` 模式逐点复制）：
   哨兵（`workspaceRuntime.ts:91` 旁）→ `workspaces.ts` 状态/action/cycle/close
   回落（73-87/152-164 模式）→ `App.vue:385-412` 拥有内容区切换（新 pane div +
   WorkspaceView guard）→ `WorkspaceBar.vue` chip（174-184）+ ▾ 菜单项
   （329-334 内联声明）→ i18n 双语成对（parity 测试守门）→ 测试
   （workspaceBar / runtimeFacade / store 三处）。
   字段级端到端模板 = `ui.default_new_page` 11 文件链。
9. `stores/network.ts` 名字已被 onboarding 网络选择 store 占用——新面板/组件
   命名避开（面板用 `features/usage/NetworkUsageTab.vue`）。
10. **机密纪律**：订阅 URL 走 stdin 不进 argv（照 `--secret-stdin` 先例）；
    信封/UI/诊断包只出脱敏串。
11. 现有 mihomo 挂载：`start_runtime` proxy 分支 `-v {proxy_config}:/etc/mihomo/config.yaml:ro`
    （runtime.py:998-1001）；fingerprint = sha256(`{image,network,scope,workspace}`)
    （runtime.py:40-59），**不含 proxy_config**。

## 3. 架构设计

### 3A. 订阅数据面（Python CLI）

新命令组 `aisc network subscription import|refresh|show|clear`（`--format json`
走 `aisc.cli/v1` 信封；契约见 02 文档）：

- **import**：URL 经 **stdin** 传入 → urllib 可注入 transport 拉取（UA 用
  clash/mihomo 家族——订阅服务按 UA 门控返回格式；30s 超时 + 重试 1 次）→
  非空校验 → 原子替换 `<data-root>/config/mihomo/subscription.yaml`
  （原始订阅文件，下载原样落盘）→ 解析 `subscription-userinfo` 头 → 写快照
  `<data-root>/config/network-subscription.json` → 返回快照（URL 脱敏）。
- **refresh**：按存储 URL 重拉（同 import 落盘）；**show**：只读快照；
  **clear --confirm**：两文件俱删。
- userinfo 解析器容忍：缺 `expire`、`total=0`、分号/空格混乱；字节与 epoch
  原样透传，展示层换算。
- **legacy 采用**：新路径不存在而 `<aisc_root>/.claude/mihomo/config.yaml`
  存在 → 一次性采用（拷贝）；`aisc build` 向导步骤改走新模块。
- **start_runtime 自动解析（修缺口①）**：application 层 `network=proxy` 且
  `proxy_config` 为空 → 自动取数据根配置路径 → 无则 legacy → 皆无则维持现状
  （无配置 TUN）。**Workbench Rust 零改动**。
- **fingerprint 扩维（D1）**：`compute_config_fingerprint` 增可选参
  `proxy_config_sha256`，**仅 network=proxy 时纳入**（direct 模式指纹字节级
  不变 → 现存 direct 容器零冲突，测试钉死）。订阅刷新 → sha 变 → 下次 start
  判 runtime_conflict → 既有重建引导。
- 单订阅模型（全局唯一，挂到任何 network=proxy 容器）；多订阅不做。

### 3B. 用量数据面（容器 adapter + Python 聚合）

- **2a 探针**：live 容器 `docker exec … python3 sqlite3` dump usage 表结构 +
  脱敏样例 → 02 契约冻结 + fixtures。
- 容器 adapter `aisc-cc-provider` 新操作 **`usage`**（只读 SQLite 快照照
  `op_list` 模式；红action 纪律沿用）：容器侧完成聚合，返回
  `--range today|7d|30d` 的 per-provider（请求数/成功/失败/总 token/估算费用）+
  per-model + 汇总；表缺失/空库优雅降级（`ok=true, data 空`），不报错。
- 宿主 CLI `aisc usage overview --format json`：遍历数据根 workspaces →
  注册表 + docker 状态判定：运行中 → adapter 取数并顺手写缓存快照
  `<data-root>/cache/usage/<ws-hash>.json`；已停止 → 读缓存快照（无则标
  no-data）。输出 `{subscription, workspaces[], totals}`。
- Rust：Tauri 命令 `usage_overview` / `network_subscription_import|refresh|clear`
  薄封装（argv builder 纯函数 + `run_control_input`/`run_control`；usage 超时
  120s——多容器逐个 exec）。

### 3C. 面板与入口（Workbench UI）

- 哨兵 `NETWORK_USAGE_TAB_ID = "network-usage-tab"`；面板组件
  `features/usage/NetworkUsageTab.vue`。照 §2-8 清单接入（chip + ▾ 菜单第二项 +
  App.vue pane + WorkspaceView guard + nextTick 焦点模式）。快捷键 v1 不加
  （WebView2 吞键风险，挂账）。
- **面板两节**：
  - *订阅*：脱敏 URL + 更新时间 + 用量条（(upload+download)/total）+ 余量 +
    到期日 + [刷新][更换][清除]；未配置态 = 导入表单；刷新后提示「新配置将于
    下次容器启动时生效（自动重建）」；userinfo 缺失 → 「订阅未提供用量信息」。
  - *Provider 用量*：范围选择（全部/单工作区）+ 时间（今日/7天/30天）+
    per-provider 行（名称/请求数/真实消耗 tokens/估算费用/成功率）+ 口径说明
    （cc-switch 会话扫描 + 代理日志；官方直连流量归属有限）。
- **共享导入表单组件 `features/usage/SubscriptionForm.vue`**（D3）：粘贴 URL →
  import → 结果反馈；向导与面板两处挂载，单实例状态自持。
- **向导内嵌**（OnboardingWizard.vue network 步 378-426）：选 container_tun
  分支显示「需要代理订阅」+ SubscriptionForm + 「稍后在面板配置」跳过项
  （不阻断向导）。
- **LaunchSummary**（高级配置 network select 旁）：`network=proxy && 无订阅` →
  警示行 + 「去配置」开面板。
- **preflight 新 warning 检查**：`network=proxy && 无配置文件` → warning
  （不 fail；无配置 TUN 可启动维持现状）。
- 数据获取：面板打开自动拉一次 + 手动刷新按钮；不做定时轮询（v1）。
- i18n：全部键双语成对新增。

## 4. 阶段与门禁

| 阶段 | 内容 | 门禁 |
|---|---|---|
| 本轮 | 规划文档落库（本文 + 02 初版）+ todo.md 更新 | 用户 review |
| **2a** | 探针与契约冻结：live cc-switch.db usage 表 dump（docker exec）+ 真实订阅 URL 行为验证（用户机场链接手测）→ 02 冻结 + fixtures | 契约文档 |
| **2b** | Python 订阅链路（§3A 全部 + `_detect_command` known 集补 `cc-switch` 漏） | python 全测 + 手测：真实 URL import→show→refresh→clear |
| **2c** | 用量数据面（adapter usage 操作 + `aisc usage overview` + 缓存快照） | python 全测 + 手测：CLI 对 live 容器出数 |
| **2d** | 面板 + 向导表单（§3C 全部） | vitest + vue-tsc + cargo test + 手测轮 |
| **2e** | 收口：手测矩阵全过 → todo 闭环 → `--no-ff` 合并 → 四 CI 绿 | CI + 用户验收 |

**手测矩阵（2d/2e）**：向导选 proxy→内嵌表单导入→启动→容器内 mihomo 生效；
面板用量显示 + 刷新→下次启动自动重建提示；停止工作区显示缓存；**direct 模式
现容器零冲突**（升级后首启验证）；clear 后 preflight warn；LaunchSummary
警示 + 跳转；诊断包不含完整 URL；订阅不提供 userinfo 头的降级显示。

## 5. 关键文件

- **Python**：`src/aisc/cli/main.py`（组注册 + dispatch + known 集）、新
  `src/aisc/cli/commands/network.py`、新 `src/aisc/application/network_subscription.py`、
  `src/aisc/application/runtime.py`（自动解析 + fingerprint）、
  `src/aisc/cli/commands/wizard.py`（重定向新模块）、新
  `src/aisc/application/usage.py`、`container/aisc-cc-provider`（usage 操作）、
  对应 tests（transport 伪注入照 cc_switch_resolver 测试模式；adapter 照
  test_cc_switch_provider_adapter 的 seeded-db 模式；宿主层 FakeExec）。
- **Rust**：`workbench/src-tauri/src/runtime.rs`（4 个 Tauri 命令 + argv 纯函数 +
  内联测试）、`lib.rs` 注册、`ipc.ts` / `types/index.ts` 绑定。零新依赖。
- **Vue**：`workspaceRuntime.ts` / `workspaces.ts` / `runtime.ts`（门面转发）/
  `App.vue` / `WorkspaceBar.vue`、新 `features/usage/NetworkUsageTab.vue` +
  `SubscriptionForm.vue`、`OnboardingWizard.vue`、`LaunchSummary.vue`、
  `PreflightGate.vue`、i18n ×2、相关 `__tests__`。

## 6. 风险与缓解

1. **cc-switch usage schema 未知/跨版本漂移** → 2a 探针冻结 + adapter 防御式
   解析 + 缺表降级为空数据（面板「暂无数据」不报错）。
2. **fingerprint 变更波及存量容器** → sha 仅 proxy 模式纳入；direct 字节级
   不变有测试；存量 proxy 容器（罕见）一次性重建提示。
3. **订阅服务 UA 门控 / 无 userinfo 头** → clash 家族 UA；头部缺失降级显示。
4. **WAL 锁语义** → 宿主永不直接开库，全走容器内 adapter。
5. **URL 泄露面** → stdin 传入；信封/日志/诊断包只出脱敏串；数据根在
   LOCALAPPDATA 不入 repo。
6. **向导内嵌表单拖长首次流程** → 表单可跳过；proxy 也可稍后面板补配。
7. **聚合耗时** → 打开面板 loading 态；stopped 用缓存；usage 命令 120s 预算。

## 7. 非目标（本轮不做）

多订阅；快捷键直达面板；provider 用量定时轮询；「容器随镜像同步更新」
（挂账维持，见 todo.md）；mihomo REST API 实时流量（订阅 userinfo 头已够）；
DeepSeek 等厂商余额 API（token 用量已够）。
