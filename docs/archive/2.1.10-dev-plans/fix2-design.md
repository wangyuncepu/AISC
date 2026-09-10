# FIX-2 设计：远程体验补全 + CLI run 解耦（2.1.10 收官批）

> 2026-09-09 与用户讨论定稿（四块原料：20260806 ① run 解耦 + ② 更新命令；
> R4 手测一轮并入的 #2 慢 + #4 远端目录浏览器）。
> **范围裁决**：F2-A（③ 慢）+ F2-B（④ 浏览器）优先——本版本最重要功能；
> F2-C（① run 解耦）随后；**F2-D（② CLI 自更新）封存**——更新方案
> （CLI + Workbench 一体）转下周期专题再议。

## 实测依据（2026-09-09，nas = Debian13/zsh，LAN）

- 每 CLI op = 一次全新 ssh 握手 ≈ **220ms**（首连 705ms）；切机器/列表/
  探活串行叠加即秒级体感，公网按 RTT 放大。
- **Windows OpenSSH 不支持 ControlMaster**（实测 `getsockname failed:
  Not a socket`，Win32 移植已知缺失）——连接复用路线在 Workbench 宿主上
  不可行，方案对比后定 A（迁 serve）。

## F2-A · 控制面迁 serve 长驻（D-10，修订 D-7）

**D-7 原裁决**：低频控制面走 per-op ssh、流式面走 serve 长驻。
**D-10 修订**：控制面高频 op 也走 serve 长驻（ServePool 复用连接，
220ms 握手→毫秒级帧往返）；per-op ssh 降级为 serve 不可用时的回退通道。

设计：

1. **Python：serve 通用 `cli` op**——`args = argv`（如
   `["ps","--format","json"]`），服务端**进程内复用既有 CLI 命令分派**
   直调 application 层，回 envelope。一个 op 覆盖全部控制面命令，
   零逐个注册。约束：仅承载非交互 + JSON envelope 命令（分派前校验，
   交互命令回明确错误）。
2. **Rust：`run_control_target` / `run_input_target` 的 Remote 分支**
   改为走 ServePool 通道（借 `cli` op 送 argv）。**无 per-op ssh 回退**
   （用户裁决 2026-09-09）：两端版本都自管，`serve_protocol` 不匹配 →
   硬错误 + 「远端 aisc 过旧，请升级」指引（诚实失败优于静默慢速，
   同 VS Code commit 配对哲学）；serve 死亡由 ServePool 按需重建兜底，
   不留单通道独活的暗路径。
3. **协议 v1.2 → v1.3**：新增 `cli` op + ready 帧加 `home` 字段
   （F2-B 共用）。Rust 侧握手硬门同步 3。
4. **边界**：PTY 流（已是 serve）、build 事件流、subscription 下载
   等 stdin/长流命令维持既有通道，本批不迁（per-op ssh 机制仅存活于
   serve 引导拉起与 build 流两处）。
5. ServePool 健康性：断线检测 + 按需重建（复用 fs_op 既有重建语义，
   实施时核对补齐）。

测试：Python serve 单测（cli op envelope 往返/交互命令拒绝/unknown op
回退语义）；Rust Remote 分支 serve-first/回退路径单测；AISC_TEST_SSH
真机集成（nas）计时断言（同 op 握手版 vs serve 版延迟对比）。

## F2-B · 远端目录浏览器（#4）

1. **协议 v1.3 ready 帧带 `home`**（服务端 `os.path.expanduser("~")`）。
2. **Rust `remote_browse(target, path)`**：走 ServePool `fs.list`，
   钉根远端 `$HOME`，服务端 containment 复用（防穿越沿 D-9 哲学：
   `..` 段归一化拒绝、根外一律拒）。
3. **前端**：WorkspacePicker 远程模式「浏览」按钮复活（解除 R4 一轮
   #1 的禁用降级）→ 目录弹层：面包屑/上级（根处禁用）/目录进入/条目
   点选回填输入框；权限坏目录容错（行内错误不炸弹层）。交互考古 F1
   时代 popover（tag `v2.1.9-dev`，S0 剥离删除）。i18n 双语。
4. 手动输入任意绝对路径的能力保留（浏览引导、输入兜底——沿 F1 时代
   分层裁决）。

测试：containment 矩阵（穿越/兄弟/父目录拒绝）已有先例可套；前端
vitest（远程模式浏览启用/本地模式原生对话框不变）+ CDP 真机一轮。

## F2-C · `aisc run` 解耦（20260806 ①，用户设想细化定稿）

**心智**：工作区 = 长期激活态；agent = 正交入口；与 Workbench 模型统一。

1. **`aisc run <路径>`**（必选参数；`./` = 当前目录）：相对路径当场
   绝对化 → detached 建容器（`docker run -d`，**不 `--rm`**——CLI 模式
   无 GUI lease 心跳，容器靠 docker 原生生命周期存活）→ registry
   `default` 指针更新 → 输出「工作区已激活」+ 可用命令清单（claude/
   codex/switch/shell/status/stop/runs）即退出。`--image/--network/
   --label` 创建时配置保留。
2. **`aisc claude` / `aisc codex`**：顶层糖——活跃工作区（default 指针）
   容器内 exec 对应 agent，参数透传（`aisc claude -c` 续上次——容器内
   claude 原生语义）；`--workspace <路径>` 覆盖目标；多工作区可并存，
   default 指针 = 最近激活。
3. **`aisc stop [--all]`**：显式 stop + remove（当前 / 全部）。
4. **`aisc runs`**：历史列表（时间倒序）+ **`aisc run --resume <序号|
   路径>`** 恢复（按记录的 image/network 快照原配置重建激活）。
   存储：数据根 `config/cli-runs.json`——**绝对路径** + 配置快照 +
   时间戳；**独立于** Workbench history.json（那份带 layout 重字段，
   语义不同）。GUI/CLI 互操作经 registry default 指针天然成立。
5. **镜像缺失**：维持报错指引 `aisc build`（不进向导——解耦原则）。
6. **Breaking（dev 周期可接受）**：run 不再前台交互；交互需求由
   `aisc shell`（已存在，靠 registry 发现）承接。
7. **孤儿治理**：重启后 stale 容器检测复用 ownership 标签机制
   （`aisc ps` 列出 + 提示 stop --all）。

**附（2026-09-09 追加，addendum）**：
8. **别名 alias**：`--name` 即工作区别名（默认 `super-claude-station`
   表示「未命名」），record 落 alias 字段，`aisc run --resume <别名|序号|
   路径>` 按别名恢复（别名最强键，同名覆盖）；`aisc runs` 列表显示
   `@别名`；resume 不带新 `--name` 时沿用原别名。
9. **`aisc workspaces`**：机器级管理视图——扫数据根全工作区 registry，
   join 激活历史别名 + docker 实际状态（`running` = status 前缀 `Up`），
   `--stop` 批量 stop+rm+unregister 运行中的 CLI 工作区（`owner=workbench`
   的 GUI 运行时永不触碰）。修 9025044 遗留缺陷：`_resolve_by_workspace`
   误按 list 形状迭代 `list_containers`（实际返回 name→meta dict）+ 用错
   `locate_aisc_root`（应 `workspace_state_dir`），`aisc claude --workspace`
   必崩；`cmd_stop_all` 同 list/dict 错位；激活文案 emoji 双重转义成字面
   `\U...`。

测试：run/stop/claude/codex/runs/workspaces 单测（default 指针流转、
快照恢复、路径绝对化、别名解析、workspaces 视图 join/stop 抖动）；
真容器 e2e 一轮；Workbench 回归零改动验证。

## F2-D · CLI 自更新（封存）

更新方案需要整体设计（CLI 自更新 + Workbench 更新 + 侧车同步 + 发布
通道），本批不做。挂账转下周期「更新方案」专题。原型场景备忘：远程机
（nas）CLI 保活（2026-09-08 手动 wheel 推送）。

## 实施顺序与门禁

| 阶段 | 内容 | 门禁 |
| --- | --- | --- |
| F2-A | 通用 cli op + Remote serve-first + 协议 v1.3 + D-10 | pytest / cargo / 真 SSH 计时断言 |
| F2-B | home 字段 + remote_browse + picker 弹层 | 同上 + vitest / vue-tsc / CDP 一轮 |
| F2-C | run/claude/codex/stop/runs/--resume | pytest / 真容器 e2e / 手测 |
| 收口 | devlog / 阶段表 / 手测清单 | 用户手测 PASS → merge → CI |

每阶段独立分支（`fix2-a-serve-cli` 等）+ 最小提交 + `--no-ff` 合并。
