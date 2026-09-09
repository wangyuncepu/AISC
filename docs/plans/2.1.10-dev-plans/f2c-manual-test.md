# F2-C 手测清单——run 解耦验收（真容器 e2e + Workbench 回归）

> 2026-09-09。基线分支 `fix2-c-run-decouple` `a896d0a`
> （代码 `9025044` + `38d1c8a`）。范围：fix2-design F2-C 全部九点
> （run/claude/codex/stop/runs/--resume/别名/workspaces）+ 9025044
> 三缺陷修复实证 + Workbench 回归零改动。预计 30–45 分钟。
> 反馈编号沿用 #N；PASS 后走收口（阶段表刷新 → merge develop → CI）。

## 前置准备

- [ ] Docker Desktop 运行中；`docker images super-claude` 有 `super-claude:latest`
- [ ] CLI 跑的是本分支构建（`aisc --version` 后随手验一个 F2-C 子命令在
      `--help` 里可见，如 `aisc runs --help`）
- [ ] 建两个测试工作区目录（独立小目录，勿用 AISC 仓库本身）：
      `mkdir %USERPROFILE%\f2c-ws-a %USERPROFILE%\f2c-ws-b`
- [ ] 数据根用真实根（`%LOCALAPPDATA%\AISC\data`）——D/F 组互操作验证
      依赖 GUI/CLI 同根
- [ ] 记录手测前 `docker ps -a` 快照（收尾对照清场）

## A. `aisc run` detached 激活

- [ ] **A1 基本激活**：`aisc run %USERPROFILE%\f2c-ws-a` →
      激活摘要正常（**emoji 显示为原字形，不是字面 `\U...``——
      38d1c8a 修点）；`docker ps` 见容器 Up 且**无 `--rm`**（detached
      原生生命周期）
- [ ] **A2 default 指针**：`aisc ps` / `aisc status` 显示该工作区为活跃
- [ ] **A3 别名激活**：`aisc run %USERPROFILE%\f2c-ws-b --name alpha` →
      容器名带 alpha 前缀；两工作区并存（docker ps 双容器）
- [ ] **A4 default = 最近激活**：A3 后 `aisc ps` 活跃指针指向 ws-b
- [ ] **A5 相对路径**：`cd %USERPROFILE%\f2c-ws-a && aisc run ./` →
      记录里是绝对路径
- [ ] **A6 镜像缺失**：`aisc run %USERPROFILE%\f2c-ws-a -i no-such-img` →
      明确报错 + 指引 `aisc build`，**不进向导**（解耦原则）
- [ ] **A7 dry-run**：`aisc run %USERPROFILE%\f2c-ws-a --dry-run` →
      只计划不建容器

## B. agent 顶层糖（claude/codex）

- [ ] **B1 交互 REPL**：`aisc claude` → 活跃工作区（default=ws-a）容器内
      claude 起来 → `/exit` 退出
- [ ] **B2 参数透传**：`aisc claude -- --version` → 输出 claude 版本号
      （`--` 后原样透传）
- [ ] **B3 --workspace 覆盖**：`aisc codex --workspace %USERPROFILE%\f2c-ws-b`
      → 进入 ws-b 容器（**重点：9025044 此处必崩——list/dict 错位 +
      locate_aisc_root 用错，38d1c8a 修点**）
- [ ] **B4 --name 覆盖**：`aisc claude --name alpha` 同效于 B3

## C. `aisc stop` 清场

- [ ] **C1 定点停**：`aisc stop --name alpha` → 该容器 `docker ps -a` 消失
      （stop+remove 双做）
- [ ] **C2 --all 只清 CLI-owned**：Workbench 先激活一个 GUI 工作区跑着 →
      `aisc stop --all` → CLI 两个容器清掉，**GUI 容器（owner=workbench）
      原样存活**——所有权边界核心断言
- [ ] **C3 无活跃报错**：全停后 `aisc claude` → 明确「无活跃工作区」类
      报错指引，不崩不挂

## D. 历史 `aisc runs` + `--resume`

- [ ] **D1 列表**：`aisc runs` → 时间倒序；条目带序号、`@别名`
      （alpha 可见；未命名的显示默认名）
- [ ] **D2 按序号恢复**：`aisc run --resume 1` → 按快照（image/network）
      重建激活，容器回来
- [ ] **D3 按别名恢复**：`aisc run --resume alpha`（别名最强键）
- [ ] **D4 按路径恢复**：`aisc run --resume %USERPROFILE%\f2c-ws-a`
- [ ] **D5 别名沿用**：resume 不带新 `--name` → 沿用原别名（runs 再看）
- [ ] **D6 显式旗标优先**：`aisc run --resume alpha --name beta` →
      新别名 beta 生效
- [ ] **D7 落盘形态**：`%LOCALAPPDATA%\AISC\data\config\cli-runs.json` →
      路径全绝对、含 image/network 快照与时间戳；**与 Workbench
      history.json 分立**（两文件并存互不覆盖）

## E. `aisc workspaces` 机器视图

- [ ] **E1 视图**：`aisc workspaces` → 数据根全工作区（CLI 激活的 +
      GUI registry 的）join 别名 + docker 状态；running 判定 = `Up`
- [ ] **E2 owner 区分**：GUI 拥有的工作区在列（状态如实），不误标
- [ ] **E3 --stop 批量清场**：跑两三个 CLI 工作区 + 一个 GUI 工作区 →
      `aisc workspaces --stop` → 运行中 CLI 工作区全清，**GUI 的不动**

## F. GUI/CLI 互操作（registry default 指针天然成立）

- [ ] **F1 CLI→GUI**：A 组激活后开 Workbench → 该工作区在列表/历史可见
- [ ] **F2 GUI→CLI**：Workbench 激活工作区 → `aisc workspaces`/`aisc runs`
      视图如实反映
- [ ] **F3 Workbench 回归零改动**：GUI 开关终端/文件树/切换工作区一轮
      正常（F2-C 对 GUI 路径零改动的设计验证）

## G. 孤儿治理（可选，成本高可降级）

- [ ] **G1 stale 检测**：`docker stop` 一个 CLI 容器（模拟重启残留）→
      `aisc ps` 列出 stale + 提示 `stop --all`（ownership 标签机制）
- [ ] （可选加严）重启 Docker Desktop 后同验

## 收尾

- [ ] 全部容器清干净（`docker ps -a` 对照前置快照）
- [ ] 测试目录 `%USERPROFILE%\f2c-ws-a/b` 删除与否随喜（cli-runs.json
      记录保留无害，是真实历史）
- [ ] 结果落盘：本文件勾选 + 问题记 #N → devlog 收口条目 + 阶段表刷新
      → merge develop → 推送 → 监视远程 CI
