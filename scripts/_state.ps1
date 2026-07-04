# scripts/_state.ps1 — 启动器流水线状态文件助手（模块间解耦传参）
# 用法：. "$PSScriptRoot\_state.ps1"
#   Init-State                  建 .deploy 并清空 state.env
#   Set-State -Key K -Val V     追加/更新
#   Get-State -Key K            输出值（无则空）
# 状态文件：$ProjectRoot\.deploy\state.env  (KEY=value, UTF-8 无 BOM, LF)
#   只存简单值：IMAGE / PROXY_ENABLED / CONTAINER_NAME。路径由各模块从自身位置推导。
$Script:StateDir = Join-Path (Split-Path $PSScriptRoot -Parent) '.deploy'
$Script:StateFile = Join-Path $Script:StateDir 'state.env'
$Script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Init-State {
    New-Item -ItemType Directory -Force -Path $Script:StateDir | Out-Null
    [System.IO.File]::WriteAllText($Script:StateFile, '', $Script:Utf8NoBom)
}

function Set-State {
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$Val)
    New-Item -ItemType Directory -Force -Path $Script:StateDir | Out-Null
    $lines = @()
    if (Test-Path $Script:StateFile) {
        $lines = @(Get-Content $Script:StateFile | Where-Object {
            $_ -ne '' -and ($_ -split '=', 2)[0] -ne $Key
        })
    }
    $lines += "$Key=$Val"
    [System.IO.File]::WriteAllText($Script:StateFile, ($lines -join "`n") + "`n", $Script:Utf8NoBom)
}

function Get-State {
    param([Parameter(Mandatory)][string]$Key)
    if (-not (Test-Path $Script:StateFile)) { return '' }
    $line = Get-Content $Script:StateFile | Where-Object { ($_ -split '=', 2)[0] -eq $Key } | Select-Object -Last 1
    if ($line) { return (($line -split '=', 2)[1]).TrimEnd("`r") }
    return ''
}
