# Push installer files from host into the KI-3 VM's PUBLIC desktop.
# V2: enables the Guest Service by PIPELINE (some Hyper-V module builds reject
#     the literal name string lookup) and shows what IS present if it fails.
#
# Run from an ELEVATED PowerShell while AISC-KI3-Win11 is RUNNING:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\push-files-to-k3-vm.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V

$vmName  = 'AISC-KI3-Win11'
$payloads = @(
    "C:\Users\VE111\Desktop\AISC Workbench_2.1.6-dev_x64-setup.exe",
    'C:\Users\VE111\Documents\AISC\release-staging\Docker Desktop Installer.exe',
    'C:\Users\VE111\Documents\AISC\release-staging\wsl_update_x64.msi'
)

if ((Get-VM $vmName).State -ne 'Running') { throw "VM '$vmName' is not running." }

Write-Host '[1/4] Integration services currently:'
Get-VMIntegrationService -VMName $vmName | Format-Table Name, Enabled, Status -AutoSize | Out-String | Write-Host

# Service names are LOCALE-LOCALIZED (zh-CN host shows 来宾服务接口), and the
# name string above only survives if this file is read as UTF-8-BOM. Belt and
# suspenders: also match the stable well-known GUID in the Id property
# (Guest Service Interface = 6C09BB55-D683-4DA0-8931-C9BF705F6480).
$guest = Get-VMIntegrationService -VMName $vmName |
    Where-Object { $_.Id -match '6C09BB55' -or $_.Name -match 'Guest|来宾' } |
    Select-Object -First 1
if (-not $guest) {
    Write-Warning "No Guest/Guest Service integration service found on this VM/build."
    Write-Host '      Fallback: share-based transfer. Skipping push - see chat.'
    return
}
if (-not $guest.Enabled) {
    $guest | Enable-VMIntegrationService
    Write-Host '[2/4] Guest service enabling...'
}
while ((Get-VMIntegrationService -VMName $vmName |
        Where-Object { $_.Name -match 'Guest|guest|来宾' }).Status -ne 'Ok') {
    Start-Sleep -Seconds 2
}
Write-Host '      Guest Service: Ok'

Write-Host '[3/4] Copying into C:\Users\Public\Desktop ...'
foreach ($p in $payloads) {
    if (-not (Test-Path $p)) { Write-Warning "skip (missing): $p"; continue }
    Copy-VMFile -VMName $vmName -SourcePath $p `
        -DestinationPath ("C:\Users\Public\Desktop\" + (Split-Path $p -Leaf)) -FileSource Host
    Write-Host ("      pushed: {0}" -f (Split-Path $p -Leaf))
}
Write-Host '[4/4] Done - check the VM desktop.'
