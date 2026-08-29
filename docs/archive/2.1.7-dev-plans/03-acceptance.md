# 03 · 验收清单与手测矩阵

> ID 规则：A-217<阶段><序号>。自动化项随阶段实现落地；手动项由用户执行，助手给步骤+预期。

## S1（A-2171x）

- A-21711 Windows 双击资源管理器中 txt/图片文件，无黑色控制台窗闪现（自动：静态断言两处 creation_flags 存在）。
- A-21712 `app_start` 日志 `app_version` 等于真实版本号（2.1.7.dev0）。
- A-21713 Provider 页出现表头，各列含义可读（zh/en）。
- 手测：双击文件 ×3 类型；启动查日志首行；Provider 页目检。

## S2（A-2172x）

- A-21721 右键历史 → 确认弹窗逐项列明删除内容（记录 + 该工作区 data 根状态），明示不动用户文件。
- A-21722 确认后：首页记录消失、`workspaces/<hash>/` 目录删除、磁盘原始工作区文件原样。
- A-21723 打开中的工作区右键删除被拒绝并提示先关闭。
- A-21724 历史默认最多 8 条 + 「查看全部 N 个」内联展开/收起。
- A-21725 点击路径不存在的历史 → 弹窗提示已移动/删除，「清除记录」仅移除条目。
- 自动：vitest 裁剪/展开/确认流；Rust forget 校验分支。
- 手测：删除一个真实工作区后去 data 根与原目录双核对；失效路径用改名目录造。

## S3（A-2173x）

- A-21731 首次启动（可清 FirstRun 状态模拟）直接进入 picker，不出现向导。
- A-21732 设置页存在"设置向导"入口，可手动打开完整向导。
- A-21733 选定工作区后环境检测嵌入启动卡片：Docker 停止时呈现修复动作，恢复后直进。
- A-21734 睡眠/恢复：开工作区 → 睡眠 30s → 唤醒，容器存活、无冲突页、终端继续可用（挂账终验）。
- 手测：含 Docker 引擎停止态走一遍选定后流程。

## S4（A-2174x）

- A-21741 构建期间默认视图为进度条+百分比+阶段说明+已耗时，无终端刷屏。
- A-21742 百分比基于 Dockerfile 真实步数；无步数信息时为阶段文案+不确定进度（不伪造%）。
- A-21743 「详细日志」抽屉可展开查看完整原始输出，默认收起。
- A-21744 Docker 一键安装等待期显示已耗时心跳（≥每 5s 更新），超时前 30s 有预告。
- 手测：删镜像后重建观察进度；停 Docker 走安装路径观察心跳（VM 或宿主二选一）。

## S5（A-2175x）

- A-21751 `spike-artifact-flood.md` 调查报告：复现数据、根因结论、修复方案，经用户过目。
- A-21752 修复后：500 产物目录打开工作区，产物面板 ≤2s 出列表、无持续转圈、CPU 无尖峰（前后对比数据留档）。
- A-21753 轮询重绘：低分辨率 VM 下界面无肉眼可见周期性闪烁（复测 KI-3 环境场景）。
- 手测：构造大产物目录 + VM 复测闪烁。

## S6（A-2176x）

- A-21761 首启 bash 首屏为速查卡（≤12 行），无"AISC已启动"类横幅。
- A-21762 `help` 输出三段式分页教学 + 互动练习引导，全部中文。
- A-21763 新建 claude/codex tab 头部为对应工具速查卡，可关闭且同会话不重现。
- A-21764 教学不改变 shell 正常行为（退出/重开无残留副作用）。
- 手测：完整走一遍 help + 练习；close 重开验证不重现。

## S7（A-2177x）

- A-21771 徽章体系：类型四分类（新增/修改/删除/移动）× 来源二级角标，图标+色相区分，悬停有说明。
- A-21772 Explorer 与产物面板徽章视觉/语义一致，图例可折叠常驻入口。
- 手测：制造四类变更 + agent 归因样本目检。

## 发布门（周期收口）

- 全部阶段合入 develop、四线 CI 绿。
- 版本契约四件套无漂移；release notes（v2.1.7.dev0.md）按实收内容更新。
- 手测矩阵全 PASS 后走封版流程（tag/Draft 由用户拍板时机）。

## 审阅补充：新增验收与负向矩阵

> 下列项目为发布必过项；用于消除原清单中的不可测描述与安全空白。

### S1 补充

- A-21714 `app_start.app_version` 来自 Tauri package info（当前 `tauri.conf.json` 版本），不再来自 Cargo `0.1.0`；日志写点移动后仍是每次进程启动恰好一条。
- A-21715 Provider 表头列定义冻结并与行 grid 对齐；窄宽度下表头与内容使用相同隐藏/截断策略，屏幕阅读器能读出列名。

### S2 补充

- A-21726 使用临时 fixture workspace 和 sentinel hash 验证：forget 前后用户目录树、内容、ACL/时间戳（允许系统读取造成的 access time 差异除外）不被修改。
- A-21727 `AISC_DATA_ROOT` 自定义路径、包含空格/中文路径均只删除 resolver 返回的受控 workspace 子树；`..`、symlink/junction/reparse、hash 不匹配均 fail-closed。
- A-21728 两个 Workbench 实例/活跃 lease、启动中的 launcher、损坏 lease 三种场景均拒删；无“先删后报错”。
- A-21729 模拟 history revision conflict、目录占用、权限拒绝、清理中断：结果逐项准确、可重试，不误报全成功；日志不含配置内容或 secret。
- A-2172A host-bind toolchain 在确认项中列出并随受控子树删除；Docker named volume 若存在，行为与 Gate-S2 决策一致，绝不按名称猜测删除。
- A-2172B `…` 菜单、键盘 ContextMenu/Shift+F10、Escape/焦点回退可用；破坏性按钮不是默认焦点。

### S3 补充

- A-21735 首次启动时最小 CLI negotiation 失败仍进入全局 blocked gate；不得展示一个无法工作的 picker。
- A-21736 WebView2 不出现在 workspace 启动卡片；Docker missing / engine starting / workspace permission / image missing 分别显示正确动作。
- A-21737 失败卡片允许返回 picker、重检和诊断；失败不会自动触发 winget。修复后在同一状态链继续，无整页向导闪现。
- A-21738 设置页打开向导不会篡改当前已打开 workspace/session；关闭向导返回原设置上下文。

### S4 补充

- A-21745 冷构建、全缓存构建、多行 RUN、ARG/FROM、多 stage、拉取层有/无总字节六类 fixture 下：百分比仅在可靠时出现、单调、终态前 `<100`；不可靠时明确 indeterminate。
- A-21746 `aisc.build-events/v1`、v2、未知版本、乱序/缺 seq、部分丢失均有 fixture；未知/坏事件只降级 UI，不中断真实构建。
- A-21747 pull 字节百分比只标识“拉取基础层”，不会被当作整体构建百分比；切换阶段时文案清晰且无倒退伪象。
- A-21748 10 万行日志压力下 UI 不冻结、不无界增长；完整日志可从 operation log 打开，默认抽屉只渲染有界窗口。
- A-21749 winget 与 bundled 两条路径都每 ≤5s 提供 elapsed 心跳；窗口失焦/隐藏仍继续；超时前 30s 预告只出现一次。
- A-2174A 安装超时/取消后子进程已 kill+reap，操作可重新发起；旧 operation 的晚到事件不会覆盖新 operation。
- A-2174B 安装成功后明确进入 engine-start 阶段；安装 deadline 与 engine deadline 分别显示，最终失败原因不混淆。

### S5 补充

- A-21754 报告包含 fixture、硬件/VM、p50/p95/max、watcher/IPC/spawn/store/render/loading 计数和 before/after trace。
- A-21755 workspace 快速切换或关闭时，旧 artifact 扫描/事件不会落入新 workspace；队列有界且取消后 loading 收敛。

### S6 补充

- A-21765 `help foo`（若采用裸 help 方案）与原 Bash builtin 行为等价；非交互 shell 不注入卡片，不改变脚本 stdout/stderr/exit code。
- A-21766 profile/命令只存在镜像或本次容器受控层，不写用户 workspace、宿主 profile、持久 Claude/Codex 配置；容器删除后无宿主残留。
- A-21767 Claude/Codex TUI 速查卡上的教程入口实际可执行，不宣称 TUI 内裸 `help` 会进入 Bash 教程。
- A-21768 互动练习默认不产生计费或外网请求；真实命令前有明确确认、可取消、失败可返回教程。

### S7 补充

- A-21773 每种徽章都有记录的数据源；数据不可得时显示“未知/未归因”或不显示，不把 rename/delete 猜成事实。
- A-21774 不依赖颜色也能区分四类状态；键盘 focus、tooltip、ARIA label、高对比度/色觉差异目检通过。

### 发布门补充

- 五文件紧凑版的风险/契约/UX/观测映射已保持一致，无同一主题互相矛盾的旧文案。
- 所有开放 Gate（S2/S4/S5/S6/S7）有明确结论或明确从本次 release scope 移除；不得带“可选做/待定”进入编码完成态。
