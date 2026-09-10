# R3 计划：远端 FS API 文件面（D-5 远端权威模型落地）

> 前置：R2 完成（`847cfec`：会话面 + 全仓 target 路由 + serve v1.1）。
> 目标：Explorer/预览/变更面板在远程 target 下工作于远端机器的文件系统——
> 本地仅显示、不落第二份（D-5）；工作区语义切换为「CLI 所在机器的路径」。

## 0. 现状（代码盘点 @ `847cfec`）

- Explorer 数据面：`workspace.rs` 12 个 tauri 命令（list/preview/open/reveal/
  copy_path/create_file/create_dir/copy_entry/rename + forget 族），全部
  直接操作本地 `std::fs`（lazy 树、PREVIEW_BUDGET 512KB、COPY 页大小、
  DEFAULT_IGNORE 过滤集）。
- 变更面：`watcher.rs` notify(5) 本地 watch → 分类（新增/修改/删除/移动）
  → 变更面板投影。
- 工作区校验：`session.rs canonical_workspace` 本地 canonicalize（远程
  路径会被本地 FS 语义拒绝——R2 演示时以本地路径绕过，正是本阶段要根除的）。

## 1. D-9 裁决（2026-09-07）

1. **FS 面走 serve 长驻通道**（D-8 双通道模型的既定归位）：文件树浏览/
   读文件高频 + watch 事件是推送语义——per-op ssh 不合适。fs.* op 复用
   ServeSession 的 request 多路复用；watch 事件用 R1 预留的 `event` 帧。
2. **Python watcher 引入 `watchdog` 依赖**（Linux inotify；PyInstaller
   bundle 打包）。无 watchdog 环境（老 NAS/受限容器）`fs.watch` 优雅降级
   返回 unsupported，Explorer 回退轮询（Remote 模式 list 刷新）。
3. **远端权威语义**：所有 fs op 的 path 都以远端机器为根解释；服务端做
   workspace root 之外的路径拒绝（containment，沿 F2 cwd containment 思路
   收敛在 fs.list 的 root 参数上）；「用本地软件打开」= 显式下载临时副本
   + 系统 opener；本地文件拖入 = 上传。本地永无工作区副本。

## 2. serve 协议 v1.2 追加（fs.* op 族）

```text
op fs.list    {path, offset?}        → {entries:[{name,kind,size,modified}], nextOffset?}
op fs.read    {path, maxBytes?}      → {base64, truncated, size, mediaHint}
op fs.write   {path, base64}         → {}（新建/覆盖，父目录须存在）
op fs.mkdir   {path}
op fs.rename  {from, to}
op fs.delete  {path}
op fs.watch   {root}                 → {}，此后 event 帧推送：
   {"type":"event","event":"fs.change","data":{"root":..,"paths":[{path,kind}]}}
op fs.unwatch {root}
```

- kind: file|dir；`fs.list` 服务端应用与本地相同的 ignore 语义（服务端
  无 Workbench 的 user ignore 配置——R3 先用内置 DEFAULT_IGNORE 等价集，
  用户自定义 ignore 的远端化挂 R4 机器档案）
- path 规范：`/` 起绝对路径；`.`/`..` 归一化后必须在 watch root / list
  root 的子树内（服务端拒绝，防穿越——F1 时代 browse 钉根的教训复用）

## 3. 阶段切分

- **R3a** Python：fs.* op + watchdog watcher + event 推送 + containment +
  单测（fake watcher 可注入）
- **R3b** Rust：workspace 读面命令（list/preview）Remote 分流（serve
  request→同形返回值）；Explorer 即可浏览远程树/预览
- **R3c** Rust 写面命令（create_file/create_dir/copy_entry/rename/reveal/
  open_path）Remote 分流；open_path = 下载临时 + opener
- **R3d** watcher 双路径：Remote target 下经 serve event 帧驱动本地变更
  面板；WorkspaceWatcher 抽象（Local notify / Remote serve 订阅）
- **R3e** 工作区语义：canonical_workspace/preflight target 感知（远端
  fs.stat 校验）；workspace picker 远程模式提示远端路径
- **R3f** 收口：三层自动化（真 SSH fs 往返 / 真容器 / CDP UI）+ devlog

## 4. 验收（AISC-R3-*）

- A1 serve fs.* 单测（含 containment 拒绝、ignore 等价、watch 事件注入）
- A2 Rust Remote fs 往返集成（AISC_TEST_SSH 门控，真 ssh 树浏览+读写）
- A3 Explorer 远程浏览 CDP 自动化（list→expand→preview 全链真 GUI 进程）
- A4 watcher 事件经 event 帧投影变更面板（自动化）
- A5 devlog/阶段表

## 5. 风险

- watchdog 打包进 sidecar 的体积/兼容（PyInstaller hook；Linux glibc 老
  机器 inotify 可用性——降级路径兜底）
- Explorer 分页/缓存语义在 RPC 延迟下的体验（树展开往返）——list 页大小
  与前端既有 cursor 协议对齐，避免重写前端
- serve 单连接上 fs op 与 PTY 流的公平性（同一 reader 分发，帧粒度 16-64KB
  攒批）——R2 的多路复用框架已备，观察 A3 实测
