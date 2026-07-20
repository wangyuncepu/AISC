# scripts/_state.ps1 — 启动器流水线状态文件助手（模块间解耦传参）
# 用法：. "$PSScriptRoot\_state.ps1"
#   Init-State                  建 .aisc 并清空 state.env（同时写入 .deploy 向后兼容）
#   Set-State -Key K -Val V     追加/更新
#   Get-State -Key K            输出值（无则空）
# 状态文件（新）：$ProjectRoot\.aisc\state.env  主位置
# 状态文件（旧）：$ProjectRoot\.deploy\state.env  向后兼容（已弃用）
#   只存简单值：IMAGE / PROXY_ENABLED / CONTAINER_NAME。路径由各模块从自身位置推导。
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$AiscHome = Join-Path $ProjectRoot '.aisc'
$Script:StateDir = $AiscHome
$Script:StateFile = Join-Path $Script:StateDir 'state.env'
$Script:LegacyStateDir = Join-Path $ProjectRoot '.deploy'
$Script:LegacyStateFile = Join-Path $Script:LegacyStateDir 'state.env'
$Script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Script:StateHeader = '# AISC launcher state — do not edit manually'

function Init-State {
    $header = "$Script:StateHeader`n`n"
    # New location
    New-Item -ItemType Directory -Force -Path $Script:StateDir | Out-Null
    [System.IO.File]::WriteAllText($Script:StateFile, $header, $Script:Utf8NoBom)
    # Legacy location (backward compat)
    New-Item -ItemType Directory -Force -Path $Script:LegacyStateDir | Out-Null
    [System.IO.File]::WriteAllText($Script:LegacyStateFile, $header, $Script:Utf8NoBom)
}

function Set-State {
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$Val)

    function _WriteOne {
        param([string]$File, [string]$Dir)
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        $lines = @()
        if (Test-Path $File) {
            $lines = @(Get-Content $File | Where-Object {
                $_ -ne '' -and -not $_.StartsWith('#') -and ($_ -split '=', 2)[0] -ne $Key
            })
        }
        $result = @($Script:StateHeader, '')
        $result += $lines
        $result += "$Key=$Val"
        [System.IO.File]::WriteAllText($File, ($result -join "`n") + "`n", $Script:Utf8NoBom)
    }

    _WriteOne -File $Script:StateFile -Dir $Script:StateDir
    _WriteOne -File $Script:LegacyStateFile -Dir $Script:LegacyStateDir
}

function Get-State {
    param([Parameter(Mandatory)][string]$Key)
    # Read from new location first
    if (Test-Path $Script:StateFile) {
        $line = Get-Content $Script:StateFile | Where-Object { ($_ -split '=', 2)[0] -eq $Key } | Select-Object -Last 1
        if ($line) { return (($line -split '=', 2)[1]).TrimEnd("`r") }
    }
    # Fall back to legacy location
    if (Test-Path $Script:LegacyStateFile) {
        $line = Get-Content $Script:LegacyStateFile | Where-Object { ($_ -split '=', 2)[0] -eq $Key } | Select-Object -Last 1
        if ($line) { return (($line -split '=', 2)[1]).TrimEnd("`r") }
    }
    return ''
}
