# AISC Windows installer CI smoke test
# Usage: .\smoke_installer.ps1 -SetupPath <path-to-setup.exe>
# Performs: install → verify → upgrade → uninstall → cleanup
# Exits 1 on any failure.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$SetupPath
)

$ErrorActionPreference = "Stop"
$Script:ExitCode = 0

function Fail {
    param([string]$Msg)
    Write-Host "  FAIL: $Msg" -ForegroundColor Red
    $Script:ExitCode = 1
}
function Pass { param([string]$Msg) Write-Host "  PASS: $Msg" }

$appDir = "$env:LOCALAPPDATA\Programs\AISC"
$regPath = "HKCU:\Environment"
$sentinelConfig = "$env:USERPROFILE\.aisc\smoke-marker.txt"
$sentinelCC = "$env:USERPROFILE\.cc-config\smoke-marker.txt"
$sentinelPathEntry = "C:\aisc-smoke-sentinel-path"
$setupFile = Get-Item $SetupPath -ErrorAction Stop
$cleanupMarkers = $false

# ---------------------------------------------------------------
# Cleanup helper — best-effort removal of test artifacts
# ---------------------------------------------------------------
function Invoke-Cleanup {
    # Remove markers we created
    if ($cleanupMarkers) {
        Remove-Item $sentinelConfig -Force -ErrorAction SilentlyContinue
        Remove-Item $sentinelCC -Force -ErrorAction SilentlyContinue
        # Remove empty dirs if we created them (only if they existed before we ran)
        $configDir = Split-Path $sentinelConfig
        if ((Test-Path $configDir) -and -not (Get-ChildItem $configDir -ErrorAction SilentlyContinue)) {
            Remove-Item $configDir -Force -ErrorAction SilentlyContinue
        }
        $ccDir = Split-Path $sentinelCC
        if ((Test-Path $ccDir) -and -not (Get-ChildItem $ccDir -ErrorAction SilentlyContinue)) {
            Remove-Item $ccDir -Force -ErrorAction SilentlyContinue
        }
    }
    # Remove sentinel PATH entry
    try {
        $cp = (Get-ItemProperty -Path $regPath -Name "PATH" -ErrorAction SilentlyContinue).PATH
        if ($cp) {
            $entries = $cp -split ';' | Where-Object { $_.Trim().TrimEnd('\') -ne $sentinelPathEntry }
            $newPath = ($entries -join ';').TrimEnd(';')
            if ([string]::IsNullOrWhiteSpace($newPath)) {
                Remove-ItemProperty -Path $regPath -Name "PATH" -Force -ErrorAction SilentlyContinue
            } else {
                Set-ItemProperty -Path $regPath -Name "PATH" -Value $newPath
            }
        }
    } catch { Write-Host "  cleanup: sentinel PATH removal failed: $_" }
}

try {
    # ---------------------------------------------------------------
    # 1. Silent install
    # ---------------------------------------------------------------
    Write-Host "=== 1. Silent install ==="
    $log1 = "$env:TEMP\aisc-install-1.log"
    & $setupFile.FullName /VERYSILENT /SUPPRESSMSGBOXES /LOG="$log1"
    if ($LASTEXITCODE -ne 0) {
        Fail "Install failed (exit $LASTEXITCODE)"
        if (Test-Path $log1) { Write-Host (Get-Content $log1 -Raw) }
        exit 1
    }

    if (-not (Test-Path $appDir)) { Fail "App dir not created"; exit 1 }
    Pass "App dir created"

    # Layout checks
    $checks = @{
        "executable" = "aisc.exe"
        "bundle VERSION" = "aisc-bundle\VERSION"
        "container/Dockerfile" = "aisc-bundle\container\Dockerfile"
        "config/versions.env" = "aisc-bundle\config\versions.env"
    }
    foreach ($desc in $checks.Keys) {
        if (Test-Path (Join-Path $appDir $checks[$desc])) {
            Pass $desc
        } else {
            Fail "$desc missing"
        }
    }

    # Run aisc commands
    $aisc = Join-Path $appDir "aisc.exe"
    Write-Host "--- aisc version ---"
    & $aisc version 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) { Fail "aisc version failed" }

    Write-Host "--- aisc provider list --format json ---"
    $provJson = & $aisc provider list --format json 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Fail "aisc provider list failed" }
    try { $provObj = $provJson | ConvertFrom-Json; Pass "provider JSON valid ($($provObj.data.providers.Count) providers)" }
    catch { Fail "provider JSON parse failed: $_" }

    Write-Host "--- aisc build --dry-run ---"
    & $aisc build --dry-run 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) { Fail "aisc build --dry-run failed" }

    # Verify HKCU uninstall entry
    $uninstallParent = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    $found = Get-ChildItem $uninstallParent -ErrorAction SilentlyContinue |
             Where-Object { try { (Get-ItemProperty $_.PSPath -Name DisplayName -EA SilentlyContinue).DisplayName -like "*AISC*" } catch { $false } }
    if ($found) { Pass "HKCU uninstall entry" } else { Fail "HKCU uninstall entry missing" }

    # Verify PATH
    $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -EA SilentlyContinue).PATH
    $normDir = $appDir.TrimEnd('\')
    $inPath = if ($currentPath) {
        ($currentPath -split ';' | ForEach-Object { $_.Trim().TrimEnd('\') } | Where-Object { $_ -eq $normDir }).Count
    } else { 0 }
    if ($inPath -eq 1) { Pass "PATH entry (count=1)" } else { Fail "PATH entry count=$inPath (expected 1)" }

    # ---------------------------------------------------------------
    # 2. Upgrade (second install — PATH dedup)
    # ---------------------------------------------------------------
    Write-Host "=== 2. Upgrade (second install) ==="
    $log2 = "$env:TEMP\aisc-install-2.log"
    & $setupFile.FullName /VERYSILENT /SUPPRESSMSGBOXES /LOG="$log2"
    if ($LASTEXITCODE -ne 0) { Fail "Upgrade install failed" }

    $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -EA SilentlyContinue).PATH
    $inPath = if ($currentPath) {
        ($currentPath -split ';' | ForEach-Object { $_.Trim().TrimEnd('\') } | Where-Object { $_ -eq $normDir }).Count
    } else { 0 }
    if ($inPath -eq 1) { Pass "PATH dedup: count=1" } else { Fail "PATH dedup: count=$inPath" }

    # ---------------------------------------------------------------
    # 3. Create user config markers + PATH sentinel
    # ---------------------------------------------------------------
    Write-Host "=== 3. Setup uninstall preconditions ==="
    New-Item -ItemType Directory -Force -Path (Split-Path $sentinelConfig) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $sentinelCC) | Out-Null
    "keep" | Out-File $sentinelConfig -Encoding ascii
    "keep" | Out-File $sentinelCC -Encoding ascii
    $cleanupMarkers = $true

    $cp = (Get-ItemProperty -Path $regPath -Name "PATH" -EA SilentlyContinue).PATH
    if ($cp) { Set-ItemProperty -Path $regPath -Name "PATH" -Value ($cp.TrimEnd(';') + ";" + $sentinelPathEntry) }
    else { Set-ItemProperty -Path $regPath -Name "PATH" -Value $sentinelPathEntry }

    # ---------------------------------------------------------------
    # 4. Uninstall
    # ---------------------------------------------------------------
    Write-Host "=== 4. Uninstall ==="
    $uninstFile = Get-ChildItem "$appDir\unins*.exe" -ErrorAction Stop | Select-Object -First 1
    if (-not $uninstFile) { Fail "unins*.exe not found — cannot uninstall"; exit 1 }

    & $uninstFile.FullName /VERYSILENT /SUPPRESSMSGBOXES
    if ($LASTEXITCODE -ne 0) { Fail "Uninstall failed (exit $LASTEXITCODE)" }
    Start-Sleep -Seconds 2

    # Verify app dir gone
    if (Test-Path $appDir) { Fail "App dir still exists" } else { Pass "App dir removed" }

    # Verify PATH: app entry gone, sentinel preserved
    $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -EA SilentlyContinue).PATH
    $appInPath = if ($currentPath) { ($currentPath -split ';' | % { $_.Trim().TrimEnd('\') } | ? { $_ -eq $normDir }).Count } else { 0 }
    $sentinelInPath = if ($currentPath) { ($currentPath -split ';' | % { $_.Trim().TrimEnd('\') } | ? { $_ -eq $sentinelPathEntry }).Count } else { 0 }
    if ($appInPath -eq 0) { Pass "App PATH entry removed" } else { Fail "App PATH entry still present" }
    if ($sentinelInPath -eq 1) { Pass "Sentinel PATH preserved" } else { Fail "Sentinel PATH missing" }

    # Verify config preserved
    if (Test-Path $sentinelConfig) { Pass "~\.aisc preserved" } else { Fail "~\.aisc removed" }
    if (Test-Path $sentinelCC) { Pass "~\.cc-config preserved" } else { Fail "~\.cc-config removed" }

} finally {
    Invoke-Cleanup
}

Write-Host "=== Smoke result: $($Script:ExitCode -eq 0 ? 'PASSED' : 'FAILED') ==="
exit $Script:ExitCode
