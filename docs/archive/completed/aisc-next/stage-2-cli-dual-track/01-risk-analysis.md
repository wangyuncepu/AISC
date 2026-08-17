# Stage 2 风险分析

> 风险编号仅本阶段使用：CLI-R01～CLI-R07。

| 风险 | 触发与影响 | 缓解/阻断门 | 关联 |
|---|---|---|---|
| CLI-R01 包元数据/入口错误 | wheel 可装但入口、版本或依赖错，独立产品不可用 | clean venv、pipx、offline wheel smoke、reproducible metadata | CLI-01→S2.1→CLI-A01 |
| CLI-R02 envelope 漂移 | sidecar 与 pip 字段/错误码不同，Workbench 误判 | versioned schema、golden fixtures、unknown round-trip、负例 | CLI-02→S2.2→CLI-A02 |
| CLI-R03 capability 协商误放行 | 新命令在旧 CLI 上执行，破坏性 fallback | capability matrix、unsupported stable code、fail closed | CLI-03→S2.3→CLI-A03 |
| CLI-R04 discovery 选错二进制 | PATH 恶意/旧版覆盖 pin，用户运行错误 CLI | 固定优先级、来源可见、绝对路径 argv、无 shell | CLI-04→S2.4→CLI-A04 |
| CLI-R05 双轨行为不等价 | 参数、退出码、timeout、redaction 分叉 | 同一 fixture/contract runner 跑 pip 与 sidecar；差异阻断发布 | CLI-05→S2.5→CLI-A05/06 |
| CLI-R06 产物/升级回滚失败 | 架构错、sidecar 缺失或升级半成品无法启动 | hash/arch manifest、clean-room、atomic install、上一版本回滚 | CLI-06→S2.6→CLI-A07 |
| CLI-R07 供应链与诊断泄密 | 依赖投毒、日志/doctor 输出携带 secret | lock/SBOM/hash、dependency audit、redaction fixture、权限最小化 | CLI-07→S2.7→CLI-A08 |
