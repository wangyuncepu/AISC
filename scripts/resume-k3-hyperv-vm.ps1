# Resume KI-3 VM creation from step 5 (vTPM onwards).
# IMPORTANT: open a BRAND NEW ELEVATED PowerShell first (a fresh session picks
# up the just-enabled Hyper-V module), then:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\resume-k3-hyperv-vm.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$vmName = 'AISC-KI3-Win11'
$iso    = 'G:\ISO\Win\Win11_25H2_Chinese_Simplified_x64_v2.iso'

Import-Module Hyper-V -Force

if (-not (Get-Command Add-VMKeyStorageDevice -ErrorAction SilentlyContinue)) {
    Write-Warning 'Add-VMKeyStorageDevice is STILL missing after a forced module import.'
    Write-Host 'Hyper-V module copies found on disk:'
    Get-Module Hyper-V -ListAvailable | Select-Object Name, Version, Path | Format-Table | Out-String | Write-Host
    throw 'Start a brand-new admin PowerShell window and run this script again there.'
}

$vm = Get-VM -Name $vmName -ErrorAction Stop

# Idempotency: skip whatever already succeeded in the interrupted run.
if (-not $vm.KeyProtector) {
    Set-VMKeyProtector -VMName $vmName -NewLocalKeyProtector
    Write-Host '[5/9] Key protector created'
} else { Write-Host '[5/9] Key protector already present' }

if (-not (Get-VMKeyStorageDevice -VMName $vmName -ErrorAction SilentlyContinue)) {
    $null = Add-VMKeyStorageDevice -VMName $vmName
    Write-Host '[5b]  Virtual TPM added'
} else { Write-Host '[5b]  Virtual TPM already present' }

if (-not (Get-VMDvdDrive -VMName $vmName -ErrorAction SilentlyContinue)) {
    $dvd = Add-VMDvdDrive -VMName $vmName -Path $iso
    Set-VMFirmware -VMName $vmName -FirstBootDevice $dvd
    Write-Host '[6/9] ISO attached + DVD-first boot'
} else { Write-Host '[6/9] DVD drive already present'; Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName) }

Set-VMProcessor -VMName $vmName -ExposeVirtualizationExtensions $true
Write-Host '[7/9] Nested virtualization EXPOSED'

if ($vm.State -ne 'Running') { Start-VM -Name $vmName }
Write-Host '[8/9] VM started - connect via Hyper-V Manager'

[pscustomobject]@{
    Name          = (Get-VM $vmName).Name
    State         = (Get-VM $vmName).State
    Processors    = (Get-VM $vmName).ProcessorCount
    DynamicMemory = (Get-VM $vmName).DynamicMemoryEnabled
    NestedVirtOn  = (Get-VMProcessor -VMName $vmName).ExposeVirtualizationExtensions
    TpmPresent    = [bool](Get-VMKeyStorageDevice -VMName $vmName -ErrorAction SilentlyContinue)
} | Format-List
Write-Host '[9/9] Done - install Windows 11 in the connected console next.'
