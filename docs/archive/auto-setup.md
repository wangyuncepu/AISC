# AISC 自动环境配置指南

本文档说明 AISC 的智能环境检测和自动安装功能，实现"开箱即用"的体验。

---

## 功能概述

从 **v2.1.5** 开始，`aisc doctor` 命令具备智能环境补全功能：

- ✅ **自动检测**缺失的依赖（Docker 等）
- ✅ **交互式提示**用户是否安装
- ✅ **多平台支持**（Linux/macOS/Windows）
- ✅ **安装后自动验证**环境状态

---

## 使用方式

### 1. 运行环境诊断

```bash
aisc doctor
```

### 2. 发现缺失依赖时的交互流程

如果 Docker 未安装，AISC 会自动提示：

```
=== AISC Doctor (host) ===

  [FAIL] docker-cli
         Docker CLI not found
         Hint: Install Docker: https://docs.docker.com/get-docker/

...

============================================================
Docker is required but not installed.
============================================================

Docker is not installed. AISC can automatically install it using the
official Docker installation script.

This will:
  • Download and run https://get.docker.com
  • Install Docker Engine and CLI tools
  • Add your user to the 'docker' group (requires sudo)
  • You may need to log out and log back in for group changes to take effect

Do you want to install Docker now?

Proceed with installation? [y/N]:
```

### 3. 确认安装

输入 `y` 并按回车确认安装，AISC 将自动完成：

- 下载官方安装脚本
- 安装 Docker
- 配置用户权限
- 重新验证环境

---

## 平台支持

### Linux（完全自动化）

**支持的发行版：**
- Ubuntu / Debian
- CentOS / RHEL / Fedora
- Arch Linux
- 其他主流 Linux 发行版

**安装方式：**
- 使用官方 `get.docker.com` 脚本
- 自动检测包管理器
- 自动配置用户权限（添加到 docker 组）

**需要：**
- `curl` 命令
- `sudo` 权限

**示例输出：**
```bash
$ aisc doctor

...

Proceed with installation? [y/N]: y

Starting Docker installation...
Downloading Docker installation script...
Docker installed successfully!

Configuring user permissions...

Docker installed successfully!

IMPORTANT: You need to log out and log back in for group permissions to take effect.

After logging back in, run 'aisc doctor' to verify the installation.


Re-running diagnostics...

=== AISC Doctor (host) ===

  [PASS] docker-cli
         Docker version 24.0.7
  [PASS] docker-daemon
         Docker daemon is running

...
```

---

### macOS（半自动化）

**支持的版本：**
- macOS 11 Big Sur+
- Apple Silicon (arm64) 和 Intel (x86_64)

**安装方式：**
- 使用 **Homebrew** 包管理器
- 自动安装 Docker Desktop
- 自动启动 Docker Desktop 应用

**需要：**
- Homebrew（如未安装会先自动安装）
- 系统权限授权（需要用户交互）

**安装流程：**

1. **Homebrew 已安装：**
   ```
   Installing Docker Desktop via Homebrew...
   This may take several minutes to download (~500MB)...
   Docker Desktop installed successfully!
   Starting Docker Desktop...
   
   Docker Desktop installed and started successfully!
   
   Docker Desktop is launching in the background. This may take a minute.
   Please accept any system permission prompts and the Docker service agreement.
   
   Run 'aisc doctor' in a minute to verify Docker is running.
   ```

2. **Homebrew 未安装：**
   ```
   Docker is not installed. AISC can install it via Homebrew, but Homebrew
   is not currently installed.
   
   This will:
     • First install Homebrew (the macOS package manager)
     • Then install Docker Desktop via: brew install --cask docker
     • You will see prompts for your password and admin approval
   
   Do you want to proceed?
   
   Proceed with installation? [y/N]: y
   
   Installing Homebrew first...
   [Homebrew 安装过程...]
   Homebrew installed successfully!
   
   Installing Docker Desktop via Homebrew...
   [继续 Docker 安装...]
   ```

**注意事项：**
- 首次运行 Docker Desktop 需要接受服务协议
- 需要授予系统权限（在"系统偏好设置"中）
- Docker Desktop 启动需要 30-60 秒

---

### Windows（半自动化）

**支持的版本：**
- Windows 10 1809+ / Windows 11
- x86_64 架构

**安装方式：**
- 使用 **winget**（Windows Package Manager，系统内置）
- 自动安装 Docker Desktop
- 静默安装模式

**需要：**
- Windows 10 1809+ 或 Windows 11
- WSL2（会自动安装）
- 管理员权限

**安装流程：**

```
Installing Docker Desktop via winget...
You will see a UAC (User Account Control) prompt - please accept it.
This may take several minutes to download (~500MB)...

Docker Desktop installed successfully!

IMPORTANT: You need to log out and log back in (or restart your computer)
for the installation to complete.

After logging back in:
1. Start Docker Desktop from the Start menu
2. Accept the service agreement
3. Run 'aisc doctor' to verify the installation
```

**注意事项：**
- 需要点击 UAC 提示中的"是"
- 安装后**必须**登出/登入或重启
- 首次启动需要接受服务协议
- 如果 WSL2 未启用，Docker Desktop 会引导启用

---

## 非交互模式

在 CI/CD 或脚本中使用时，AISC 不会提示安装（避免阻塞）：

```bash
# 非交互模式（stdin 不是 tty）
aisc doctor < /dev/null

# 或在脚本中
if ! aisc doctor; then
    echo "Docker is required. Please install Docker manually:"
    echo "  https://docs.docker.com/get-docker/"
    exit 1
fi
```

---

## 手动安装

如果自动安装失败或不支持，可以手动安装 Docker：

### Linux
```bash
# 官方安装脚本
curl -fsSL https://get.docker.com | sudo sh

# 配置用户权限
sudo usermod -aG docker $USER

# 登出并重新登录
```

### macOS
```bash
# 使用 Homebrew
brew install --cask docker

# 或下载 Docker Desktop
open https://docs.docker.com/desktop/install/mac-install/
```

### Windows
```bash
# 使用 winget
winget install Docker.DockerDesktop

# 或下载 Docker Desktop
start https://docs.docker.com/desktop/install/windows-install/
```

---

## 故障排查

### 问题 1：安装失败

**Linux：**
```bash
# 检查 curl
which curl

# 检查 sudo
sudo --version

# 手动运行安装脚本并查看错误
curl -fsSL https://get.docker.com | sudo sh
```

**macOS：**
```bash
# 检查 Homebrew
brew --version

# 手动安装
brew install --cask docker
```

**Windows：**
```bash
# 检查 winget
winget --version

# 手动安装
winget install Docker.DockerDesktop
```

### 问题 2：权限不足

**Linux：**
```bash
# 确认用户在 docker 组
groups | grep docker

# 手动添加用户到 docker 组
sudo usermod -aG docker $USER

# 登出并重新登录
```

### 问题 3：Docker 安装后仍检测不到

**所有平台：**
```bash
# 验证 Docker 命令
docker --version

# 验证 Docker daemon
docker info

# 重新运行诊断
aisc doctor
```

**Linux/macOS：**
```bash
# 确保 Docker 在 PATH 中
which docker

# 如果不在，添加到 PATH
export PATH="/usr/local/bin:/usr/bin:$PATH"
```

**Windows：**
```
1. 确认已登出并重新登录
2. 启动 Docker Desktop
3. 接受服务协议
4. 等待 Docker engine 启动（托盘图标变为绿色）
```

---

## 自动化脚本示例

### 完全自动化（CI/CD）

```bash
#!/bin/bash
set -e

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    
    # Linux: 自动安装
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker $USER
    else
        echo "Please install Docker manually:"
        echo "  https://docs.docker.com/get-docker/"
        exit 1
    fi
fi

# 验证安装
aisc doctor || exit 1

# 继续使用 AISC
aisc build
aisc run
```

### 交互式安装（用户环境）

```bash
#!/bin/bash

# 运行诊断，如果 Docker 缺失会自动提示安装
aisc doctor

# 检查退出码
if [ $? -ne 0 ]; then
    echo "Environment check failed. Please resolve the issues above."
    exit 1
fi

echo "Environment ready!"
```

---

## 相关文档

- [AISC 用户手册](../README.md)
- [Docker 官方文档](https://docs.docker.com/)
- [Homebrew 官网](https://brew.sh/)
- [Windows Package Manager](https://github.com/microsoft/winget-cli)
