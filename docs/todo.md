# 20260625

1. [X] 仅保留docker_version使用即可

* [X] 没有挂VPN的时候node:20-slim无法安装
* [X] 挂VPN之后可以安装，配置提示`.claude/`缺少报错，不再继续进行

1. [ ] ssh配置，windows端配置，检查是否打开ssh，如果没打开运行配置脚本

* [X] skill增加一个[github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md)（尽可能模拟/使用**Claude Code Plugin**安装）
* [X] 模型配置统一交由 cc-switch 管理

# 20260627

* [X] karpathy-skills安装后并没有被claude调用，需要主要启用；全局CLAUDE.md使用这个技能的CLAUDE.md文件（不是项目文件夹那个）
* [X] README.md使用引导统一，分为Windows，Linux，MacOS使用，各自有一键运行脚本
* [X] EADME.md中 直接运行super-claude:v1.1.2h 空白 和 bash的区别，两者使用上似乎没有区别，前者配置好之后再次登录不会调用claude
* [X] Windows一键运行脚本.bat，没有版本更新更改名称，改为“docker run -it --rm -v "%cd%:/app" super-claude:v1.1.2”
* [X] 保留之前的单次运行的使用方法，交互式+运行单个命令
* [X] 产生的Container如果用户直接关闭Terminal，不会关闭Container，需要docker手动删除（进入虚拟机之后，exit推出回windows，如果这个时候不输入exit，关闭windows的命令行，docker不关闭）
* [X] gstack没有成功安装: gstack的安装略微不同于其它的（/slash运行模式下没有/gstack./office-hour）
* [X] Caveman安装了，但是需要默认激活（默认是不激活的）
* [X] CMD运行有中文乱码问题，跨平台使用的终端方案（目前我用的是Wrap和Termius）

# 20260701

* [x] 每日skill/claude学习模块
* [X] clash翻墙配置（docker内部翻墙）— v1.2.3 完成：容器内建 Mihomo TUN 透明代理 + 多格式订阅转换（yaml/base64订阅/URI/JSON，ss/vmess/trojan/vless/hysteria2），详见 devlog
* [X] 一键启动脚本规范化配置 — v1.3.0(模块化流水线)+ v1.3.1(目录重构)完成：scripts/ 下 4 模块 + 薄入口，跨平台对等，状态解耦
* [X] claude code CLI外配置 cc-switch-cli：[github.com/saladday/cc-switch-cli](https://github.com/saladday/cc-switch-cli)；v2.1.1-dev 起作为唯一 Provider/skills 管理入口
* [X] 配置docker容器系统的python — v1.3.2 完成：apt 装 python3/pip/venv + 默认 venv /home/AISC/.venv（挂 PATH 头，绕过 PEP 668，pip install 直达），详见 devlog
* [x] 用户自定义模型
* [x] 自定义接入服务商
* [x] 兼容openai请求格式

* [x] 文件结构
* [x] 安装后的文件结构
* [x] cc-switch使用
* [x] user版本调整
* [x] 剪枝
* [x] readme_dev调整
* [x] 进程保活
* [x] docker操作
* [x] 使用流程捋清楚、aisc使用引导、tool
  * [x] 初次使用cli环境配置
  * [x] config环境配置
  * [x] docker管理
  * [x] claude

# 20260730

1. [X] 更新 README.md 的 `aisc run` 前台运行容器说明，补充 `--workspace`（使用指定目录作为工作区）的用法
2. [X] 更新 README.md 的「Codesome｜Codex 与 Claude Code 二合一服务」部分：说明下单入口变更为 <https://meta.codesome.cn/?aff=FAP2ASVX>、注册后可自助创建 AFF 并查看邀请情况、满 100 可提现，并参考 `doc.codesome.ai` 介绍 Claude、Codex 及二合一服务
3. [X] 检查 `aisc switch --quick` 是否可用及其实现逻辑，并为 cc-switch 常见供应商提供除 API Key 外的一键配置：DeepSeek、Claude 使用 Codex 订阅、火山引擎 Ark、智谱 Z.ai、Kimi
4. [X] 检查容器内代理/翻墙设置，重点排查与 cc-switch 的冲突，并验证 Docker 容器内可通过官方渠道访问 Codex
5. [X] 移除 README.md 开头的版本要点内容
6. [X] 完善 Docker 直接引导安装流程，实现开箱即用
7. [ ] 增加 Claude/Codex 基本使用方法与技巧，重点建设可由大家共同更新的协作文档，并参考 Codesome 文档系统
8. [ ] 更新飞书知识库 ：支持同步在线文档，并结合 Obsidian 管理本地知识库
9. [x] 调研适合 AI 稳定访问和读取网页的方案
10. [x] 准备一套使用演示材料，PPT+解说词+实机演示。


# 20260806
- [x] Workbench S4.1.b：Windows NSIS 定制安装器（依赖检测 + winget 引导装 Docker/Python/WebView2）— CI 构建验证通过（产物 setup.exe），实机手测进行中（docs/问题.txt 4 个问题已修：Docker 引导启动/引擎检测/console 闪现/构建失败，待复测）
- [x] 修复安装版 Workbench「打开目录 → 构建镜像」失败（2026-08-08）：NSIS 安装器随附 aisc-bundle（CI staging + 静默安装冒烟）+ build --events 流式捕获跨平台化（_drain_threads + _kill_child）+ vendor/checksums.txt 刷新，见 devlog S4.1.b 修复
- [x] 安装向导增加语言选择（英/简中），全中文安装（2026-08-08）：languages + displayLanguageSelector + LangString DEP_* 本地化，见 devlog S4.1.b
- [x] 安装器依赖检测修复 + winget 隐藏终端（2026-08-09）：Docker 查真实路径/卸载键、Python 枚举 PythonCore 版本键（32/64 视图）、ExecWait→nsExec::ExecToLog（进度进安装日志）+ 非 0 退出重检测，见 devlog S4.1.b
- [ ] 临时模式下，cc-switch不可用
- [ ] aisc run命令解耦，引导混乱，用户感到费解
- [ ] agent加上Pi/opencode
- [ ] aisc cli的更新命令优化
- [x] 预配置的deepseek配置项错误，修复
- [ ] 预配置的codesome配置项错误，修复
- [x] runtime内，cc-switch显示异常（表现为终端显示不及时，能正常使用TUI，但是选择的位置不到对应区域时，对应区域显示的是乱七八糟的TUI结构，应该是旧的。且在windows下，TUI不会随窗口变化自适应）
- [x] 界面字体太小，增加设置页，可以设置软件各类属性 — 2026-08-10 Step 3/7 完成：typed settings + 设置对话框 + UI 字号缩放（自适应窗口）+ 终端字号/行高/回滚/渲染器
- [x] 通过winget安装docker desktop并启动，从引导界面勾选打开workbench，打开的workbench，无法内启动摘要界面无法正常检测，且点击启动docker也无效。而关闭该workbench，重新打开，就可以成功识别docker。— A+C 已实现（自动重试 preflight + CLI 绝对路径兜底）；复测发现 2 新问题已修（空目录误报冲突：resolve_conflict 仅限真冲突；构建失败：docker-credential-desktop PATH 兜底），2026-08-09 待最终复测
# 20260810

- [x] codex 打开即进默认配置（login_required 直接开会话，终端内登录）——用户决定保留数据驱动行为（A-G08-2 只拦 not_configured）；若日后想更保守（login_required 也先进 guide 配置页），改 `runtime.ts` maybeOpenCreated 条件为 `["not_configured", "login_required"].includes(...)`（代码内已有 TODO 注释 + 2026-08-10 决策记录）
- [x] **未来路线探讨：容器内 GUI 版 cc-switch**。当前 cc-switch-cli 是 TUI 应用，经终端管道渲染到 xterm.js（Step 9 管道方案已解决编码/对齐/性能/刷新问题，体验基本可用）。但 TUI 仍有固有局限：图标/emoji 需终端字体支持、布局受终端网格约束、无鼠标交互（部分 TUI 框架支持但受限）。若在容器内增加 GUI 版 cc-switch（如 Web 前端 + 后端 API），Workbench 可通过 webview 直接打开 GUI 版，绕过终端层。优势：完整 Unicode/emoji、自由布局、鼠标交互、更接近原生应用体验。需评估：cc-switch 是否有或可加 Web UI 模式、容器内端口暴露方式、Workbench webview 集成路径。保留 cc-switch-cli 作为终端备选。
- [x] 工作区，aisc配置文件集中在一个文件夹下，不要像现在这样太零散是否可行？
- [ ] 退出前询问用户是否想要保留runtime，若选择不想则直接删除该runtime及对应的container
- [ ] 分屏键盘导航无效（Step 16 遗留）：`Ctrl+Shift+W` 关 pane 可用，但 `Ctrl+Shift+hjkl` / `Ctrl+方向键` 移动 pane 焦点在实机 WebView2 无反应。已修到：window capture handler 生效、scope `.xterm`→`.pane`（覆盖 guide/dormant）、导航成功后 focusTabTerminal 移交键盘焦点（f409b3f），实测光标仍不动。结论：监听器/guard/`navigatePane`/焦点移交代码均已验证正常（`Ctrl+Shift+W` 同一路径可用），最可能是 WebView2 在浏览器加速器层拦截 Ctrl+Shift+字母 / Ctrl+方向键组合（`AreBrowserAcceleratorKeysEnabled` 默认开启；Tauri 2 未暴露禁用该行为的公共钩子，COM 方案已尝试并放弃）。留待之后解决，见 devlog。
- [ ] Step 16（G-17 分屏）暂时通过、小问题之后再改（2026-08-10）：用户验收"暂时算通过"。已修的：恢复布局黑屏/闪烁/布局错误、stop 丢布局、tab 标题陈旧、空状态居中、bash 卡"启动中"。遗留待改的小问题未逐一枚举，用户之后再反馈；键盘导航（上一条）为已知遗留。


# 用户体验
- [x] 资源管理器；单击，系统默认方式打开；双击，插入到对话。
- [x] 生成文件快速打开


# 手测异常/问题
- [x] 欢迎使用 AISC Workbench的初次运行环境失败，没有找到aisc cli（多次出现，从之前的版本里就有出现，但是当时没有重视）
- [x] 初次进入选择工作区页面时，显示没有aisc cli能力，点击重新检测后恢复正常（同上，多次出现，之前没有重视）
- [ ] aisc卸载、升级，要同步删除、重建docker的镜像、数据文件等配套资源，如果能同步更新container就更好了。



# UI美术动效
- 当前情况：
  - 纯 CSS，无框架无预处理器：
    - 每组件 \<style scoped\>：样式随 SFC 就地管理（App.vue / TabBar / WorkspaceBar 等都是）
    - 设计令牌 = CSS 自定义属性（Stage 6 UX-01 落的）：间距/字号/圆角/阴影/层级/时长统一为 --surface、--text-2、--radius-md、--space-2 这类变量，组件只消费变量不写死值
    - 主题：src/theme.ts 按 settings 的 ui.theme 在根元素打 data-theme（system/dark/light），变量在全局样式表里按主题重定义
    - 字号缩放：ui.font_scale 用 CSS zoom 实现（App 的 uiZoom + 终端区 1/scale 反向补偿）


- 界面截图，使用流程
- 安装开始->开启正常工作
- 功能区域
- 