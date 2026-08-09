# Windows 平台依赖

AISC Workbench（Windows）运行依赖：

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| WebView2 Runtime | Tauri 渲染引擎 | 安装器自动处理（`downloadBootstrapper`，联网下载静默安装） |
| Docker Desktop | AISC CLI 容器运行时 | 安装器检测 + winget 引导安装（`Docker.DockerDesktop`） |
| Python 3.12 | 备用 CLI 分发（pip 安装 `aisc`） | 安装器检测 + winget 引导安装（`Python.Python.3.12`） |
| winget（App Installer） | 安装器内安装依赖的通道 | 缺失时安装器引导打开 Microsoft Store（App Installer 页面） |

## 安装器行为（S4.1.b）

NSIS 安装器在选完安装目录/开始菜单后显示 **Environment Check** 页：

- 检测 Docker Desktop（`%LOCALAPPDATA%\Docker\Docker Desktop\Docker Desktop.exe` 或 HKLM 注册表路径）、Python 3（`HKLM/HKCU \SOFTWARE\[WOW6432Node\]Python\PythonCore`）、winget（`where winget`）。
- 每项缺失时，点 **Install missing dependencies** 后安装器经 winget 安装缺失项（可能触发 UAC 授权提示，属预期）。安装失败不阻断安装器，Workbench 首启 preflight 会再次报告缺失。
- Docker 已安装时提供 **Start Docker Desktop** 按钮；winget 缺失时提供 **Open Microsoft Store** 按钮（App Installer 9NBLGGH4NNS1）。
- **Skip** 跳过依赖安装，继续安装 Workbench。
- WebView2 由 Tauri 原生 section 处理（`bundle.windows.webviewInstallMode.downloadBootstrapper`），不在检测页安装。

## 验证清单（Windows 实机）

- 全新环境（无 winget/Docker/Python）：检测页全缺失 → 装依赖（UAC 授权）→ 完成后启动 Workbench → CLI discovery 正常。
- 已有 Docker + Python：检测页全绿 → 直接继续。
- Docker 已装未运行：「Start Docker Desktop」按钮启动成功。
- 打开目录 → preflight → 点「构建镜像」：Docker Desktop 运行中应完成镜像构建（安装版 CLI root 发现走随装 `aisc-bundle\`，与 cwd 无关；Linux dev 正常是因为 cwd 恰好是仓库）。安装器侧随装 bundle 由 `nsis-installer.yml` staging + 静默安装冒烟验证。
- Skip 路径：Workbench 首启 preflight 报告缺 Docker，不崩溃。
- 覆盖升级旧版本正常；卸载不删用户数据（`%APPDATA%\cn.aisc.workbench` 保留）。

## 实机修复复测（docs/问题.txt 4 项，2026-08-08）

1. **装完 Docker 引导启动**：全新环境装完 → Finish 页勾选启动 → Docker Desktop 打开（license 确认）→ Workbench 启动。
2. **Docker 未启动识别**：摘要页 docker gate 红 → 点「启动 Docker」→ Docker Desktop 打开 → 自动轮询重新检测 → 变绿 → Start 可用。
3. **console 闪现**：启动/打开目录/构建等操作不再弹 Windows Terminal 窗口。
4. **构建镜像失败**：Docker 未启动时构建 → 报「Docker 引擎未运行」+ 显示「启动 Docker」按钮。


## macOS / Linux

macOS pkg 与 Linux 安装包在 S4.1.c；Linux 另需 WebKitGTK 系统库（发行版包管理安装）。
