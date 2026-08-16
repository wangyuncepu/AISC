# Fetch the latest stable Docker Desktop installer (Windows x64) for the
# offline NSIS build. The online build does NOT need this.
#
# Output: workbench\src-tauri\docker-offline\Docker Desktop Installer.exe
#   (bundled by tauri.offline.conf.json into $INSTDIR\aisc-bundle\docker-offline\
#   and used by runtime.rs when Docker Desktop.exe is missing — like mihomo).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/fetch-docker-installer.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent
$OutDir = Join-Path $Root "workbench\src-tauri\docker-offline"
$OutFile = Join-Path $OutDir "Docker Desktop Installer.exe"
$Url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"

# Minimum plausible size for the Docker Desktop installer (~600 MB current);
# anything smaller means a proxy/error page or a partial download.
$MinSize = 150MB

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (Test-Path $OutFile) {
    $size = (Get-Item $OutFile).Length
    if ($size -gt $MinSize) {
        Write-Host "== reuse existing installer ($([math]::Round($size/1MB)) MB) =="
        exit 0
    }
    Write-Host "== existing file too small ($([math]::Round($size/1MB)) MB), re-downloading =="
    Remove-Item $OutFile -Force
}

Write-Host "== downloading Docker Desktop installer from desktop.docker.com =="
# Prefer BITS (resumable) when available, else Invoke-WebRequest.
Import-Module BitsTransfer -ErrorAction SilentlyContinue
if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
    Start-BitsTransfer -Source $Url -Destination $OutFile
} else {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
}

$size = (Get-Item $OutFile).Length
if ($size -lt $MinSize) {
    throw "Downloaded installer looks wrong: $([math]::Round($size/1MB)) MB (expected > $([math]::Round($MinSize/1MB)) MB)"
}
Write-Host "== artifact: $OutFile ($([math]::Round($size/1MB)) MB) =="
