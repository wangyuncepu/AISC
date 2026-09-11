# 2.1.11 开发计划——Provider 体验 · UI 对标 VS Code · 历史与生命周期修复

> 2026-09-10 开池（用户 todo v2.1.11-target + 审问裁决）。
> 版本号沿 2.1.10 惯例：开发期保持 `2.1.10.dev0`，封版提交统一四件套 bump。
> 阶段表（手测 PASS → merge develop → CI 绿后划完成）：

| 阶段 | 内容 | 状态 | 文档 |
| --- | --- | --- | --- |
| P1 快修批 | provider key 显隐（已配置态+可查看）/ 历史恢复顶部空白诊断修复 / 忘记工作区勾选清理+可选导出 | **手测 PASS（r1-r8，含 5 项增补），已并 develop** | [p1-manual-test.md](p1-manual-test.md) · [decisions.md](decisions.md) |
| S2 传输统一 | 本地全命令切池化 serve + 版本配对驱逐（D-5 两步走收官） | **手测 PASS，已并 develop** | [decisions.md D-5](decisions.md) |
| P2 UI 批 | 反馈语法（全局 Toast+空态 CTA）→ topbar 整行砍除（status 右移+窗口标题动态）→ rail 图标化（activity bar+Ctrl+B）→ 命令面板（Ctrl+Shift+P）→ 设置页搜索 | 待做 | [ui-review-vscode.md](../archive/2.1.10-dev-plans/ui-review-vscode.md)（输入） |
| Shell 重设计 | rail 底部图标+浮窗化（W1）→ 菜单栏+一窗一工作区（W2+W3 合并）| 拆解就绪待实施 | [shell-redesign.md](shell-redesign.md) |
| P3 调研批 | Slurm/PBS 工作流方案（用户提供实际场景）/ provider 热切换可行性（输出文档，实施下轮） | 待做 | [decisions.md](decisions.md) |
| 收口 | devlog / 阶段表 / 手测清单 / VERSION 四件套冻结 / plans 归档 / release | 待做 | — |

## 关键裁决（2026-09-10 审问）

- **topbar**：整行砍掉（A）——status 图标右移 WorkspaceBar、窗口系统标题
  动态设为当前工作区名；「AISC WORKBENCH」静态字样移除。
- **忘记工作区**：预览弹窗加「同时清理生命周期文件（agent 记忆/配置/
  状态，**不碰工作区用户文件**）」勾选框默认勾选；勾选时给「先导出 zip」
  按钮（导出位置用户选）。
- **Slurm/PBS**：先调研出方案文档（用户后续提供实际工作流场景），
  实施下轮。
- **provider 热切换**：先调研可行性（claude 进程启动时读 env，真热切
  预期不可行；调研「新会话即时生效」与现状差距后定案）。
- **UI 优化范围**：审查清单四项全做 + VS Code 补充挖掘（底部状态栏/
  tab 活动指示/面板最大化）排 P2 之后视余力。
