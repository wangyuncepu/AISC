> 2026-08-26 联合手测整轮 PASS（用户确认，清单与台账见 manual-test-joint.md）：生命周期/懒布局/阻断页/崩溃回收/toolchain 持久化全过。

# 验收台账与测试矩阵

## 1. 自动化验收

### CLI / Python

- [ ] 新 Runtime 写入 `lifecycle=ephemeral`、`retention=remove_on_close` 和 lease 元数据。
- [ ] 旧 registry 无新字段时可读，且不会被当作无条件可复用 Runtime。
- [ ] 同一 workspace 的并发 claim 只有一个成功。
- [ ] lease 未过期时返回 `active_other_instance`，不 stop/remove。
- [ ] lease 过期且 owner/lifecycle 可确认时 stop -> inspect -> remove 成功。
- [ ] heartbeat 由 Tauri/Rust tokio interval 写入；WebView 隐藏、最小化到托盘或前端定时器节流不会导致 lease 停止更新。
- [ ] 同一 workspace/runtime 只有一个 heartbeat writer；close/exit/cleanup 后 heartbeat 任务停止。
- [ ] 系统睡眠/休眠超过 lease 宽限期后恢复时，实例先立即 heartbeat 并对账；另一实例不得仅凭旧时间戳删除 Runtime。
- [ ] stale registry 的 container not_found 路径可重复执行且最终 registry 为空。
- [ ] Docker unavailable 不执行 remove，不把状态写成 not_found。
- [ ] unknown owner、非 Workbench owner、scope 缺失全部 fail-closed。
- [ ] remove 不删除 workspace 和 data-root bind mount 目录。
- [ ] Runtime remove 后 workspace 内的 `node_modules`、`.venv`、项目 `target` 等仍存在。
- [ ] project Runtime remove 后 data-root 的 Claude/Codex/cc-switch 配置和所选 project toolchain backend 仍存在。
- [ ] temporary Runtime remove 后 temporary toolchain 目录不可见，下一次 temporary Runtime 不会复用上次安装的用户级工具。
- [ ] project/temporary 两种模式都保留 workspace 内的 `node_modules`、`.venv`、项目 `target` 和其他文件修改。
- [ ] `apt-get`、`npm install -g`、系统级 pip/cargo 安装被明确识别为 container-only，不被报告为已持久化。
- [ ] `persistent_toolchain` 能挂载专用目录并正确注入 PATH。
- [ ] root 容器中 `PIP_USER=1`、`PYTHONUSERBASE`、`NPM_CONFIG_PREFIX` 指向当前 scope 的 toolchain，pip/npm 用户级安装后的 bin 可执行。
- [ ] Windows NTFS bind mount 与 Docker named volume 的 npm global spike 有可复现命令、版本和耗时记录。
- [ ] spike 验证 npm bin symlink、直接执行、跨 Runtime 复用以及冷/热安装性能。
- [ ] spike 任一功能门失败或依赖非默认 Windows 设置时，Windows 默认选择 named volume。
- [ ] named volume 有 owner/kind/workspace-key/schema labels，且 `runtime remove` 不删除 volume。
- [ ] 新 Runtime 能按 workspace key 找回并挂载原 named volume。
- [ ] named volume 可 inspect，并报告 backend/name/labels/占用空间/环境标记摘要。
- [ ] named volume 可导出到归档并导入空 volume；导入后工具可执行。
- [ ] named volume remove 会拒绝活跃 lease、错误 workspace key、错误 owner/kind label 和仍被 Runtime 挂载的 volume。
- [ ] 普通卸载默认保留 toolchain volume；选择删除工作区运行数据时才清理并报告结果。
- [ ] `environment.json` 只记录环境基线，不记录包清单、安装命令、API key、token 或其他 secret。
- [ ] 环境标记版本不匹配时保留 toolchain 并报告非阻断 `toolchain_incompatible` warning。
- [ ] 环境标记缺失/损坏时报告 `unknown`，不阻断、不自动删除。
- [ ] stop/remove/reconcile 操作超时后返回 unknown/failed，而非乐观成功。

### Tauri / Rust

- [ ] shutdown request 能携带多个 workspace runtime target。
- [ ] Session cleanup 完成后才开始 Runtime cleanup。
- [ ] 一个 Runtime cleanup 失败不阻塞其他 Runtime。
- [ ] shutdown report 保留每个 Runtime 的实际结果。
- [ ] tray minimize 不触发 shutdown；tray exit 触发完整 cleanup。
- [ ] close request 重复触发时 shutdown 只执行一次。

### Workbench / TypeScript

- [ ] 同一进程重复选择相同 workspace 聚焦已有 workspace，不创建新 Runtime。
- [ ] 新 workspace 每次 materialize 使用新的 runtime ID。
- [ ] close workspace 从 UI 快速移除，并后台完成 stop/remove。
- [ ] close A 不 stop/remove B。
- [ ] preflight 对 stale ephemeral 自动 reconcile，不进入 ConflictManager。
- [ ] active other instance 只显示重新检测/返回/诊断。
- [ ] unknown owner 不显示 force remove。
- [ ] history layout 仍保存，runtime ref 不驱动跨启动复用。
- [ ] placeholder tab 不伪造 running session。
- [ ] active tab 只创建一个新 Session；切换其他 placeholder 时懒创建。
- [ ] placeholder 关闭不调用 `close_session`/`terminate`。
- [ ] 旧异步 poll/cleanup 结果不覆盖当前 workspace 状态。

## 2. 真实 Docker 手测

| 场景 | 初始状态 | 预期用户行为 | 预期资源结果 |
|---|---|---|---|
| 首次启动 | 无 registry、无 container | 选择 workspace 后直接启动 | 一个新的 ephemeral Runtime |
| 正常关闭 workspace | 一个 running Runtime | 确认关闭 | Session 结束，container 删除，registry 删除，data-root 保留 |
| 项目模式依赖 | project workspace 中已有 `node_modules`/`.venv` | 关闭并重新打开 | 依赖目录保留，新 Runtime 可直接使用 |
| 项目模式 Toolchain | project toolchain 中已有用户级二进制 | 关闭并重新打开 | toolchain 保留，PATH 重新注入 |
| Windows bind mount spike | npm global prefix 位于 NTFS bind mount | 安装并运行带 bin 的包 | symlink/exec/复用/性能全部留证；失败则选 named volume |
| Windows named volume | npm/pip/cargo toolchain 位于 Docker volume | 删除 Runtime 后重新打开 | volume 保留并重新挂载，工具可执行 |
| Named volume 备份 | project toolchain 已有工具 | export、删除/新建 volume、import | 归档成功恢复，工具可执行，labels 重新建立 |
| 临时模式 Toolchain | temporary Runtime 中安装用户级二进制 | 关闭并重新打开 | 不再存在，不会从上次 Runtime 恢复 |
| 临时模式 workspace 依赖 | temporary Runtime 在 workspace 中生成 `node_modules`/`.venv` | 关闭并重新打开 | 文件仍保留，这是 workspace 数据，不是 Runtime toolchain |
| 系统级安装 | 通过 `apt-get` 安装额外包 | 关闭并重新打开 | 不承诺保留；显示 container-only 边界 |
| 高级保留 Runtime | `keep_stopped` | 关闭并重新打开 | container 保留，系统级安装可继续使用 |
| 再次打开 | 上一 Runtime 已 remove | 选择同一路径 | 新 runtime ID、新 container，无冲突页 |
| Workbench 崩溃 | running Runtime、lease 最终过期 | 重启 Workbench | 自动回收旧 Runtime 后启动新 Runtime |
| 系统睡眠/恢复 | workspace lease 活跃、Runtime running | 睡眠超过宽限期后恢复，再启动第二实例 | 第二实例先对账；不得仅凭旧时间戳删除 Runtime，原实例恢复后可继续 heartbeat |
| 旧版本遗留 stopped Runtime | owner workbench、无 lease | 打开 workspace | 自动回收，不展示 stop/remove 选择 |
| 另一个 Workbench 活跃 | lease 未过期 | 打开同一路径 | 阻断，不能自动删除另一个 Runtime |
| 外部 `docker rm` | registry 有记录、container 不存在 | 打开 workspace | 清理 registry 后启动，不进入普通冲突页 |
| Docker 关闭 | container/registry 可见但 daemon 不可用 | 打开 workspace | 显示 Docker 错误，不做删除 |
| 非 Workbench container | owner 缺失或非 workbench | 打开 workspace | 诊断阻断，不自动删除 |
| 镜像 tag 更新 | 旧 container image_id 不同 | 打开 workspace | 旧 ephemeral Runtime 回收，使用新镜像创建 |
| 托盘最小化 | running Runtime | 关闭窗口到 tray | 进程和 Runtime 保持，lease heartbeat 继续 |
| 托盘退出 | running Runtime | 点击退出 | 完整 Session + Runtime cleanup |
| 多工作区 | A、B 各有一个 Runtime | 关闭 A | 只删除 A，B 继续 running |
| 多 Tab layout | 历史有 Claude/Codex/Bash/split | 打开 workspace | 恢复结构；active Tab 新 Session，其他 Tab placeholder |

## 3. 回归检查

- [ ] `ConflictManager.vue` 不再成为普通 stale Runtime 的入口。
- [ ] UI 不出现“Runtime 已保留但用户无法继续”的死循环。
- [ ] Runtime sidebar 的高级 stop/remove 仍可用于诊断。
- [ ] `aisc runtime stop` 的 CLI 语义未被悄悄改成 remove。
- [ ] workspace 文件、Agent 配置、Provider 配置、history 未被 cleanup 删除。
- [ ] named toolchain volume 未被普通 Runtime remove、stale reconcile 或 workspace close 删除。
- [ ] “清除工作区运行数据”能显式删除 toolchain volume，并有独立确认与日志。
- [ ] release notes 和用户帮助文案明确“Runtime 临时、数据持久”。

## 4. 发布门

结论只能是：

- `PASS`：自动化、真实 Docker 和多进程边界全部通过；
- `PASS-WITH-FOLLOWUPS`：仅有不影响安全和主流程的 placeholder/文案遗留；
- `STOP`：出现误删活跃 Runtime、删除 data-root/workspace、退出后 Session/Runtime 泄漏无法对账、或两个 Workbench 可同时取得同一 workspace lease。
