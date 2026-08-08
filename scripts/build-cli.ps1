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
