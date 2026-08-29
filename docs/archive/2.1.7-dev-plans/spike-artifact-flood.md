# Spike · 产物面板"疯狂转圈"根因调查（S5 / Gate-S5）

> 2026-08-27。调查方法：代码路径追踪 + 结构证据（对应 02 §D 的 H1-H4 假设）；基准数据见文末（本地实测）。

## 症状

打开一个已有大量产物的工作区，产物页面长时间转圈；agent 一次性产出大量文件时尤甚。

## 根因（按贡献度排序）

### R1 · 每次打开工作区都全量重建产物索引（主因，后端）

`WorkspaceExplorer` **每次挂载**都触发 `refreshRoot()`（`WorkspaceExplorer.vue:150,177`；IDEA-3 的 `:key` 重挂载使每次工作区切换都重新挂载）→ `refreshArtifacts()` → `artifact_refresh` IPC → `import_registries()`（`artifact.rs:331`）：

1. `read_cli_registries`（:231）**逐行重解析** registry 目录下全部 JSONL；
2. `import_locked`（:339）**从零重建** BTreeMap 全量索引；
3. 序列化整个索引 + 原子写盘（锁内）。

没有变化检测——registry 一个字节都没变也要付全价 O(N)。1000 条记录 ≈ 解析+合并+序列化+写盘全链路。**"打开工作区转圈"= 这条同步链在锁内跑，`artifactsLoading` 全程为真。**

### R2 · 1.5s 轮询翻转 loading 标志（转圈的"疯狂"感，前端）

`WorkspaceExplorer.vue:156` 每 1.5s 调 `pollLoadedDirs()` → 对每个已加载目录 `loadDir(dir, force=true)` → `loadDir` **无条件** `this.loading[dir] = true`（`workspaceExplorer.ts:388`）。大目录列出耗时 > 1.5s 时，loading 永远为真；目录级 spinner（`:944`）与根级空态判断（`:826 isLoading('')`）随之持续闪烁。轮询本该是"廉价后台 diff"，却戴着用户可见的加载态跑。

### R3 · applyChangeStates 全树扫描 × 每个事件批（次要）

`workspaceExplorer.ts:370`——每次任何目录重载/每个 watcher 批都遍历**所有已加载目录的全部节点**重贴 change_state，O(总节点数) × 事件数。

### R4 · agent 产物洪峰期间 watcher 批未聚合（放大器，待 F1-F3 落地后复测再定是否单修）

## 修复方案（本轮实施）

- **F1（治 R1）**：registry 目录指纹（文件数+总字节+最新 mtime）随索引持久化；指纹未变 → `import_registries` 直接返回现有索引，跳过解析/合并/写盘。打开未变化的工作区从 O(N) 降为一次 read_dir。
- **F2（治 R2）**：轮询路径调用新的 `loadDir(dir, force, markCreated, silent=true)`——silent 时不动 `loading` 标志（用户触发的加载才显示 spinner）；loading 守卫继续防重入。
- **F3（治 R3）**：`applyChangeStates(dir?)` 接受可选目录参数，只重贴该目录；全量调用点保留给 reset 场景。

## 基准（本地实测，Rust `import_benchmark_ceiling` 测试计时，warm，2026-08-27）

| 记录数 | 全量 import（parse+merge+serialize+write） | 指纹门控（F1 后） |
|---|---|---|
| 200 | 6.5ms | 3.2ms |
| 500 | 13.9ms | 7.8ms |
| 1000 | 23.6ms | 15.4ms |

单次 import 在千条量级是几十毫秒而非秒级——但它在锁内同步执行且**每次打开/切回都付**；症状主体是 R2（1.5s 轮询翻转 loading，目录列出 > 间隔时 spinner 常亮/闪烁）+ R3（每 tick 全树重扫）叠加感知放大。F1 消掉重复全量链、F2 消掉轮询可见 loading、F3 把重扫降到单目录。真机验收以 A-21752 三条场景为准。

## 验收对照（A-21752/55）

- 打开含 1000 产物的工作区：首次打开后**切换出去再切回**不再转圈（指纹跳过）。
- 空闲工作区挂机：目录/产物页无周期性 spinner 闪烁。
- agent 洪峰场景复测：loading 收敛、无假死。

## 负向（A-21755）

- 快速切换/关闭工作区时旧代扫描不落入新工作区（既有 generation guard 测试保持绿）。
