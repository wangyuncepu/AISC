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
