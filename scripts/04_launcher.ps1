# scripts/04_launcher.ps1 — 读 state → docker run（按需加 NET_ADMIN/tun/挂载）
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
. "$PSScriptRoot\_state.ps1"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Image = Get-State -Key 'IMAGE'; if (-not $Image) { $Image = 'super-claude:latest' }
$Name = Get-State -Key 'CONTAINER_NAME'; if (-not $Name) { $Name = "super-claude-station-$(Get-Random)" }
$Proxy = Get-State -Key 'PROXY_ENABLED'
$DoRun = Get-State -Key 'DO_RUN'; if (-not $DoRun) { $DoRun = '1' }

if ($DoRun -eq '0') {
    Write-Host 'ℹ️  DO_RUN=0，未启动容器。'
    exit 0
}

# 确定 workspace 挂载源：AISC_WORKSPACE env > pwd
$workspace = if ($env:AISC_WORKSPACE) { $env:AISC_WORKSPACE } else { $PWD }
if (-not (Test-Path $workspace -PathType Container)) {
    Write-Host "❌ Workspace directory does not exist: $workspace"
    exit 1
}

Write-Host '🚀 [4/4] 启动容器...'
Write-Host '💡 容器内：cs ark / cs deepseek / cs show 切换模型后端'
Write-Host "📂 Workspace: $workspace -> /home/AISC/app"
Write-Host ''

# 仅清理已退出的旧工作站容器（保留运行中的，支持多开并行）
docker ps -aq -f 'name=super-claude-station' -f 'status=exited' 2>$null | ForEach-Object { docker rm $_ 2>$null | Out-Null }

# 拼接 docker run 参数；启用代理时追加 NET_ADMIN + /dev/net/tun + 配置只读挂载
$runArgs = @('run', '-it', '--rm', '-e', 'TERM=xterm-256color', '--name', $Name, '-v', "${workspace}:/home/AISC/app")
if ($Proxy -eq '1') {
    Write-Host '🛡️  已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）'
    $runArgs += @('--cap-add=NET_ADMIN', '--device=/dev/net/tun', '-v', "$ProjectRoot\.claude\mihomo\config.yaml:/etc/mihomo/config.yaml:ro")
}
$runArgs += $Image
& docker @runArgs
