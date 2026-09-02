# 2.1.9 开发周期

首批：四条挂账统一清偿（完整设计见本目录 decisions.md 与会话计划存档）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T1 | #53 隔离测试修复（AISC_DATA_ROOT 钉第二 tempdir） | ✅ |
| T2 | #50 ble.sh 移除（vendor + 门控 + D-1 修订） | ✅ |
| T3 | #3 归因全量修复：a=R2 env 兜底 / b=R1 容器登记桥 / c=R3 推断归因（R3 呈现层后按 D-6 降级） | ✅ |
| T4 | #28 VM 闪烁主攻（三轮收敛 + fit 遥测/自诊断浮层保留） | ✅ |
| T5 | 收尾：全矩阵回归 + 手测 + 挂账关闭 | ✅ |
| T6 | 变更页朴素化（归因呈现降级，D-6） | ✅ |
| T7 | zsh 下 help 教学引导补齐（D-8） | ✅ |
| T8 | 构建网络韧性硬化：预拉镜像链/pip/npm/apt/yazi 兜底 + 离线逃生（D-9） | ✅ |

## 优化批次（opt-batch，规格已冻结 → [opt-batch-spec.md](opt-batch-spec.md)，D-11）

| 阶段 | 内容 | 状态 |
|---|---|---|
| O1 | 分屏 × 被滚动条挡住（z 序修复） | ⬜ |
| O3 | 渲染路径遥测（WebGL 激活状态打点） | ⬜ |
| O9 | 取消懒布局（重开工作区全量恢复） | ⬜ |
| O2 | 输出截断 → 磁盘 spool + 按需回放 | ⬜ |
| O5 | cc-switch daemon 定时巡检自愈 + reconcile 判定容错 | ⬜ |
| O4 | provider 切换链重构（含舞步：抓取出主路径/超时对齐/并行/进度 UI） | ⬜ |
| O6 | 轮询自适应退避 + WSL 内存引导（docker 负载治理） | ⬜ |
| O7 | build cache 清理产品化 | ⬜ |
| O8 | 冷启动提速（出厂增量复制 + 等待收紧） | ⬜ |

外部证据待收集：8G 笔记本 doctor 导出（O5）；长对话恢复复现样本（独立 bug）。

## 后续批次（方案已定稿，等优化批次收口后排期）

| # | 特性 | 状态 |
|---|---|---|
| F1 | **远程 SSH 工作区**：双向同步（mutagen），影子目录=真工作区（身份链零改动）。方案已定稿 → [f1-f2-design.md](f1-f2-design.md)（D-10） | 方案定稿，等优化批次后排期 |
| F2 | **容器内 Agent 调用宿主工具**：宿主 MCP 服务（streamable-http，白名单+只读筛），容器经 host.docker.internal 调用。方案已定稿 → [f1-f2-design.md](f1-f2-design.md)（D-10，含 P0 通道实测项） | 方案定稿，等优化批次后排期 |
| PP | **Provider 页对标 cc-switch 桌面端**：专属编辑页+简易/高级两档+完全卡片化+上游格式双侧暴露+双侧映射编辑器。方案已定稿 → [provider-parity-design.md](provider-parity-design.md)（D-12） | 方案定稿，四点裁决齐 |

规约：VERSION 冻结前保持 2.1.8.dev0；container/ 改动后必跑 vendor-refresh；每 T 项独立提交 + 四条 CI 全绿进下一项；周期全部完成后 plans 归档。
