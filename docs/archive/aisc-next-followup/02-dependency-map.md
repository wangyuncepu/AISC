# 阶段依赖图

## 主线

```text
已完成 Stage 0–6
        |
        v
Stage 7  Windows Data Root
        |
        v
Stage 8a  cc-switch/API/Provider contract freeze
        | \
        |  `--> Stage 9 C# POC（独立分支，可并行）
        v
Stage 8b  latest build + container UI + preset implementation
```

Stage 8a 是 Stage 8 的早期门：在确认最新版 cc-switch 是否有稳定 daemon/API 前，不能决定 adapter 细节。Stage 9 可以在该门通过后启动，但不修改 Stage 8 的实现文件。

## 阶段门

| 阶段 | 开始条件 | 完成条件 |
|---|---|---|
| 7 | `f5a74e5` 基线可构建 | 新路径默认生效；旧布局迁移、回滚、锁和 Windows 真机证据通过 |
| 8a | Stage 7 path resolver fixture | cc-switch API/adapter 方案、DB 并发策略和 Provider protocol fixture 冻结 |
| 8b | Stage 8a accepted | stable latest resolver、checksum、DeepSeek preset、UI tab 和 CLI E2E 通过 |
| 9 | Stage 7 accepted + Stage 8a protocol | C# POC 功能等价、native terminal 风险结论和 branch handoff 文档完成 |

## 分支

```text
develop
  ├─ stage-7-windows-data-root
  ├─ stage-8-cc-switch-provider-ui
  └─ experiment/workbench-winui3   # Stage 8a 后创建，独立 POC
```

Stage 7/8 的数据和协议变更在用户确认后按 `--no-ff` 合并。C# 分支只在 POC 通过后另行讨论是否建立正式替代分支。

## 不允许的并行修改

- Stage 7 迁移完成前，Stage 8/9 不得各自定义 data root；
- Provider protocol 冻结前，Tauri 和 C# 不得各自发明 Provider JSON；
- C# POC 不得修改 Python CLI、container wrapper 或生产 Tauri 代码；
- latest resolver 与 Release manifest 必须共用同一版本解析 library/fixture。
