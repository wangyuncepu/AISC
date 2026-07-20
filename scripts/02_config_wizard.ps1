# scripts/02_config_wizard.ps1 — 代理配置向导（TUI）→ .claude/mihomo/config.yaml + state(PROXY_ENABLED)
# 宿主只下载/拷贝用户原始配置；TUN 块由容器 entrypoint 注入。格式由容器内自动识别/转换。
# 代理为可选项：失败/跳过 → PROXY_ENABLED=0 回退直连（非阻断，匹配旧行为）。
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
. "$PSScriptRoot\_state.ps1"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$MihomoDir = Join-Path $ProjectRoot '.claude\mihomo'
$Cfg = Join-Path $MihomoDir 'config.yaml'

Write-Host '🌐 [2/4] 代理网络配置（容器内访问 Anthropic API 等国际网络）'
$pc = Read-Host '是否需要配置代理网络? [y/N]'
if ($pc -notmatch '^[yY]') {
    Write-Host '⏭️  跳过代理，容器直连网络。'
    Set-State -Key 'PROXY_ENABLED' -Val '0'
    exit 0
}

Write-Host '  1) 本地文件 — 输入本地配置文件绝对路径'
Write-Host '  2) 网络链接 — 输入订阅链接 / 配置直链 URL'
$mode = Read-Host '选择 [1/2，默认 2]'
if (-not $mode) { $mode = '2' }

New-Item -ItemType Directory -Force -Path $MihomoDir | Out-Null
$ok = $false
if ($mode -eq '1') {
    $src = Read-Host '本地配置文件绝对路径'
    if (-not (Test-Path $src)) {
        Write-Host "❌ 文件不存在: $src" -ForegroundColor Red
    } else {
        Copy-Item $src $Cfg -Force
        $ok = $true
    }
} else {
    $url = Read-Host '配置 URL'
    if (-not $url) {
        Write-Host '❌ URL 为空' -ForegroundColor Red
    } else {
        Write-Host '⬇️  下载配置...'
        & curl.exe -fsSL $url -o $Cfg 2>$null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Cfg) -or (Get-Item $Cfg).Length -eq 0) {
            Write-Host 'curl 失败，改用 PowerShell 重试...'
            try { Invoke-WebRequest -Uri $url -OutFile $Cfg -UseBasicParsing -ErrorAction Stop } catch {
                Write-Host "[错误] 下载失败: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
        if ((Test-Path $Cfg) -and (Get-Item $Cfg).Length -gt 0) { $ok = $true }
        else { Write-Host '❌ 下载失败或内容为空' -ForegroundColor Red }
    }
}

if ($ok) {
    Write-Host "✅ 代理配置已就绪: $Cfg（格式由容器内自动识别/转换）"
    Set-State -Key 'PROXY_ENABLED' -Val '1'
} else {
    Write-Host '⚠️  代理配置未完成，将以直连启动。' -ForegroundColor Yellow
    Set-State -Key 'PROXY_ENABLED' -Val '0'
}
exit 0
