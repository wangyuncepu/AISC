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
