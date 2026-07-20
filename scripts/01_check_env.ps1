# scripts/01_check_env.ps1 — 环境检测：docker 已安装且 daemon 运行中
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host '🔍 [1/4] 环境检测...'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '❌ 未检测到 docker。请先安装 Docker：https://www.docker.com/' -ForegroundColor Red
    exit 1
}

docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '❌ Docker daemon 未运行。请启动 Docker Desktop。' -ForegroundColor Red
    exit 1
}

Write-Host '✅ Docker 已就绪。'
exit 0
