# 2.1.10-dev 周期计划

> 池开启：2026-09-07。上周期 2.1.9-dev 已发布归档（`docs/archive/2.1.9-dev-plans/`）。
> VERSION 冻结前保持 `2.1.9.dev0`（沿 2.1.9 周期惯例，四件套 bump 在封版提交统一做）。

## 周期主题：CLI 远程化（VS Code Remote 式）+ 基础 fix 批

用户目标（`docs/todo.md` # v2.1.10-target）：

- **new feature**：一台机器上的 aisc-cli 可与其它机器上的 Workbench 通信，
  Workbench 可选择与哪台机器的 CLI 通信。先调研 VS Code（SSH remote /
  codeserver）的实现方式。
- **fix-1**：历史页 claude/codex 图标辨识度提升。
- **fix-2**：aisc-cli 命令优化（含 20260806 遗留：`run` 解耦引导混乱、更新命令）。
- **fix-3**：资源管理器、bash tab 行等非终端区域可拖动 + VS Code 式可隐藏折叠。

散落挂账（todo.md 各节 + 2.1.9 遗留 backlog）本周期**暂不处理**（D-1 裁决），
Slurm/PBS 场景调研并入 R0、实施明确划出 2.1.10（D-2 裁决）。

## 阶段表

| 阶段 | 内容 | 状态 | 文档 |
| --- | --- | --- | --- |
| R0 | 调研：VS Code 远程工作逻辑与实现方案 × Slurm/PBS 场景 × AISC 可行性对照 | **完成**（D-4/D-5 裁决已收口） | [r0-vscode-remote-and-hpc.md](r0-vscode-remote-and-hpc.md) |
| S0 | **F1 SSH 工作区剥离与封存**（D-6：错误尝试，周期首任务） | **完成**（2026-09-07，门禁全绿；用户数据处置 §3 待逐项确认） | [f1-strip-plan.md](f1-strip-plan.md) |
| R1 | 传输抽象 + `aisc serve --stdio` PoC（version/doctor/ps 远程打通） | **完成（A5 手测 PASS 双条：本地直连 + 真 SSH 链路）**，已合并 | [r1-serve-transport.md](r1-serve-transport.md) |
| R2 | runtime 生命周期 + 终端 PTY 远程流（含 resize 带内化） | **完成（手测自动化三层 PASS：真 SSH 集成 + 真容器 e2e + UI 面 CDP 全链）**，已合并 | [r2-remote-sessions.md](r2-remote-sessions.md) |
| R3 | 文件面远程化：远端 FS API（D-5 远端权威/本地仅显示） | **完成（三层自动化 PASS：单测 12/真 SSH 0.79s/UI CDP 全链含 watcher）**，已合并 | [r3-remote-fs.md](r3-remote-fs.md) |
| R4 | svc 网关端口转发 + 机器管理页 | **完成（手测三轮 PASS，真机 nas/Debian/zsh 验收；field-fixes-r4-1..4 五批修复，含 #7 ssh 参数 shell 转义）**，已合并 | [r4-manual-test-round3.md](r4-manual-test-round3.md) |
| FIX 批 | 历史页图标 ✅ / FIX-2 远程体验补全：**F2-A 控制面迁 serve（D-10，10 倍实测）+ F2-B 远端浏览器已合入（手测两轮 PASS）**；F2-C run 解耦待实施；CLI 更新封存（D-11）/ 面板拖动折叠（下一轮，需手测迭代） | FIX-1/F2-A/F2-B 完成；F2-C 待做 | [fix2-design.md](fix2-design.md) |

D-4 裁决：**R1-R4 全部在本周期内交付**（含文件面与机器管理），不收窄。

## 裁决记录

见 [decisions.md](decisions.md)（D-1 起）。
