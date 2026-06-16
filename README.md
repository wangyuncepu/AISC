# AutoCC — Claude Code + DeepSeek 一键安装与配置工具

**AutoCC** 是一个跨平台自动化工具，让你的 Claude Code 在 2 分钟内完成安装、DeepSeek API 接入，以及 5 个常用 Skills/MCP Servers 的配置。

> 🎯 只需回答 **2 个问题**，其余全自动完成。

## 特性

- 🖥️ **跨平台**: 支持 Windows、macOS、Linux（apt / pacman / dnf / apk / zypper）
- 🇨🇳 **国内网络优化**: 全链路走 npmmirror / 阿里云 / 中科大镜像源
- 🔐 **安全输入**: API Key 密码掩码输入，不回显
- 🐟 **Fish Shell 兼容**: 环境变量直接写入 Shell 原生 RC 文件（`$PROFILE` / `.bashrc` / `.zshrc` / `config.fish`）
- 📄 **自文档化配置**: 生成 `AUTO_CONFIG.md`，用户复制一条命令即可完成 Skill 安装
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
#    ... 之后全自动完成环境配置 ...

# 4. 复制脚本输出的命令，在新终端中运行，完成 Skills/MCP 安装
```

**Windows 用户请使用 PowerShell：**

```powershell
.\install.ps1
```

若显示

```powershell
.\install.ps1 : 无法加载文件 C:\Users\...\AutoCC\install.ps1，因为在此系统上禁止运行脚本。
```

则可运行如下命令开放权限：

```powershell
# 临时放行
Set-ExecutionPolicy Bypass -Scope Process

# 永久放行
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser（后选择 y）
```

## 安装了什么

| 项目 | 说明 |
|------|------|
| **Node.js >= 18** | 若缺失则通过系统包管理器自动安装 |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` |
| **DeepSeek API 配置** | 环境变量直接写入 Shell 原生 RC 文件 |
| **AUTO_CONFIG.md** | 生成 Skill 安装指令文件 |

### 5 个可安装的 Skills / MCP

| Skill | 类型 | 说明 |
|-------|------|------|
| **superpowers** | Plugin | 20+ 实战 Skills（测试/调试/协作/计划） |
| **document-skills** | Plugin | Anthropic 官方文档处理（Excel/Word/PPT/PDF） |
| **caveman** | Plugin | 压缩输出模式（节省 ~75% Token） |
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
      ├── 写入 Shell 原生 RC 文件（$PROFILE / .bashrc / .zshrc / config.fish）
      ├── 生成 ~/.claude/AUTO_CONFIG.md
      └── 打印一键安装命令（用户复制运行）
```

## 文件结构

```
AutoCC/
├── install.sh          # Linux/macOS 引导入口（Bash）
├── install.ps1         # Windows 引导入口（PowerShell）
├── install.js          # 主脚本（Node.js TUI + 安装 + 环境配置）
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

脚本直接将环境变量写入 Shell 原生配置文件，新终端启动时自动生效。

**写入位置：**

| Shell | 配置文件 |
|-------|---------|
| PowerShell | `$PROFILE` |
| Bash | `~/.bashrc` |
| Zsh | `~/.zshrc` |
| Fish | `~/.config/fish/config.fish` |
| 备份 | `~/.claude/.env` |

**写入内容：**

```bash
# >>> AutoCC — Claude Code + DeepSeek >>>
export ANTHROPIC_AUTH_TOKEN='<你的 API Key>'
export ANTHROPIC_BASE_URL='https://api.deepseek.com/anthropic'
export ANTHROPIC_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_HAIKU_MODEL='deepseek-v4-flash'
export CLAUDE_CODE_SUBAGENT_MODEL='deepseek-v4-flash'
export CLAUDE_CODE_EFFORT_LEVEL='max'
# <<< AutoCC <<<
```

> 重复运行脚本不会重复写入（幂等，通过 marker 标记识别已有配置块）。

## 安装 Skills / MCP

脚本完成后会打印一条命令，复制到终端运行即可：

```bash
claude --print 'Read the file at "~/.claude/AUTO_CONFIG.md". Execute every step listed in it, in order. Verify each step. Output PASS/FAIL at the end.' --dangerously-skip-permissions
```

Claude Code 会自动读取指令文件，依次完成 5 个 Skill 的安装。

> `~/.claude/AUTO_CONFIG.md` 文件包含每个 Skill 的安装命令和验证方法，也可手动逐条执行。

## GStack 额外配置

`gstack` (Google Cloud MCP) 需要 GCP Service Account 凭据。安装完成后，手动设置：

```bash
# Bash / Zsh
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-gcp-key.json

# PowerShell
$env:GOOGLE_APPLICATION_CREDENTIALS='C:\path\to\gcp-key.json'
```

## 常见问题

**Q: 安装过程中卡住了？**

A: 正常流程约 1-2 分钟。如果网络慢，安装 Node.js 或 Claude Code 可能需要更长时间。

**Q: Skills 安装命令执行时报错？**

A: 确认 DeepSeek API Key 已正确设置在环境变量中。打开新终端后运行 `claude --version` 确认 Claude Code 可用。`~/.claude/AUTO_CONFIG.md` 中的命令也可手动逐条执行。

**Q: API Key 从哪里获取？**

A: 登录 [DeepSeek Platform](https://platform.deepseek.com)，在 API Keys 页面创建。

**Q: 支持原版 Anthropic API 而非 DeepSeek 吗？**

A: 可以，在 TUI 中输入你的 Anthropic API Key，然后编辑 Shell 配置文件中的 `ANTHROPIC_BASE_URL` 为 `https://api.anthropic.com`，并根据需要移除模型相关环境变量。

**Q: 安装后 `claude` 命令找不到？**

A: 重新打开终端窗口，或执行 `hash -r`（Linux/macOS）刷新命令缓存。确保 npm 全局 bin 目录在 PATH 中：

```bash
npm bin -g  # 查看 npm 全局 bin 路径
```

**Q: 如何卸载？**

A: 编辑对应 Shell 的配置文件，删除 `# >>> AutoCC` 到 `# <<< AutoCC <<<` 之间的内容。

## 前置依赖

| 依赖 | 说明 |
|------|------|
| Bash / Zsh / PowerShell | 运行引导脚本 |
| curl | 网络环境检测、nvm 下载 |
| git | (可选) nvm 安装、插件 marketplace 克隆 |

引导脚本会自动检测并提示缺失的依赖。

## License

MIT
