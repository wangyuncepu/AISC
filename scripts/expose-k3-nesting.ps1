# Final piece that has NO GUI checkbox: hand hardware VT-x to the guest.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V -Force

$vmName = 'AISC-KI3-Win11'
$null = Get-VM -Name $vmName -ErrorAction Stop   # fail fast if VM vanished

if ((Get-VMProcessor -VMName $vmName).ExposeVirtualizationExtensions) {
    Write-Host 'Nested virtualization already EXPOSED.'
} else {
    Set-VMProcessor -VMName $vmName -ExposeVirtualizationExtensions $true
    Write-Host ('NestedVirtOn = {0}' -f (Get-VMProcessor -VMName $vmName).ExposeVirtualizationExtensions)
}

Get-VM $vmName | Select-Object Name, State, ProcessorCount, Generation | Format-List
