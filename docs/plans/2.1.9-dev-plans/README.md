# 2.1.9 开发周期

首批：四条挂账统一清偿（完整设计见本目录 decisions.md 与会话计划存档）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T1 | #53 隔离测试修复（AISC_DATA_ROOT 钉第二 tempdir） | ⬜ |
| T2 | #50 ble.sh 移除（vendor + 门控 + D-1 修订） | ⬜ |
| T3 | #3 归因全量修复：a=R2 env 兜底 / b=R1 容器登记桥 / c=R3 推断归因 | ⬜ |
| T4 | #28 VM 闪烁主攻（k3 复现 → 门控修复 → VM 终验） | ⬜ |
| T5 | 收尾：全矩阵回归 + 手测 + 挂账关闭 | ⬜ |

后续批次（用户已点名，待 T5 后 brainstorming，未开工）：

| # | 特性 | 状态 |
|---|---|---|
| F1 | **远程 SSH 工作区**：双向同步（mutagen），影子目录=真工作区（身份链零改动）。方案已定稿 → [f1-f2-design.md](f1-f2-design.md)（D-10） | 方案定稿，等优化批次后排期 |
| F2 | **容器内 Agent 调用宿主工具**：宿主 MCP 服务（streamable-http，白名单+只读筛），容器经 host.docker.internal 调用。方案已定稿 → [f1-f2-design.md](f1-f2-design.md)（D-10，含 P0 通道实测项） | 方案定稿，等优化批次后排期 |

规约：VERSION 冻结前保持 2.1.8.dev0；container/ 改动后必跑 vendor-refresh；每 T 项独立提交 + 四条 CI 全绿进下一项；周期全部完成后 plans 归档。
