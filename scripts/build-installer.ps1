# Build the AISC Workbench Windows installer (NSIS only, skips MSI).
#
#   online  (default): current lightweight setup — Docker installs via winget
#           at first-run onboarding.
#   offline: bundles the latest Docker Desktop installer (scripts/fetch-docker-
#           installer.ps1) into the setup exe; the Workbench installs Docker
#           from the local bundle with no network (like mihomo). The output is
#           suffixed `-offline-setup.exe`.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build-installer.ps1 -Mode online
#   powershell -ExecutionPolicy Bypass -File scripts/build-installer.ps1 -Mode offline -CopyToDownloads

param(
    [ValidateSet("online", "offline")]
    [string]$Mode = "online",
    [switch]$CopyToDownloads
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent
$Wb = Join-Path $Root "workbench"

if ($Mode -eq "offline") {
    Write-Host "== offline mode: fetching Docker Desktop installer =="
    & (Join-Path $Root "scripts\fetch-docker-installer.ps1")
    if ($LASTEXITCODE -ne 0) { throw "fetch-docker-installer failed (exit $LASTEXITCODE)" }
}

Push-Location $Wb
try {
    Write-Host "== tauri build (bundles=nsis, mode=$Mode) =="
    if ($Mode -eq "offline") {
        # --config resolves relative to the CWD (workbench/), hence src-tauri/ prefix.
        npm run tauri build -- --bundles nsis --config src-tauri/tauri.offline.conf.json
    } else {
        npm run tauri build -- --bundles nsis
    }
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$bundle = Join-Path $Wb "src-tauri\target\release\bundle\nsis"
$setup = Get-ChildItem -Path $bundle -Filter "*-setup.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "No *-setup.exe found under $bundle" }

if ($Mode -eq "offline") {
    $dest = $setup.FullName -replace "-setup\.exe$", "-offline-setup.exe"
    Copy-Item $setup.FullName $dest -Force
    Write-Host "== offline bundle: $dest =="
    $setup = Get-Item $dest
} else {
    Write-Host "== online bundle: $($setup.FullName) =="
}

if ($CopyToDownloads) {
    $dl = Join-Path $env:USERPROFILE "Downloads"
    Copy-Item $setup.FullName $dl -Force
    Write-Host "== copied to $dl\$($setup.Name) =="
}
