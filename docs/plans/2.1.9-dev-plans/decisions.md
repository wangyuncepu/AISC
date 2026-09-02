# 2.1.9 决策与挂账记录

## D-0：周期首批范围（2026-08-31，用户裁决）

四条挂账统一清偿，方向全部由用户拍板：
- **#3 归因**：全量修复（R1 容器登记桥 + R2 CLI env 兜底 + R3 宿主推断归因）。
  探针定性：容器内不装 aisc（devlog.md:138），claude/codex 登记链路**从未**端到端
  通过（用户确认实底徽章从未见过）；SKILL.md "可省略 ID" 与 CLI required=True
  矛盾；AISC_RUNTIME_ID/AISC_TERMINAL_SESSION_ID 未见于任何 agent 文档。
- **#28 VM 闪烁**：本轮主攻修完（k3 VM 复现 → 修复 → VM 终验）。
- **#50 ble.sh**：关闭并移除（修订 2.1.8 D-1 的"保留供实验"）。
- **#53 隔离测试**：钉 AISC_DATA_ROOT 修复。CI 绿实为 7 个测试模块 import 时
  setdefault AISC_DATA_ROOT 的 env 泄漏——整 suite 跑时侥幸通过，单 node id
  任何 OS 都红（本机 Windows 已双证：suite 1044 绿 / 单 node 红）。

## D-1：ble.sh 移除（T2，2026-08-31）

修订 2.1.8 D-1（"镜像继续 vendor 供实验"）——用户裁决关闭并移除：

- `container/Dockerfile`：删除 vendor COPY 与解压 RUN 段；apt 行移除
  `xz-utils`（其为 ble.sh tar -xJf 而来，无其他消费者）；`procps` 保留
  （排障独立价值：entrypoint 进程判活曾因缺 pgrep 误报，2026-08-19 实测），
  注释改为独立理由
- `container/vendor/ble-0.4.0-devel3.tar.xz`：git rm
- `container/aisc-bashrc`：删第 3 节（AISC_BLE_EXPERIMENT 门控加载）与第 6 节
  （门控 attach）；保留 HISTFILE/history -a/SQLite 钩子（bashrc 服务 tmux
  子 shell 与 wrapper 的旧镜像回退路径）
- wrapper `_agent_argv` 的 ble.sh 提法保留（历史注释，解释 zsh 由来）
- 幽灵文本/高亮能力不受影响：zsh 套件（2.1.8 D-4）独立交付

## D-2：#3 归因根因与 R1/R2 修复（T3a/T3b，2026-08-31）

**根因（探针证据链闭合）**：镜像不装 aisc（devlog.md:138"拒绝嵌套"）→
`aisc artifact record` 在容器内不存在 → SKILL.md:53-55 兜底"列路径、落未归因"
——claude/codex 的登记链路**从未**端到端通过（用户确认实底徽章从未见过）。
伴生缺陷：SKILL.md 称"环境未提供 ID 可省略"与 CLI required=True 矛盾；
`AISC_RUNTIME_ID`/`AISC_TERMINAL_SESSION_ID` 未见于任何 agent 文档。

**R2（T3a，已落地）**：`artifact record` 的 `--runtime-id/--session-id` 缺省取
`AISC_RUNTIME_ID`/`AISC_TERMINAL_SESSION_ID`，`--agent` 缺省取 `AISC_AGENT`；
双缺报 AISC_ERR_USAGE 并点名 env 变量。宿主直跑与容器 shim 共用此语义。

**R1（T3b）容器登记桥**：
- 先验哈希：registry 用 sha256(canon)[:16]（domain/artifacts.py:147），容器
  注入的是完整 64 hex——shim 截断 `[:16]` 对齐
- `container/lib/aisc_shim.py`：仅实现 `artifact record` 的薄入口（不整装
  aisc）；schema 镜像宿主 ArtifactRecord；`/root/app` 前缀容忍归一化；
  O_EXCL 锁 + 原子替换。**偏差**：artifact_id 用 uuid5（session/path/action/
  kind 确定性）而非宿主的 uuid4——同事实重登替换而非堆叠（宿主消费两种
  id 均合法）；8 个往返兼容测试钉死契约（shim 输出可被宿主 from_dict/
  validate/list_records 读取）
- `runtime.py`：docker create 追加 `-v <data-root>/artifacts:
  /root/.local/state/aisc-artifacts` + `AISC_ARTIFACT_ROOT` env；宿主侧先
  mkdir 保证 bind mount 真实
- wrapper 增注 `AISC_AGENT=<args.agent>`
- 文档：SKILL.md 重写（env 缺省为真话、不再写死 `--agent claude`、保留
  "never absolute" 契约短语）；global-claude.md 增"交付物登记"节（经 sed 同
  时落 CLAUDE.md 与 AGENTS.md）

## D-3：R3 推断归因的落点偏差（T3c，2026-08-31）

计划原列落点含 watcher.rs；实施改为**纯前端投影**（workspaceExplorer
store）：watcher.rs:3-4 的"绝不猜测 provenance"契约原样保留——推断显式发生
在它之上的展示层（`inferred` map 与 `unattributed` 并列，切换/缓存/改名
搬移同生命周期）。规则：变更到达时若活跃 tab 是 running/starting 的
claude/codex 会话 → 归因为该 agent（ChangeBadge 新增 `inferred` 来源：agent
色 + 虚线框 + "会话期间（系统推断）"文案）；bash/cc-switch/无会话 → 未归因。
不写 manifest（推断不是事实）。

## D-4：resolver 传输层失败接入 S8b 回退（#59，2026-08-31，T3 期间新生）

`aisc build` 的 cc-switch 解析在 GitHub releases 大响应被截断时
（`IncompleteRead`，直连环境连续复现）裸崩为 PyInstaller traceback——
绕过了 S8b 设计的四级回退。根因：`IncompleteRead` 属 `HTTPException`，
不在既有 `URLError/TimeoutError/OSError` 捕获链；截断 200 体还会以
`JSONDecodeError` 逃逸。修复：两者都转
`ResolveError(CC_SWITCH_ERROR_NETWORK)`，回退链（在线→缓存→回执→无钉版）
恢复生效（a2f6407，2 条 mock urlopen 测试）。

## D-5：#28 VM 终端振荡——三轮收敛与终局（T4，2026-08-31）

**症状重定义（VM 复现实证）**：非"轮询闪烁"，而是 bash 终端区在两个
尺寸间振荡——窄态屏幕超出窗口且长行不换行，宽态适配窗口但长行换行
（教学框 CJK 双宽）。仅 RDP 远程会话 + 低分辨率出现；提分辨率 + 最大化
消失。真机从未复现。

**根因链（B-05 家族的间歇变体）**：字体链回退时，CSS 探针与 xterm 渲染
器解析到不同回退字体（cell 宽差 ~20%）；软渲染下 `actualCell` 间歇返回
null，每个 null tick 探针值重返计算 → 列数在两个相距甚远的网格间跳；
r2 曾把 sticky 改为每 tick 无条件覆写，自洽的"测量→网格→再测量"循环
仍在追自己的两个状态。

**终局修复（r2+r3 组合，VM 实证 PASS）**：
- 探针降级为**仅首屏引导**（首次拿到有效 `.xterm-screen` 测量后，本终端
  实例永不再询探针；字体/渲染重建时重置）
- sticky 刷新加 **1s 冷却**（首测即时），断掉自洽循环
- 校正 pass 门槛从 0.01px/单元格改为 ≥1px 整格溢出
- 附带两刀降源噪声：RuntimeSidebar 语义 `:key` 移出 freshness（stale↔fresh
  翻转不再整块重挂载）；explorer 1.5s 静默轮询加 identity 门控（零变化保
  持数组引用，对齐 v2.1.7 s5b 快照门控模式）

**保留物**：fit 遥测 + 振荡自诊断浮层（≥6 次/5s 自动弹出，截图即含
rect/cell/sticky/DPR/zoom 数值）——修复已生效但保留为安全网，野外复发
时第一手数据自带上门。

## D-6：归因呈现层整体降级——变更页朴素化（T6，2026-08-31，用户裁决）

**事实链**：指令回填（eb6c3d7）后 agent 自登记仍不可靠（重试手测未出
实底徽章；R3 推断虽工作但用户判定价值不足以支撑分类复杂度）。用户裁
决："技术上不成熟，先抛弃花哨分类，只保留最基本的展示变更和搜索（模糊
+正则）"。

**实施（90da41b + 7169909，净删 ~520 行）**：
- 变更页 = 平铺 watcher 变更列表 + 类型徽章（图标+色+文字）+ 共享搜索
  （字面>模糊跳字>/正则/）；删除 kind 分组/筛选 chips/归因徽章
- R3 推断层整体移除（explorer.inferred、activeAgentSession、inferred
  徽章源）；R1 桥接（shim/挂载/指令回填）**镜像内休眠保留**——无害、
  偶发可用、模型遵从度提升后可复活
- 文件树行尾的 manifest 枚举药丸（source_change 等）与行级变更徽章一并
  清除：变更信息唯一出口 = 变更页

**复活条件**（若未来重启归因）：模型对登记指令的遵从率可实测（镜像内
shim 就绪，起会话产文件统计实底率）；遵从率达标再谈呈现。

## D-7：nairong 热修——"bash 零输出退出"两轮诊断反转与传输层加固（T-hotfix，2026-09-01）

**症状（nairong 设备，v2.1.8）**：bash 标签只有前端欢迎卡可见，
会话零 PTY 输出，稍后 `[Session exited: process_exit, code 1]`
（用户初报 exit 0，截图纠正为 1）。镜像 1.45GB（本机 2.23GB）。

**第一轮（fit 假说，HOTFIX1，证伪）**：误判为 #28 fit 塌缩家族——
但用户实测装包无效且自诊断浮层未触发（浮层只在网格振荡时弹出，
没弹 = 渲染层从未收到字节）。教训：欢迎卡是前端 writeWelcomeCard
写入 xterm 的，它能显示恰恰证明渲染/字体/适配全正常。

**第二轮（排除法定位）**：CLI 所有有序失败路径最终都会往 stdout 打
`Error: ...` 或 `session ... exit_code=1`（print_session_text）——截
图中没有 → aisc.exe 带未捕获异常裸死（Python traceback → 退出码
1）→ traceback 打到 stderr，而 Rust 侧 spawn_pipe_session 把 CLI
stderr `Stdio::null()` 黑洞了 → 零可见输出。open_interactive 只捕
`APIError`，requests 层 `ReadTimeout/ConnectionError`（npipe 抖动，
非 DockerException 子类）直接穿透炸掉——与 #59（resolver
IncompleteRead 裸崩）同类病。已排除：镜像完整（1.45GB 差值 =
`npm install --no-cache` 不留缓存，构建日志 68 步全过）、容器健康
（entrypoint 全绿）、代理 env（本机带 ALL_PROXY 同链路首字节
0.04s）、docker 版本一致（双方 29.7.2）。

**HOTFIX2 修复（三层）**：
1. `docker_.py`/`docker_gateway.py` open_interactive：exec_create/
   exec_start/from_env 捕获扩到 `requests.RequestException`+`OSError`
   → orderly ProcessResult；exec_inspect 轮询容忍 ≤2 次连续瞬时失败
   （每 200ms 一发的 npipe 调用不再一抖就杀健康会话），第 3 次才
   orderly 收场
2. `commands/session.py`：`data["error"]` 透传 proc.stderr 真因（原来
   无脑 "docker command not found"），报错文本进终端
3. `pty.rs`：stderr 改 piped 并以 Output 事件流入终端（对齐真实
   `docker exec -it` 的 stderr 交错）；`session.rs` 观察者在会话终态
   落 `session_exit` 事件到 app 日志（原先 spawn 旁路 run_control，
   整条会话生命周期零日志痕迹）
测试：transport-failure 单测 6 条（两实现对称）+ stderr 流入单测 +
真实 stderr 文本断言；全量 pytest 1067 绿 / cargo 全绿。

**r3 根因闭环（HOTFIX2 的可见性立功，用户 VM 复现）**：中文用户名
VM 装包开 bash，stderr 流进终端后 traceback 直接点名——
`docker.from_env()` 在 DOCKER_HOST 未设时读 docker CLI context 的
`meta.json`，**docker-py 7.x 的 open() 不带 encoding** → zh-CN Windows
按 GBK 解码 Docker Desktop（中文环境）写入的 UTF-8 字节 →
`UnicodeDecodeError` 包成普通 `Exception`（"corrupted meta file"），
非 DockerException，直接穿透裸死。这解释了全部疑团：**只有 bash 会话
坏**（open_interactive 是全程序唯一 docker-py 路径，其余走 docker CLI
子进程，Go 的 UTF-8 无恙）；**只有中文环境机器坏**（英文环境
meta.json 纯 ASCII，GBK 恰好能解）；本机同链路实验"正常"是因为测不
出该分支。已本地伪造中文 context 逐字复现同款崩溃。

**r3 修复（双保险）**：① `ensure_sidecar_utf8()`（lib.rs 启动时
`PYTHONUTF8=1`，尊重显式覆盖）——所有 sidecar 子进程按 UTF-8 打开
文件，根治 GBK 一类；② `_client_from_env_safe`/`_default_client`
安全工厂（docker_.py + docker_gateway.py）——from_env 抛任何异常时
回退平台默认端点（显式 base_url 不读 meta.json，绕开 context 解析），
裸跑 CLI（无 PYTHONUTF8）也自愈；③ 顺手修 gateway 的隐藏 bug：
`_client_factory` 字段 default_factory 写成 `lambda: _default_client()`
——构造即急切 from_env（CJK 机器上连查询路径都会炸）且字段值不可
调用，改为普通函数默认值。测试 +4（含伪造 meta 复现断言）。

**伴生发现**：nairong 镜像是 resolver 失败后**无钉回退**构建（构建日志
#56 build-arg 为空走了手动 v5.9.0 分支）——S8b 回退链按设计工作，但
"构建完成"未提示降级，后续考虑在 build 事件里标出。另：其首日构建
直连 docker.1ms.run 拉基础镜像 ~10min（无代理直连极慢），网络环境
恶劣是这台设备的底色（也是 #59/#61 两类传输层 bug 都先在他机器上
现形的原因）。

## D-8：zsh 下 help 教学引导缺失（T7，2026-09-01，用户报障）

**根因**：教学 `help` 靠 v2.1.7 S6 的 `BASH_FUNC_help%%` 环境变量注入
（session.py → docker exec env），bash 启动时重新导入为函数；zsh 没有
环境变量导入函数的机制，2.1.8 D-4 把交互 shell 换成 zsh 后没人补这条
链——`help` 在 zsh 下"无此命令"。

**修复**：`container/aisc-zshrc` §7 直接定义 `help()`（heredoc 教学文本；
`help <cmd>` 委托 man——zsh 无 help 内建）。托管 rc 是产品自有面，不违
反 A-21766 的"不碰用户 profile"精神。**SSOT 仍在 tutorial.py**，
`tests/test_tutorial_zsh.py` 把 zshrc heredoc 与 `_TUTORIAL` 钉成字节级
相等（双处文本永不静默漂移）；bash env 注入保留（旧镜像 bash 回退路径
仍依赖）。已知边界：tmux 子 shell 的 bash 无 help（未报障，未处理）。

## D-9：镜像构建 CN 网络韧性硬化（T8，2026-09-01，用户裁决范围）

**审计驱动**：nairong 构建实锤（首日基础镜像在 docker.1ms.run 爬 10 分钟
放弃、resolver 失败静默无钉降级）。对 Dockerfile 构建期全部网络动作
过堂，风险定级：基础镜像 pull（单镜像零兜底）**高**、pip 升级
（pypi 直连无镜像无重试硬失败）**高**、npm 安装（npmmirror 单源）**
中-高**、yazi（无 preset 逃生）**中**、apt ×2（无重试）**低-中**；
mihomo/geodata/cc-switch/宿主 resolver 已是完备范式（金标准：mihomo 的
preset+镜像链+指引）。

**实施**（用户裁决：预拉链做、npm 重试+离线逃生都做）：
- **T8a** `build.py` 预拉链：本地命中零开销跳过；否则按
  `NODE_IMAGE_MIRRORS`（versions.env，1ms.run→daocloud→dockerproxy）链式
  `docker pull`（600s/个）→ 首胜 `docker tag` 本地名 → build argv 改指
  本地名（buildkit 零网命中）；全链失败 exit 4 + 三条指引。try 行走
  build.output 事件（UI 构建日志可见）
- **T8b** pip 升级：CN 走清华源 + 失败软放过（venv 自带 pip 够用）
- **T8c** npm：downloads/ 预置→**file: 清单离线安装**（`scripts/
  stage-npm.sh` 预下载）；否则外层重试 ×2 + `--fetch-retries=5`（顺手
  删掉一直非法的 `--no-cache` flag——npm 常年 warning "invalid config
  cache=false"）。**离线路线三坑实录**：① 原生二进制在平台伴生包里
  （claude 主包 27KB 纯 JS，linux-x64 伴生 95MB）；② codex 平台包是
  **npm alias**（`npm:@openai/codex@0.152.0-linux-x64`，平台包名不存在
  于 registry）——文件直装同名冲突，`npm cache add`+`--offline` 又缺
  packument（ENOTCACHED），终局 = /opt/aisc/npm 写 file: 依赖清单、
  平台包按**别名键**声明、`npm install --offline` + symlink bins（
  node:20-slim 实测零 registry 通过，claude -p 跑到模型校验层证明原生
  二进制真实落位）；③ tgz **不入 git/安装包**（.gitignore，单架构
  ~215MB）——escape hatch 按需 stage，默认单架构（--all-arches 可选），
  mihomo/geodata 小预置继续 tracked。**清理顺序重构**：geodata 段原
  `rm -rf /tmp/dl` 会删掉未消费的预置包——各段改为只删自己的文件，
  yazi 段最终清场
- **T8d** apt ×2 处外层 3 次重试（if 条件语境豁免 set -e）
- **T8e** yazi 对齐 mihomo preset 模式 + 承接 /tmp/dl 终清

**Backlog（记账未实施）**：CLAUDE_CODE_VERSION=latest 版本漂移（且
claude-code 2.1.251 要求 node≥22，基底 node:20，EBADENGINE 已现）；
NODE_IMAGE_DIGEST 未钉；resolver 无钉回退在 UI 无提示（D-7 伴生发现）。

## D-10：F1/F2 新特性立项与方案定稿（2026-09-01，用户七项裁决）

两轮只读探底（工作区身份链 / 容器-宿主网络与 MCP 注入面）+ 产品裁决
后，设计文档定稿：`f1-f2-design.md`（含触点附录与待决清单）。裁决：
F1=双向同步（影子目录=真工作区，身份链零改动，mutagen，MIT 可 vendor）；
F2=宿主 MCP（白名单默认空 + 程序级/只读筛，文本流+文件产物）；顺序
F2 先。**实施不排期**——用户裁决优化批次优先于新功能，F1/F2 等优化
议题定案后开工。注意 F2 的 P0 前置实测：WSL2 下容器→宿主 loopback
通道（--add-host host-gateway）+ proxy 模式 TUN 放行。

## D-11：优化批次立项与规格冻结（2026-09-01，三路探针 + 五项裁决）

用户报障五条（输出截断/provider 卡顿/cc-switch proxy 变 off/低配体验/
分屏×）+ 三路只读探针（前端流/渲染/分屏 · provider 链/daemon · 性能
旋钮/缓存/冷启动）后，合并规格冻结：`opt-batch-spec.md`（O1-O9 + 全局
约束 §G）。关键定性：
- 分屏× = z 序实锤（滚动条 z11/角标 z20 压过 × 的 z2）
- 截断 = 纯前端 4MB 内存护栏（服务端阻塞背压不丢字节）→ 终局磁盘
  spool（用户裁决）
- provider 全设备卡顿 = 超时层级错配（外 30s < 内层串行舞步总和）+
  codex 在线模型抓取挂在切换主路径（6s×N）→ 含舞步重构（用户裁决）
- 8G 笔记本 proxy 全 off = daemon 无 watchdog + 容器无 restart + PID1=
  sleep → OOM 后静默躺平；reconcile 的 not-real 判定雪上加霜 → 定时
  巡检自愈 + 判定容错
- 低配负载大头（用户裁定 + 探针证实）= 轮询制造的 docker 负载（慢机
  占空比 40-60%）→ 自适应退避 + WSL 内存引导，**不做 UI 动画微调打包**
- 补充实证：本机 build cache 6.7GB/4GB 可回收而清理能力覆盖不到 →
  纳入 O7；冷启动 70s 分解（全量复制 29s）→ O8；**O9 取消懒布局**
  （用户直接下令，重开工作区全量恢复）
外部证据依赖：8G 笔记本 doctor 导出、长对话恢复复现样本（独立 bug 另
开项）。

## D-12：Provider 页对标 cc-switch 桌面端（2026-09-02，调研 + 四点裁决）

手测反馈 provider 页与 cc-switch 配置能力不对等（upstream format 无 UI 为
代表）。五张桌面端截图 + 官方手册/changelog 调研后用户四点裁决 + 一条边界：

1. 长尾取舍：**图标对等做，端点测速不做**（备注/网站链接 db 列现成一并
   纳入一期）
2. 列表**完全卡片化**（弃表格）
3. codex 映射**按 preset 预填**（优于桌面端的手动添加）
4. 上游格式**双侧都露**：claude 默认 `anthropic`，codex 默认
   `openai_responses`（而非 chat）
5. 边界：**不做**桌面端的 JSON 编辑器形态

关键事实：上游格式数据层早已存在（`row.meta.apiFormat`，`_db_merge_meta`
通道）——纯 UI 缺口。设计全档 →
[provider-parity-design.md](provider-parity-design.md)（组件结构/契约变更/
测试矩阵/实施序列 P1-P4）。排期：opt-batch 收口后，或用户点名提前。
