# scripts/run.ps1 — Super Claude AI 工作站流水线编排
# 按序调用 01_check_env → 02_config_wizard → 03_build_image → 04_launcher
# 模块间用 .deploy/state.env (KEY=value) 解耦传参。任一模块非零退出即中止。
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ScriptDir = $PSScriptRoot
. "$ScriptDir\_state.ps1"

Write-Host ''
Write-Host '🚀 Super Claude AI 工作站'
Write-Host '   cs 一键切换 · 插件/技能内置 · 容器内 TUN 代理'
Write-Host ''

# 初始化状态（每次运行重生成）
Init-State
Set-State -Key 'CONTAINER_NAME' -Val "super-claude-station-$(Get-Random)"
Set-State -Key 'IMAGE'          -Val 'super-claude:latest'
Set-State -Key 'DO_RUN'         -Val '1'
Set-State -Key 'PROXY_ENABLED'  -Val '0'

# 流水线（各模块独立子进程，互不污染；状态经文件传递）
& powershell -NoProfile -File "$ScriptDir\01_check_env.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host '❌ 环境检测未通过，已中止。' -ForegroundColor Red; exit 1 }
& powershell -NoProfile -File "$ScriptDir\02_config_wizard.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host '❌ 配置向导未通过，已中止。' -ForegroundColor Red; exit 1 }
& powershell -NoProfile -File "$ScriptDir\03_build_image.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host '❌ 镜像构建未通过，已中止。' -ForegroundColor Red; exit 1 }
& powershell -NoProfile -File "$ScriptDir\04_launcher.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host '❌ 启动失败，已中止。' -ForegroundColor Red; exit 1 }
