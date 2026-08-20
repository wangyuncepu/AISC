# local-gates.ps1 — 一键本地全门禁（2026-08-20 用户决策：能本地跑的全部本地跑，
# 远程 CI 只作环境差异兜底；安装包产物改为本地构建）。
#
# 覆盖 Workbench CI + CLI sidecar 两条远程 CI 的全部可本地检查项：
#   1. Python 全测（忽略 integration）
#   2. cargo test --lib
#   3. vitest run
#   4. vue-tsc --noEmit
# 并按改动面提示两条人工后续（sidecar 重建 / vendor 刷新）。
#
# 用法：powershell -File scripts\local-gates.ps1
# 全绿输出 LOCAL GATES: ALL GREEN；任一红即停（exit 1）。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($name, $script) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $script
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nLOCAL GATES: FAILED at [$name]" -ForegroundColor Red
        exit 1
    }
}

Step "python full tests" {
    python -m pytest tests/ -q --ignore=tests/integration
}

Step "cargo test --lib" {
    Set-Location "$root\workbench\src-tauri"
    cargo test --lib 2>&1 | Select-Object -Last 3
    Set-Location $root
}

Step "vitest run" {
    Set-Location "$root\workbench"
    npx vitest run 2>&1 | Select-Object -Last 4
    Set-Location $root
}

Step "vue-tsc --noEmit" {
    Set-Location "$root\workbench"
    npx vue-tsc --noEmit
    Set-Location $root
}

# --- 按改动面的提示（不阻断） -------------------------------------------
$changed = @()
try { $changed = git diff --name-only origin/develop...HEAD 2>$null } catch {}
if (-not $changed) { try { $changed = git status --short | ForEach-Object { $_.Substring(3) } } catch {} }

if ($changed -match "^src/aisc/") {
    Write-Host "`n[reminder] Python CLI 源已改：手测/发布前需重建 sidecar —" -ForegroundColor Yellow
    Write-Host "  powershell -File scripts\build-cli.ps1; 然后拷贝 dist\aisc-x86_64-pc-windows-msvc.exe" -ForegroundColor Yellow
    Write-Host "  到 workbench\src-tauri\binaries\ 与 target\debug\aisc.exe" -ForegroundColor Yellow
}
if ($changed -match "^container/") {
    Write-Host "`n[reminder] container/ 已改：必须刷新 vendor checksums —" -ForegroundColor Yellow
    Write-Host '  PATH="/tmp/py3shim:$PATH" bash tools/vendor-refresh.sh' -ForegroundColor Yellow
}

Write-Host "`nLOCAL GATES: ALL GREEN" -ForegroundColor Green
