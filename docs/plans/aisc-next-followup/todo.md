# 待办与门禁

## UI10 终端非视觉缺陷两项——待排期（2026-08-21，Stage 10 基线 10a 手测发现）

Stage 10 视觉阶段不修（决策 D10-08/D10-15，终端为硬边界），仅要求无回归。证据：
`docs/plans/aisc-next-followup/stage-10-ui-visual-polish/baseline-10a.md` B-05/B-06。

- **①长输入不换行（B-05）**：终端内持续输入，光标在同一行不断覆盖之前内容，
  不换行；另布局恢复时 prompt（`root@...#`）串行断行一次（未复现，现象确在）。
  推断方向：xterm wraparound/PTY 行为或反向补偿交互，需专门复现路径。
- **②resize fit 迟滞（B-06）**：拖拽窗口宽窄，终端列数不实时跟随，缓慢逐段
  挤压到位。推断方向：fit 触发节流/事件时序，非 CSS 层。
- **③终端行错乱（B-05 同族，2026-08-22 Stage 10 手测补充）**：快速切换
  tab 时终端文本行串位/错乱（证据 aaa.png）——疑似 v-show 重新显示时
  xterm fit/回流时序问题。与 B-05/B-06 同属 fit/行重排家族，一并排期。

## 全流程全生命周期日志——✅ 已落地（2026-08-20，分支 `lifecycle-logging`，用户手测全 PASS）

`<数据根>/logs/aisc.log` 单一 JSONL 时间线（轮转 2MB×3，双端同参），一条
run_id 串 UI→CLI→容器全链。交付：P1 双端 appender + run_id 注入（env
`AISC_RUN_ID`）；P2 `aisc logs show/path`（--lines/--source app|cli|ui|all/
--format）；P3 诊断对话框「最近日志」折叠段+复制、诊断包 recentLogLines；
P4 诊断包 managed 容器 docker logs --tail 50 尾随；P4.5 UI 动作打点
（launch/stop/build/冲突面板/订阅/cc-switch/doctor/导出/设置保存，全在
store 收口点）；预检失败打点（cli_resolve_failed/cli_discovery_failed/
cli_pin_healed——"无法沟通 aisc CLI"全族时间线可见）。**手测实证**：TLS
拒绝三层 error 链（ui_action error + op + cli_exit 同错误码）、容器链
created→ready、自愈留痕、诊断包三键齐全。红线：字段允许清单制（stdin/
URL/key/PTY/工作区绝对路径永不入日志）。门禁：python 743+/cargo 206/
vitest 277/tsc 0。

## 挂账① 指纹源自动下载（Rust reqwest）——✅ 已落地（2026-08-19，分支 `rust-subscription-download`）

- **交付**：`workbench/src-tauri/src/subscription.rs`——Rust 下载器（reqwest+
  rustls、clash 家族 UA、env→WinINET 双探测系统代理、30s+1 重试、10MB 上限、
  宽容自签证书、捕获 `subscription-userinfo` 头）→ stdin JSON（b64）交给新
  CLI op `network subscription store-downloaded`；持久化/脱敏/假节点兜底全留
  Python。`network_subscription_import/refresh` 改「Rust 优先，失败回落
  Python 传输」，末端仍是 TLS_REJECTED→粘贴导入引导。
- **实探勘误（关键）**：原 2a 矩阵「真 Chrome 通过」系误读（dump-dom 捕获的
  是 Chrome 自带 ERR_CONNECTION_CLOSED 报错页）；且 103.14.76.98 源 8/17→8/19
  收紧为全杀（clash-verge 三级更新自身同日两轮全灭，其 8/17 日志曾成功）。
  同机场域名 http 端点对一切栈开放（curl+clash UA 即 200+真实 userinfo 头）。
  详见 `idea-2-network-usage/02-data-contracts.md` §6.1 修订。
- **验收口径**：全杀档位下该源任何客户端都拉不到（非本传输缺陷）；墙回落
  到 clash-verge 可过档位时本传输自动受益。域名 http 源今日即全链路可用。

## 挂账③ provider quota 接入面板——**已砍（用户决策 2026-08-19）**

- 完整实现过一轮（adapter op + 宿主/Rust 命令 + provider 页行内余额按钮，
  全门禁绿）后用户验收判定砍掉：**第三方供应商（我们的主力场景）需逐个
  配置 usage-query 模板才有数**（`usage-query set --template general/newapi/
  balance/custom`，官方订阅类才开箱即用），按钮对主力场景只会显示
  「未配置」，价值不匹配。分支已弃。
- 调研结论存档（如将来上游让第三方开箱即用可复活）：上游 `provider quota
  <id> --json` 信封 `{app, providerId, status: ok|not_available|error,
  available, queriedAt(ms), result(多态), error}`；模板机制见官方文档
  2.5-usage-query。

## KI-7 Provider 管理页两处异常（2026-08-19 发现；**✅ 已修，随 IDEA-5 轮合并**）

- **①自定义添加供应商报错**：根因=`--mode default="simple"` 盖掉 stdin 的
  custom（Rust 从不传该旗标）。修复=默认值改 None（5a，`af4998e`）。
- **②外部 cc-switch 改动不同步**：根因=面板一次性加载。修复=可见性翻转即
  重拉（5b，`d57db0b`）。用户手测均 PASS。


## KI-6 Docker 检测/操作受启动时 PATH 与安装位置影响（2026-08-19，IDEA-2 手测期间发现，随 `idea-2-network-usage` 修复）

- **症状**：Docker Desktop 已启动，Workbench 启动摘要仍报「Docker 引擎未运行」。
- **根因（双层）**：①本机 Docker 为**每用户安装**（`%LOCALAPPDATA%\Programs\DockerDesktop`），
  而 `env.rs::docker_cli_candidates` 只认机装位 + 错误的旧猜测位；②GUI 进程 PATH 是
  启动时快照，装 Docker 前开的终端继承不到安装器写入用户 PATH 的 bin 目录。
- **修复（三层）**：①引擎探测改为**命名管道 `\\.\pipe\docker_engine` 直发
  `GET /_ping`**（实时、与安装位置/PATH 完全无关；tokio named pipe，CLI 探测降为
  兜底）；②CLI/Desktop exe 候选链补每用户安装位（docker.exe 与 frontend\Docker
  Desktop.exe），NSIS `un.FindDockerCli` 同步补；③`run_control_inner` 给 aisc 子进程
  **前置注入 docker bin 目录到 PATH**（Python CLI 的裸 docker 调用不再受快照影响）。
  cargo --lib 197 全绿（含每用户路径锚定 + 管道探测实测）。

## v2.1.6-dev 预览手测阻塞项（2026-08-18，draft 暂不发布）

> 来源：v2.1.6-dev 安装包"全新机器"手测（用户 2026-08-18）。发布前需逐项
> 解决；原始记录在 `docs/todo.md`「手测异常/问题」。

- **KI-3 首次运行 CLI 发现竞态（P1+P2 同族）**：✅ **已修（2026-08-18，
  随 IDEA-3 分支合并 develop）**——真根因是 `resolve_pin` 抢跑：向导期间
  negotiate 被推迟 → 环境探测/预检读 pin 落空 → 裸 `cli_not_found`
  （`technical_detail: null` 实锤）；重检时 negotiate 已写 pin 故恢复。
  修复：`session::resolve_cli`（15 个命令调用点）无 pin 时当场自动发现并
  落盘（`cli::auto_select_and_pin`）；另探测超时 15s→45s + 超时重试一次
  （冷启动 sidecar 解包+杀软首扫兜底）+ `cli_not_found` 携带逐候选明细。
  **待最终复验**：从含修复的提交重建安装包后在干净环境复测安装→首跑
  全链路（当前 v2.1.6-dev draft 构建于 `65ba5d5`，不含本修复）。
  - **KI-3 round 3（stale pin 自愈，2026-08-18）**：卸载安装版删掉 sidecar
    `aisc.exe`，但共享数据根的 settings.json 残留死路径 pin → dev 模式所有
    CLI 调用/negotiate 全挂（须手动重检才恢复）。已修：`resolve_pin` 对
    pin 加存在性检查（`is_file`），失效即视为无 pin → `resolve_cli`/
    `negotiate_capabilities` 落入 `auto_select_and_pin` 自动重发现并覆写
    pin（`session::pinned_cli` + 单测）。属 KI-4 卸载配套家族的 dev 侧症状。
- **KI-4 卸载/升级的配套资源管理**：✅ **已修并合并（2026-08-18，合并
  develop `604c4b4`，用户四步手测矩阵 PASS）**（用户决策：两勾选默认不勾 / 引擎不可达
  跳过+提示手动命令 / 容器同步本轮不动 / 暂不发布）**——①「删除应用
  数据」勾选扩到真数据根 `%LOCALAPPDATA%\AISC`（Stage 7 布局；原 Tauri
  路径只覆盖旧布局）；②新增「删除 Docker 容器与镜像」勾选（docker.exe
  已知位置探测 + `docker version` 引擎 probe；`aisc-wb-*` 容器逐个
  `rm -f` + `super-claude:latest` `rmi -f`；不可达则跳过、完成页弹
  手动命令；模板禁用 `--format`——双大括号是 handlebars）；/UPDATE
  全跳过；CI smoke 补「静默卸载数据根必须保留」断言（勾选仅 GUI 存在，
  删除严格 opt-in）。**手测修复轮（2026-08-18）**：①Docker 勾选框不渲染
  ——`WM_GETFONT` 把内层对话框 HWND 覆盖成字体句柄，第二个 `CreateWindowEx`
  拿字体句柄当父窗口静默失败（`ccd5dbc`：字体改存 `$8`）；②Docker Desktop
  **非默认路径**识别不到 docker.exe——新增 `un.FindDockerCli` 探测链：`where
  docker`（PATH，覆盖自定义安装）→ 两个默认位 → Docker Desktop 卸载注册表
  InstallLocation 回退。
- **KI-5 升级用户 PATH 冲突提示**：✅ **已修并合并（2026-08-19，分支
  `ki-5-path-takeover`，用户 VM 手测 PASS——2.1.4 旧装 + 新装弹窗接管成
  功）**。用户拍板（2026-08-19）：**同源旧版 → 询问接管（覆盖式升级语义，
  CLI 随 Workbench 同步升级——接管条目固定指向安装目录，升级原地替换
  sidecar，PATH 无需再动）**。实现：冲突探测改为系统 PATH→用户 PATH 依序
  注册表扫描（**不用 `where`：安装器进程 PATH 含 CI toolchain 目录，不代表
  用户终端**）；同源判定双探针（`version --format json` 的 `aisc.cli/v1`
  信封 + 分隔符无关的 `cli_version` 读取；前信封时代回退 `--version` 散文
  扫首个数字）+ SemverCompare 严格更旧；接管 = 安装目录**前置**用户 PATH
  （旧条目/文件不动，可逆；卸载移除自有条目后旧 CLI 自动恢复）。非同源/
  同版/更新/静默安装维持 never-shadow；系统 PATH 遮挡弹手动指引。**三处
  NSIS 教训**：①G18 宏双作用域展开时安装侧函数名不能裸 Call（`!if
  "${UN}"==""` 只在安装侧展开）；②LogicLib 生成标签不能跨 `!if` 剥离区
  （受保护区改纯原生 StrCmp/IntCmp/相对跳转）；③**json.dumps 分隔符是
  `": "` 不是 `":"`**——硬编码偏移读出单个空格静默降级（改为跳到值的开引
  号，实测 v2.1.4 信封输出校验）。
- **挂账：容器随镜像同步更新——✅ 已落地（2026-08-20，分支 `container-image-sync`，用户手测 1-4 全 PASS）**：
  additive `image_id` meta 字段（非 literal 改指纹公式——公式一变存量容器
  全员假冲突）。registry meta 落 `docker image inspect .Id`；复用分支（指纹
  匹配后）三态比较：存量无 id 放行 / 异值冲突（reason 精确标 image updated，
  走既有重建引导，UI/Rust 零改动）/ 探测失败放行；`start_runtime` 复用分支
  顺手 heal 补写（照 KI-3 stale-pin 哲学）。**手测实证**：存量工作区首次复
  用即 heal（7c4762f5）；`docker commit` 同 tag 换 ID 后启动弹冲突 → 移除重
  建落新档（dc9bcbc1），新容器实挂新镜像。python 全测 732 passed。

## 想法 / Ideas

### IDEA-1 Tab 新建 UX（Windows Terminal 式，2026-08-17 用户提出）

- **内容**：设置页增加「默认新 tab」选项；点 `+` 立即建默认 tab；`+` 旁加 `↓`
  展开完整列表选择（拆分按钮）；设置页本身改为一种 tab 类型。
- **现状**：**已实现**（分支 `ui-tab-ux-followup`，2026-08-17 用户手测基本 PASS；
  手测反馈「设置 tab 铺满去卡片」已当场修复）。`ui.default_tab_agent` 设置字段
  （Rust 校验/默认 bash/REL-03）、共享 `SettingsForm`（dialog/tab 双模式）、虚拟
  设置 tab（哨兵 id，不持久化/无会话/不计 8 上限）、`+` 拆分按钮（默认直建 + ▾
  菜单含设置项）。KI-2（向导复检）同轮 PASS；KI-1 仍未 exercised。
- **历史**：`+` 菜单被 tabbar 滚动容器裁剪的 bug 已单独修复（Teleport + zoom
  补偿；Stage 6 UX-02 回归，非 Stage 7 范围）。
- **KI-1 进展（2026-08-17 同轮，用户真机复验 PASS）**：已装未启动场景可正常唤起，但弹
  Dashboard 前台窗 ——已实现**静默启动**（唤起前写 Docker 自身设置
  `OpenUIOnStartupDisabled: true`，等价 GUI 取消勾选 "Open Docker Dashboard at
  startup"，启动进托盘；只增不反向、保留其它键、原子写、损坏文件不动；
  settings-store.json 新键型 + settings.json 旧 camelCase 双兼容）。连带修复唤起反馈
  UX：向导环境步骤与 summary 页均为「转圈+已等待秒数」连续进度 + 就绪绿色提示/播报，
  轮询改静默探测（不再整页闪动），引擎 3 分钟未应答进度态自动收起。副作用须知：该设
  置全局生效，手动启动 Docker 也不再弹 Dashboard；恢复方法 = Docker Desktop
  Settings → General 重新勾选。

### IDEA-4 Provider 一键切换激活（2026-08-17 用户提出；**2026-08-18 实现并手测 PASS**）

- **已实现**（分支 `idea-4-provider-switch`）：adapter `switch` 操作（真配置行走官方
  非交互 CLI；空配置官方行走 pty+自动应答；id slug 校验防注入）+ `official` 伪目标
  （取消代理回官方直连）+ codex 切换自动开/关本地代理路由 + codex auth.json 无密钥
  占位管理（修 Codex 自身首跑向导；真实登录永不触碰）+ 行点击/使用中行取消代理确认/
  无密钥切换确认 + 隐藏不可切换占位行 + 侧栏状态联动。手测五轮 PASS
  （2026-08-18 用户确认）。打磨项拆到 IDEA-5。

### IDEA-5 Provider 管理打磨（2026-08-18 提出；**2026-08-19 实现，手测四轮 PASS，2e 收口**）

- **实现收束**（分支 `idea-5-ki7-provider-polish`，5a-5e 全阶段）：
  - **5a KI-7①**：`--mode` 默认值修复 + CLI/UI 双层回归测试。
  - **5b KI-7②**：provider 面板可见性翻转即重拉（v-show 常驻面板的外部同步）。
  - **5c 数据面**：adapter `provider_view` 脱敏 `role_env`（白名单，凭据键
    结构性缺席）+ `known_models`（预置历史∪现值）；`fetch-models` op（详见下）；
    宿主 `aisc cc-switch fetch-models` + Rust `cc_switch_fetch_models`
    （`cc_switch_call` 拆值返回核心）；**legacy 预置 ownership 扩展**
    （zhipu/kimi/volcengine 的 MODEL 纳入 `_merged_claude_env` 合并，
    `_model_history` 判据；BASE_URL 维持 legacy 重置语义）。
  - **5d UI**：编辑表单五槽映射（保存五键全显式，空=null 删键；codex 单
    model 位不变）+ datalist 三级降级 + 切换反馈三件套（行脉冲/chip 缓入/
    顶部 toast，reduced-motion 退化）+ **[1m] 声明开关**（MODEL/OPUS/SONNET
    行内复选框追加/剥离，datalist 自动补变体，与 cc-switch 映射同构）。
  - **fetch-models 源码考古**（用户手测驱动的三轮迭代）：上游 CLI 子命令打
    anthropic 兼容 base；**读 cc-switch 源码 `services/model_fetch.rs` 后原样
    移植其多候选 URL 链**（版本段 base 先 `/models`；普通 base `/v1/models`；
    anthropic 后缀剥除后根上 `/v1/models`+裸 `/models`——DeepSeek 官方即无
    /v1）× 双认证头（Bearer/x-api-key）；**JSON 链为主路径**（确定性
    data[].id），CLI 人读文本降为最后兜底并加词形过滤（真 id 须含数字/-/./_
    或 ≥10 字符——修掉表头词混入 datalist 的手测问题）。
  - **手测四轮**：自定义添加成功；bash TUI 改动回面板即见；拉取经新 key
    全链真拉（旧 key 为 DeepSeek 端点级受限，聊天正常/models 全拒——文档
    明列此场景）；[1m] 开关确认正常。
- **挂账**：fetch-models 成功态输出格式按防御解析处理（未再实测冻结——
  JSON 主路径已确定性）；上游 `provider quota`（配额查询）可作用量面板
  增强数据源，待用户提出。

### IDEA-2 mihomo 订阅导入 + 「网络与用量」面板 + Provider token 统计（2026-08-17 提出；**2026-08-19 实现，手测三轮 PASS，2e 收口**）

- **实现收束**（分支 `idea-2-network-usage`，2a-2e 全阶段）：
  - **2a 探针**：usage schema 用宿主 db 副本直接冻结（数据落点
    `proxy_request_logs`；rollups 是上游缓存不读；providers 只取
    id/app_type/name）；**用户机场订阅源有 TLS 指纹墙**（curl/openssl/
    python/.NET/curl_cffi 全被 ClientHello 掐，真 Chrome 过但拿 HTML；
    clash-verge 刷新正常 → Rust reqwest 能过，挂账首选 Rust 侧下载）。
  - **2b 订阅数据面**：`aisc network subscription import/import-file/
    refresh/show/clear`（URL 与内容均走 stdin；信封只出脱敏串；
    TLS_REJECTED 稳定错误码）；数据根 `config/mihomo/subscription.yaml` +
    快照（source: download|manual）；legacy 一次性采用；向导重定向；
    **start_runtime/plan_run 自动解析订阅（修缺口①：Workbench proxy 容器
    从此真挂配置）**；fingerprint 增 `proxy_config_sha256` 仅 proxy 模式
    （direct 字节级不变，订阅刷新→下次 start 走既有重建引导）。
  - **2c 用量数据面**：容器 adapter `usage` 操作（created_at 单位嗅探 ms/s，
    表缺失优雅降级；`--since` 宿主算 epoch，today=本地零点）+ 宿主
    `aisc usage overview [--range][--workspace]`（live=容器内 exec 宿主永不
    直开 WAL 库；停止用 cache/usage 快照，today 跨日不复用；跨工作区
    (app, provider_id) 聚合）。
  - **2d 面板**：`NETWORK_USAGE_TAB_ID` 设置同层哨兵（chip/▾ 菜单/App.vue
    接管）+ `stores/usage.ts`（组件零直接 ipc，层契约守门）+ 面板两节 +
    共享 SubscriptionForm（URL/粘贴内容）+ 向导内嵌 + LaunchSummary 警示。
    偏离：preflight warning 未做（can_start 语义下 warn=变相 fail）。
  - **手测三轮**：一轮面板/导入/摘要/向导/proxy 实跑（**mihomo 实际生效实证：
    容器内 gstatic 204 / api.anthropic 403**）；二轮修导入后不切视图/无反馈/
    加 token 单位（自动/k/M/纯数字）与币种（USD/CNY 固定汇率 7.25）切换 +
    价格未知标记（有请求费用 0→未命中定价表）；三轮修工作区选择器被服务端
    过滤收窄（改全量拉取客户端过滤）。
- **顺带修复（手测期间发现）**：KI-6 Docker 检测（引擎探测改命名管道
  `\\.\pipe\docker_engine` 直发 /_ping；每用户安装位补进 Rust/NSIS/Python
  三处探测链；Workbench 给 aisc 子进程注入 docker bin 到 PATH）；entrypoint
  mihomo 探测误报（容器无 procps，pgrep 不存在 → PID+kill-0 判活 + 3 轮重试）。
- **挂账**：指纹源自动下载（Rust reqwest 方向已定）；订阅把用量做进假节点名
  （`已用流量：4.03 GB` 等）——可作 userinfo 头缺失时的用量兜底解析；
  KI-7（provider 自定义添加报 unknown preset / 外部 cc-switch 改动不同步）。
- 单位/币种偏好现为会话级（不持久化），持久化需求待用户提出再挂账。

### IDEA-3 顶栏设置按钮去留 + 工作区级 tab（2026-08-17 用户提出；**2026-08-18 实现并手测 PASS**）

- **已实现**（分支 `idea-3-workspace-tabs`，3a..3f 六子阶段）：门面抽取
  （WorkspaceRuntime 工厂 + runtime store 可写 computed 逐键转发）→ Rust
  取消 token 键化 → workspaces 中枢（launcher 物化/上限 3/关闭即时摘
  chip+后台静默收尾/合并历史保存/退出聚合）+ 双层条（真并行，活跃 5s/
  后台 25s 轮询）→ 设置升工作区层（对话框退役、Ctrl+,、+ ▾ 入口、
  `ui.default_new_page`）→ 快捷键（Ctrl+PgUp/PgDn、Ctrl+Alt+数字，WebView2
  实测可用）+ watcher 事件带路径 + explorer per-path 缓存。条模型（用户
  三轮手测定稿）：**只显示真实打开的页**（启动器 chip 仅聚焦时显示），
  chip 显示文件夹名、同名冲突才显全路径。用户四轮手测确认收束。
- **对已批方案的一处偏离**：工作区容器用 `:key` 重挂载而非全挂 v-show
  （组件全绑门面，v-show 多实例全渲活跃区；Terminal 重挂重放缓冲是既有
  安全设计，还改善内存上界）。

## 进入 Stage 7 前

- [x] 确认归档 `aisc-next` 的最终提交和迁移说明（最终提交 `f5a74e5`；目录随 followup 计划入库整体移入 `docs/archive/completed/`）；
- [x] 记录现有 workspace 根目录中会被迁移的文件清单（fresh 初始化实测，见 `stage-7-windows-data-root/02-domain-contract.md` Legacy layout 实测清单）；
- [ ] 定义 `AISC_DATA_ROOT` 的开发/测试覆盖和权限策略（7a-contract 实现内容）。

## Stage 7

- [x] Windows path resolver、workspace hash、lock、atomic replace（7a/7b）；
- [x] legacy scan、迁移 manifest、dry-run、rollback 和损坏隔离（7c/7d）；
- [x] CLI、Workbench、container mount 全部改用 resolver（7e）；
- [x] fresh/upgrade/multi-instance/long-path/disk-full 真机验收（7f，A-DATA01..05 PASS，
      用户手测 PASS 2026-08-17；磁盘不足为 mock 门，OneDrive 目录留发布前矩阵）。

## Stage 8

- [x] 预研最新 stable cc-switch 的 daemon/API 和数据库锁行为（8a 完成 2026-08-17：
      latest=v5.10.1/DB schema v16/无 HTTP API→Path B adapter/官方 CLI CRUD 表面+
      secret stdin+stdout 回显风险全固化；DeepSeek 官方 fixture 落
      `container/lib/deepseek-official-facts.json`；详见
      `stage-8-cc-switch-provider-ui/8a-discovery-report.md` + D8-08..D8-12）；
- [x] 实现 stable latest resolver、资产架构校验、SHA-256 和 image labels（8b：domain 选择+application resolver（分页/限流/TTL cache/manifest 离线）+6 build-arg+OCI labels+21 测试；真机 dry-run 验证 latest→v5.10.1/digest 一致）；
- [x] 从官方 DeepSeek 文档生成 fixture，确认字段、模型 ID、endpoint 和 `[1m]`（8a 四页取证 + 8c fixture 驱动 preset + ownership 刷新 +13 测试；A-CS03/04 自动化绿）；
- [x] 冻结 Provider UI protocol，完成 list/add/edit/delete 和 secrets redaction（8d 容器 adapter + 宿主 CLI 23 测试；8e Workbench 虚拟 tab + Rust stdin 通道 + store 分层）；
- [x] 验证 UI/CLI 同库、并发写、preset refresh 用户覆盖和升级迁移（8f 真机 + 自动化：A-CS01..07 全 PASS，用户手测 PASS 2026-08-17；切换激活记 IDEA-4）。

## Stage 9

- [ ] 创建 `experiment/workbench-winui3`；
- [ ] 搭建 WinUI shell、native terminal control、session/tab 和 CLI bridge；
- [ ] 用同一 contract fixture 实现 Provider tab；
- [ ] 完成等价验收、性能/崩溃/高输出报告和替代决策建议。
