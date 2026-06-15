# ==============================================================================
# Claude Code + DeepSeek 一键安装引导脚本 (Windows PowerShell)
# ==============================================================================
# 职责:
#   1. 检测 Node.js >= 18，缺失则自动安装（支持中国大陆镜像）
#   2. 配置 npm 镜像源
#   3. 安装项目依赖并启动主脚本 (install.js)
#
# 用法:
#   .\install.ps1                  # 正常安装
#   .\install.ps1 -DryRun          # 仅检测环境，不执行任何安装
#   .\install.ps1 -UseCN           # 强制使用国内镜像
#   .\install.ps1 -NoCN            # 强制不使用国内镜像
# ==============================================================================

param(
    [switch]$DryRun,
    [switch]$UseCN,
    [switch]$NoCN
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---- 辅助函数 ----

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Blue }
function Write-OK    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }
function Write-Step  { Write-Host ""; Write-Host "==> $args" -ForegroundColor Cyan }
function Dry-Echo    {
    if ($DryRun) { Write-Host "      [DRY-RUN] $args" -ForegroundColor Yellow }
}

# ---- 操作系统检测 ----

function Detect-OS {
    Write-Step "检测操作系统..."

    $os = Get-CimInstance Win32_OperatingSystem
    Write-OK "操作系统: $($os.Caption) ($($os.Version))"

    # 检测 winget
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "包管理器: winget (可用)"
    } else {
        Write-Warn "winget 未安装（将使用直链下载方式）"
    }

    # 检测 Chocolatey
    $choco = Get-Command choco -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Info "包管理器: Chocolatey (可用)"
    }
}

# ---- 网络环境检测 ----

function Detect-Network {
    if ($UseCN) {
        $script:UseCNMirror = $true
        Write-Info "网络环境: 中国大陆镜像 (由参数指定)"
        return
    }
    if ($NoCN) {
        $script:UseCNMirror = $false
        Write-Info "网络环境: 国际网络 (由参数指定)"
        return
    }

    Write-Step "检测网络环境..."

    try {
        $googleTest = Invoke-WebRequest -Uri "https://www.google.com" -TimeoutSec 3 -ErrorAction SilentlyContinue
        $canAccessGoogle = ($googleTest -ne $null)
    } catch {
        $canAccessGoogle = $false
    }

    try {
        $npmMirrorTest = Invoke-WebRequest -Uri "https://registry.npmmirror.com" -TimeoutSec 3 -ErrorAction SilentlyContinue
        $canAccessNpmMirror = ($npmMirrorTest -ne $null)
    } catch {
        $canAccessNpmMirror = $false
    }

    if ($canAccessGoogle -and -not $canAccessNpmMirror) {
        $script:UseCNMirror = $false
        Write-OK "网络环境: 国际网络（可访问 Google）"
    } elseif ($canAccessNpmMirror) {
        $script:UseCNMirror = $true
        Write-OK "网络环境: 中国大陆（使用国内镜像加速）"
    } else {
        Write-Warn "无法确定网络环境，默认尝试国内镜像"
        $script:UseCNMirror = $true
    }
}

# ---- Node.js 检测 ----

function Check-Node {
    Write-Step "检测 Node.js..."

    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) {
        try {
            $nodeVersion = (node -v) -replace '^v', ''
            $majorVersion = [int]($nodeVersion.Split('.')[0])

            if ($majorVersion -ge 18) {
                $script:NodeOK = $true
                $script:NodeVersion = $nodeVersion
                Write-OK "Node.js 版本: v${nodeVersion} (符合要求 >= 18)"
            } else {
                $script:NodeOK = $false
                Write-Warn "Node.js 版本: v${nodeVersion} (需要 >= 18)"
                $script:NeedInstallNode = $true
            }
        } catch {
            $script:NodeOK = $false
            $script:NeedInstallNode = $true
            Write-Warn "Node.js 已安装但无法确定版本"
        }
    } else {
        $script:NodeOK = $false
        $script:NeedInstallNode = $true
        Write-Warn "Node.js 未安装"
    }

    # 检查 npm
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) {
        $npmVersion = npm -v
        Write-OK "npm 版本: v${npmVersion}"
    }
}

# ---- Node.js 安装 ----

function Install-Node {
    Write-Step "自动安装 Node.js..."

    # 优先使用 winget
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "通过 winget 安装 Node.js LTS..."
        Dry-Echo "winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements"
        if (-not $DryRun) {
            winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements
        }

        if (-not $DryRun) {
            # winget 安装后需要刷新 PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
        }
    }
    # 回退: Chocolatey
    elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Info "通过 Chocolatey 安装 Node.js LTS..."
        Dry-Echo "choco install nodejs-lts -y"
        if (-not $DryRun) {
            choco install nodejs-lts -y
        }
    }
    # 直链下载
    else {
        Write-Info "从 npmmirror 下载 Node.js 安装包..."
        $nodeUrl = if ($UseCNMirror) {
            "https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-x64.msi"
        } else {
            "https://nodejs.org/dist/v20.19.0/node-v20.19.0-x64.msi"
        }
        $installerPath = "$env:TEMP\node-install.msi"

        Dry-Echo "Invoke-WebRequest -Uri $nodeUrl -OutFile $installerPath"
        Dry-Echo "msiexec /i $installerPath /quiet /norestart"
        if (-not $DryRun) {
            Invoke-WebRequest -Uri $nodeUrl -OutFile $installerPath
            Start-Process msiexec -ArgumentList "/i `"$installerPath`" /quiet /norestart" -Wait
            Remove-Item $installerPath -Force

            # 刷新 PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
        }
    }

    if (-not $DryRun) {
        $node = Get-Command node -ErrorAction SilentlyContinue
        if ($node) {
            $script:NodeOK = $true
            $script:NodeVersion = (node -v) -replace '^v', ''
            Write-OK "Node.js 安装成功: v$($script:NodeVersion)"
        } else {
            Write-Error "Node.js 安装失败，请手动安装 Node.js >= 18"
            Write-Error "下载地址: https://nodejs.org/zh-cn/download/"
            exit 1
        }
    }
}

# ---- npm 镜像配置 ----

function Set-NpmMirror {
    Write-Step "配置 npm 镜像源..."

    if ($UseCNMirror) {
        Write-Info "设置 npm registry 为 https://registry.npmmirror.com"
        Dry-Echo "npm config set registry https://registry.npmmirror.com"
        Dry-Echo "npm config set disturl https://npmmirror.com/mirrors/node"
        if (-not $DryRun) {
            npm config set registry https://registry.npmmirror.com
            npm config set disturl https://npmmirror.com/mirrors/node
        }
        Write-OK "npm 镜像源已配置为 npmmirror"
    } else {
        Write-Info "使用 npm 官方源"
    }
}

# ---- 项目依赖安装 ----

function Install-ProjectDeps {
    Write-Step "安装项目依赖..."

    $packageJson = Join-Path $ScriptDir "package.json"
    if (Test-Path $packageJson) {
        Dry-Echo "cd $ScriptDir && npm install"
        if (-not $DryRun) {
            Push-Location $ScriptDir
            npm install --silent
            Pop-Location
        }
        Write-OK "项目依赖安装完成"
    } else {
        Write-Warn "未找到 package.json，跳过依赖安装"
    }
}

# ---- 启动主脚本 ----

function Invoke-MainScript {
    Write-Step "启动主安装脚本..."

    $mainScript = Join-Path $ScriptDir "install.js"
    if (-not (Test-Path $mainScript)) {
        Write-Error "未找到主脚本: $mainScript"
        Write-Error "请确认 install.js 文件存在"
        exit 1
    }

    Dry-Echo "node $mainScript"

    if (-not $DryRun) {
        $env:CC_INSTALL_USE_CN = if ($UseCNMirror) { "true" } else { "false" }
        node $mainScript
    }
}

# ---- 打印摘要 ----

function Write-Summary {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║       Claude Code 安装引导层 — 环境检测报告             ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""

    $os = Get-CimInstance Win32_OperatingSystem
    Write-Host "  操作系统:       $($os.Caption)"
    Write-Host "  Node.js 状态:   $(if ($NodeOK) { '✓ 已安装' } else { '✗ 需安装' })"
    if ($NodeOK) { Write-Host "  Node.js 版本:   v${NodeVersion}" }
    Write-Host "  国内镜像:       $(if ($UseCNMirror) { '是 (npmmirror.com)' } else { '否 (官方源)' })"
    Write-Host "  运行模式:       $(if ($DryRun) { 'DRY-RUN (仅检测)' } else { '正常安装' })"
    Write-Host "  脚本目录:       ${ScriptDir}"
    Write-Host ""

    if ($DryRun) {
        Write-Host "  DRY-RUN 模式: 以上为检测结果，未执行任何实际安装操作。" -ForegroundColor Yellow
        Write-Host "  移除 -DryRun 参数即可正常安装。" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ---- 主流程 ----

function Main {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║     Claude Code + DeepSeek 一键安装引导层                ║" -ForegroundColor Cyan
    Write-Host "║     Windows PowerShell Bootstrap                         ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""

    if ($DryRun) {
        Write-Info "运行模式: DRY-RUN（仅检测，不安装）"
    }

    Detect-OS
    Detect-Network
    Check-Node

    if ($NeedInstallNode) {
        Install-Node
        Check-Node
    }

    if ($DryRun) {
        Write-Summary
        Write-Host "✓ 引导层 dry-run 测试完成，环境检测一切正常。" -ForegroundColor Green
        Write-Host ""
        exit 0
    }

    if (-not $NodeOK) {
        Write-Error "Node.js 环境未就绪，请手动安装 Node.js >= 18 后重试"
        Write-Error "手动安装指引: https://nodejs.org/zh-cn/download/"
        exit 1
    }

    Set-NpmMirror
    Install-ProjectDeps
    Write-Summary
    Invoke-MainScript
}

# ---- 执行 ----
Main
