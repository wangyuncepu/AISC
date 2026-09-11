# P1 手测记录——provider 显隐 / 回放空白 / 生命周期治理（+ r4-r8 增补）

> **结果（2026-09-11）：全项 PASS（r1-r8 八轮，用户验收「可以，没有问题」）。**
> 三项计划内 + 五项手测中生长出的增补（recent 守门 / 打印快捷键 /
> serve 闸门 / 本地驻留 serve / build-cli 前置检测），全部收在本分支。

## 计划内三项

- **P1-1 provider API key 显隐**（`eee4ba0` + r2-r5 修复）✅
  已配置占位态 + 眼睛按钮按需取回明文（默认隐藏）。六层链
  ProviderEditPage → ccSwitchUi.revealKey → Rust reveal_id 参数 →
  CLI list --reveal-id → 容器 adapter。手测揪出的断点：
  - r2/r3/r4 输入框宽度三连修——真凶 `.field > span` 标签规则
    （`width:90px; flex:none`，特异度 0,1,1）压制 `.key-row`，
    终修 `.field > span.key-row`（0,2,1）
  - r4 眼睛无声无息真凶——Rust `CcSwitchProvider` 结构体缺
    `api_key` 字段，serde 静默剥掉明文（此前后端到端验证只穿到
    CLI 层没穿 Rust 层，教训收档）
  - r3 取证修正：17:00 两次失败非「旧镜像缺参」而是容器内
    SQLite WAL checkpoint 瞬时锁——adapter `read_snapshot` 改
    `mode=rw + query_only` + 三次退避重试（`42a5dc5`）
  - r5 失败可见化：store 不再吞错 + banner 第二行渲染
    technical_detail（这一行直接揪出 r6 的 serve 闸门真凶）+
    取回中脉冲反馈
- **P1-2 spool 回放顶部大片空白**（`5916605`）✅
  linearize 过滤器剥离屏幕编排序列，回放顶部不再有大片空白。
- **P1-3 忘记/清除记录的生命周期治理**（`6034a53`）✅
  勾选清理生命周期文件（默认勾，绝不碰工作区用户文件）+
  先导出 zip（Tauri save dialog，位置用户选）。

## r4-r8 增补（手测反馈生长项）

- **搬迁工作区 recent 打开守门**（r4，`edd534c`）✅：Enter 快捷键
  绕过禁用按钮直启，docker `-v` 静默重建旧路径为空目录——
  `startEnabled` 判定提升进 store，按钮/Enter/action 三处同源。
- **RUNTIME_NOT_FOUND 人话映射**（r4，`12cf6ed`）✅：冷启动窗口
  打开 provider 页不再显示「AISC CLI 返回错误」。
- **打印快捷键屏蔽**（r5，`af16a15`）✅：Ctrl+P / Ctrl+Shift+P 被
  WebView2 泄漏成浏览器打印面——App 全局 keydown 拦截（后者预留给
  P2 命令面板）。
- **serve 闸门放行 envelope 子命令**（r6，`682b7a4`）✅：远程 provider
  「cannot run over serve」真凶——`_SERVE_CLI_DENY` 一刀切拒绝
  cc-switch，改 allowlist 放行六 envelope 子命令（default-deny 不变）。
  远端同步：CLI 包 rsync + NAS 镜像重建（绕开死代理：本机推
  node:20-slim + legacy builder）。
- **本地 provider 切驻留 serve**（r7，`e1c9df5`）✅：本地/远程传输
  统一 step 1——本地池化 `serve --stdio`，实测冷 534ms / 热 10ms
  （原逐次 spawn ~1.4s）。含 spawn KI-6 docker PATH、drain_pool
  （RunEvent::Exit 排水，防孤儿——测试实证 statics 不 Drop 会漏
  aisc.exe）。**step 2（全命令迁移+版本配对驱逐）独立分支下轮**，
  见 decisions.md D-5。
- **build-cli 前置检测**（r8，`1a91850`）✅：运行中 aisc.exe 锁
  sidecar 导致构建半途失败——构建前检测并拒绝，附重建教训注释
  （CLI 源码改动必须 build-cli.ps1 + 重启 Workbench 才生效）。

## 环境性事故（记录备查）

- 仓库 C:→D: 搬迁余震两起：editable install 指 C 盘旧路径（6 测
  ModuleNotFoundError）→ 重装；`target/debug` 构建脚本产物全带 C:
  绝对路径（tauri 权限文件读取失败）→ 清 target 重编。
- 手测中两起「旧组件配新路由」：旧镜像容器缺 --reveal-id 判断证伪、
  旧 sidecar 缺闸门修复（r8 教训固化进 build-cli.ps1）。
