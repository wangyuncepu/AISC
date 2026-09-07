# Push the v2.1.7 unified-retest installer into the KI-3 VM's PUBLIC desktop.
# (Variant of push-files-to-k3-vm.ps1: payload resolved by glob so the exact
#  CI artifact filename does not need to be hardcoded.)
#
# Run from an ELEVATED PowerShell while AISC-KI3-Win11 is RUNNING:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\push-v217-to-k3-vm.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V

$vmName  = 'AISC-KI3-Win11'
$staging = 'C:\Users\VE111\Documents\AISC\release-staging\v217-vm-round'

# The artifact zip extracts to a nested dir; find the NSIS setup exe anywhere
# under the staging root.
$setup = Get-ChildItem -Path $staging -Recurse -Filter '*-setup.exe' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "No *-setup.exe found under $staging" }
Write-Host ("Payload: {0} ({1:N0} bytes)" -f $setup.FullName, $setup.Length)

if ((Get-VM $vmName).State -ne 'Running') { throw "VM '$vmName' is not running." }

Write-Host '[1/3] Guest service interface:'
$guest = Get-VMIntegrationService -VMName $vmName |
    Where-Object { $_.Id -match '6C09BB55' -or $_.Name -match 'Guest|来宾' } |
    Select-Object -First 1
if (-not $guest) { throw 'No Guest Service integration service found on this VM.' }
if (-not $guest.Enabled) { $guest | Enable-VMIntegrationService; Start-Sleep -Seconds 3 }
while ((Get-VMIntegrationService -VMName $vmName |
        Where-Object { $_.Name -match 'Guest|guest|来宾' }).Status -ne 'Ok') {
    Start-Sleep -Seconds 2
}
Write-Host '      Guest Service: Ok'

Write-Host '[2/3] Copying into C:\Users\Public\Desktop ...'
Copy-VMFile -VMName $vmName -SourcePath $setup.FullName `
    -DestinationPath ("C:\Users\Public\Desktop\" + $setup.Name) -FileSource Host
Write-Host ("      pushed: {0}" -f $setup.Name)
Write-Host '[3/3] Done - check the VM desktop.'
