# Build the AISC CLI as a Tauri sidecar binary (Windows).
#
# Produces dist\<name>-<target-triple>.exe (Tauri externalBin convention;
# the .exe extension is handled by Tauri's bundler on Windows).
# Requires: python with PyInstaller (pip install -e ".[dev]" or uv).

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $MyInvocation.MyCommand.Path | Join-Path -ChildPath "..")

$TargetTriple = $env:TARGET_TRIPLE
if (-not $TargetTriple) {
    $Arch = $env:PROCESSOR_ARCHITECTURE
    if ($Arch -eq "ARM64") { $TargetTriple = "aarch64-pc-windows-msvc" }
    else { $TargetTriple = "x86_64-pc-windows-msvc" }
}

Write-Host "== building aisc sidecar ($TargetTriple) =="
python -m PyInstaller --noconfirm --clean packaging/aisc.spec

New-Item -ItemType Directory -Force -Path dist | Out-Null
Move-Item -Force dist\aisc.exe "dist\aisc-$TargetTriple.exe"
Write-Host "== artifact: dist\aisc-$TargetTriple.exe =="
& "dist\aisc-$TargetTriple.exe" version --format json | Select-Object -First 1

# v2.1.7 S5: sync the fresh sidecar to BOTH places that actually run it.
# workbench/src-tauri/binaries/ feeds tauri build/dev externalBin, and the
# dev Workbench's CLI pin resolves workbench/src-tauri/target/debug/aisc.exe.
# Leaving either stale cost a full debugging round on 2026-08-27 (the app
# ran a two-day-old sidecar and failed with a capability mismatch).
$Dst1 = "workbench\src-tauri\binaries\aisc-$TargetTriple.exe"
$Dst2 = "workbench\src-tauri\target\debug\aisc.exe"
New-Item -ItemType Directory -Force -Path (Split-Path $Dst1) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $Dst2) | Out-Null
Copy-Item -Force "dist\aisc-$TargetTriple.exe" $Dst1
Copy-Item -Force "dist\aisc-$TargetTriple.exe" $Dst2
Write-Host "== synced: $Dst1"
Write-Host "== synced: $Dst2"

# 2026-08-29 incident: the bundle chain is repo container/ → nsis/bundle/aisc-bundle/
# → (cargo build copies to) target/debug/aisc-bundle/ → (aisc build) → docker image.
# The nsis/ directory is the SOURCE that cargo re-copies on every tauri dev restart —
# leaving it stale means every dev restart reverts the debug bundle to old code.
# Sync BOTH the source (nsis) and the current copy (target/debug).
foreach ($Bundle in @(
    "workbench\src-tauri\nsis\bundle\aisc-bundle",
    "workbench\src-tauri\target\debug\aisc-bundle"
)) {
    if (Test-Path $Bundle) {
        foreach ($Dir in @("container", "config", "vendor")) {
            $DstDir = Join-Path $Bundle $Dir
            if (Test-Path $DstDir) { Remove-Item -Recurse -Force $DstDir }
            Copy-Item -Recurse -Force $Dir $DstDir
        }
        Copy-Item -Force VERSION (Join-Path $Bundle "VERSION")
        Write-Host "== synced: $Bundle"
    }
}
