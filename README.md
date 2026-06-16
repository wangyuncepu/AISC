# AutoCC — Claude Code + DeepSeek 一键安装与配置工具

**AutoCC** 是一个跨平台自动化工具，让你在 3 分钟内完成 Claude Code 的安装、DeepSeek API 接入，以及 5 个常用 Skills/MCP Servers 的自动挂载。

> 🎯 只需回答 **2 个问题**，其余全自动完成。

## 特性

- 🖥️ **跨平台**: 支持 Windows、macOS、Linux（apt / pacman / dnf / apk / zypper）
- 🇨🇳 **国内网络优化**: 全链路走 npmmirror / 阿里云 / 中科大镜像源
- 🔐 **安全输入**: API Key 密码掩码输入，不回显
- 🤖 **Claude 自配置**: Skills/MCP 由 Claude Code 自动安装，不手写 JSON
- 🐟 **Fish Shell 兼容**: 同时生成 bash / zsh / fish / PowerShell 环境变量文件
- 🔇 **完全非交互**: 安装过程无需按回车，可无人值守

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/AutoCC.git
cd AutoCC

# 2. 运行安装
chmod +x install.sh
./install.sh

# 3. 回答 2 个问题：
#    Q1: 是否使用中国大陆镜像源？ [Y/n]
#    Q2: 请输入 DeepSeek API Key [****]
#
#    ... 之后全自动完成 ...

# 4. 启动 Claude Code
source ~/.claude/env.sh   # 或 ~/.claude/env.fish (Fish Shell)
claude
```

**Windows 用户请使用 PowerShell：**

```powershell
.\install.ps1
```

若显示
```powershell
.\install.ps1 : 无法加载文件 C:\Users\VE111\Desktop\AutoCC\install.ps1，因为在此系统上禁止运行脚本。有关详细信息，请参
阅 https:/go.microsoft.com/fwlink/?LinkID=135170 中的 about_Execution_Policies。
所在位置 行:1 字符: 1
+ .\install.ps1
+ ~~~~~~~~~~~~~
    + CategoryInfo          : SecurityError: (:) []，PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess
```

则可运行如下命令开放权限：
```powershell
# 临时放行
Set-ExecutionPolicy Bypass -Scope Process

# 永久放行
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser（后选择y）
```


## 一键安装了什么

| 项目 | 说明 |
|------|------|
| **Node.js >= 18** | 若缺失则通过系统包管理器自动安装 |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` |
| **DeepSeek API 配置** | 环境变量写入 `~/.claude/env.sh`（bash/zsh/fish/ps1） |

### 5 个自动挂载的 Skills / MCP

| Skill | 类型 | 说明 |
|-------|------|------|
| **superpowers** | Plugin | 20+ 实战 Skills（测试/调试/协作/计划） |
| **document-skills** | Plugin | Anthropic 官方文档处理（Excel/Word/PPT/PDF） |
| **caveman** | Plugin | SPEC.md 压缩工具（节省 ~75% Token） |
| **gstack** | MCP | Google Cloud 命令行 MCP Server |
| **claude-hub** | MCP | 社区 MCP Server 注册中心 |

## 架构

```
用户执行 install.sh / install.ps1
  │
  ├── [引导层 Shell/PowerShell]
  │   ├── 检测操作系统 & 包管理器
  │   ├── 检测 Node.js → 缺失则自动安装（国内镜像）
  │   ├── 配置 npm 镜像源
  │   └── npm install → node install.js
  │
  └── [主脚本 Node.js + TUI]
      ├── @clack/prompts TUI（仅 2 问）
      ├── npm install -g @anthropic-ai/claude-code
      ├── 写入环境变量文件（bash/fish/ps1）
      └── claude --print --dangerously-skip-permissions
          └── Claude Code 自动安装 5 个 Skills/MCP
```

## 文件结构

```
AutoCC/
├── install.sh          # Linux/macOS 引导入口（Bash）
├── install.ps1         # Windows 引导入口（PowerShell）
├── install.js          # 主脚本（Node.js TUI + 安装 + Claude 自配置）
├── package.json        # 依赖声明（@clack/prompts, picocolors）
├── README.md           # 本文件
└── DEEPSEEK_README.md  # DeepSeek API 接入参考
```

## 支持的平台

| 平台 | 包管理器 | Node.js 安装方式 |
|------|---------|-----------------|
| Ubuntu / Debian | apt | `apt-get install nodejs` + NodeSource |
| Arch Linux | pacman | `pacman -S nodejs npm` |
| Fedora / CentOS | dnf / yum | `dnf install nodejs npm` |
| Alpine | apk | `apk add nodejs npm` |
| openSUSE | zypper | `zypper install nodejs npm` |
| macOS | Homebrew | `brew install node` |
| Windows | winget / Chocolatey | `winget install` 或 msi 直链 |
| 通用回退 | nvm | nvm + 国内镜像安装 |

## 国内镜像源

中国大陆网络环境下，脚本自动切换以下镜像：

| 环节 | 默认源 | 国内镜像 |
|------|--------|---------|
| npm registry | registry.npmjs.org | registry.npmmirror.com |
| Node.js 二进制 | nodejs.org/dist | npmmirror.com/mirrors/node |
| apt (Ubuntu/Debian) | archive.ubuntu.com | mirrors.aliyun.com |
| pacman (Arch) | 默认 mirrorlist | mirrors.ustc.edu.cn |
| Homebrew (macOS) | github.com/Homebrew | mirrors.ustc.edu.cn |
| nvm 安装脚本 | raw.githubusercontent.com | gitee.com/mirrors/nvm |

## 命令行选项

### install.sh

```bash
./install.sh               # 正常安装
./install.sh --dry-run     # 仅检测环境，不执行任何安装
./install.sh --cn          # 强制使用国内镜像
./install.sh --no-cn       # 强制使用国际网络
```

### install.ps1

```powershell
.\install.ps1               # 正常安装
.\install.ps1 -DryRun       # 仅检测环境
.\install.ps1 -UseCN        # 强制国内镜像
.\install.ps1 -NoCN         # 强制国际网络
```

## 环境变量

安装完成后，`~/.claude/env.sh`（或 `.env.fish` / `.env.ps1`）包含以下配置：

```bash
# 用户输入
export ANTHROPIC_AUTH_TOKEN='<你的 API Key>'

# DeepSeek 官方默认值（自动设置，无需修改）
export ANTHROPIC_BASE_URL='https://api.deepseek.com/anthropic'
export ANTHROPIC_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_HAIKU_MODEL='deepseek-v4-flash'
export CLAUDE_CODE_SUBAGENT_MODEL='deepseek-v4-flash'
export CLAUDE_CODE_EFFORT_LEVEL='max'
```

每次启动 Claude Code 前，执行：

```bash
# Bash / Zsh
source ~/.claude/env.sh

# Fish
source ~/.claude/env.fish

# PowerShell
. $HOME\.claude\env.ps1
```

建议将 source 命令追加到 Shell 配置文件中：

```bash
# Bash
echo 'source ~/.claude/env.sh' >> ~/.bashrc

# Zsh
echo 'source ~/.claude/env.sh' >> ~/.zshrc

# Fish
echo 'source ~/.claude/env.fish' >> ~/.config/fish/config.fish
```

## GStack 额外配置

`gstack` (Google Cloud MCP) 需要 GCP Service Account 凭据。安装完成后，手动设置：

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-gcp-key.json
```

## 常见问题

**Q: 安装过程中卡住了？**

A: 正常流程约 2-3 分钟。如果 Claude Code 自动配置阶段超时（超过 5 分钟），脚本会跳过该阶段，你可手动执行：

```bash
# 安装 Skills (Plugin)
claude plugin marketplace add obra/superpowers-marketplace
claude plugin install superpowers@superpowers-marketplace
claude plugin marketplace add anthropics/skills
claude plugin install document-skills@anthropic-agent-skills
claude plugin marketplace add JuliusBrussee/caveman
claude plugin install caveman@caveman

# 安装 MCP Servers
claude mcp add --transport stdio gstack -- npx -y gcloud-mcp
claude mcp add --transport stdio claude-hub -- npx -y @amritessh/mcp-hub
```

**Q: API Key 从哪里获取？**

A: 登录 [DeepSeek Platform](https://platform.deepseek.com)，在 API Keys 页面创建。

**Q: 支持原版 Anthropic API 而非 DeepSeek 吗？**

A: 可以，只需在 TUI 中输入 Anthropic 的 API Key。启动 Claude Code 前手动设置环境变量：

```bash
export ANTHROPIC_BASE_URL='https://api.anthropic.com'
unset ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL  # 使用 Anthropic 默认模型
```

**Q: 安装后 `claude` 命令找不到？**

A: 重新打开终端窗口，或执行 `hash -r`（Linux/macOS）刷新命令缓存。确保 npm 全局 bin 目录在 PATH 中：

```bash
npm bin -g  # 查看 npm 全局 bin 路径
```

**Q: 如何在 CI/CD 中无人值守使用？**

A: 设置环境变量跳过 TUI：

```bash
export CC_INSTALL_USE_CN=true   # 或 false
# 然后将 API Key 写入临时文件作为标准输入
echo "sk-your-api-key" | ./install.sh 2>&1  # 需脚本支持 stdin 输入
```

## 前置依赖

| 依赖 | 说明 |
|------|------|
| Bash / Zsh / PowerShell | 运行引导脚本 |
| curl | 网络环境检测、nvm 下载 |
| git | (可选) nvm 安装、插件 marketplace 克隆 |

引导脚本会自动检测并提示缺失的依赖。

## License

MIT
