# Create the KI-3 verification Hyper-V VM with NESTED VIRTUALIZATION exposed.
# Run from an ELEVATED PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-k3-hyperv-vm.ps1
#
# What it builds:
#   AISC-KI3-Win11: Gen2, 8GB fixed memory, 4 vCPU, 64GB dynamic VHDX,
#   vTPM + Secure Boot (Win11 requirements), DVD-boot from the local ISO,
#   and ExposeVirtualizationExtensions=true so WSL2/Docker Desktop can run
#   INSIDE the guest while host Docker (WSL2 backend) keeps working.

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$vmName = 'AISC-KI3-Win11'
$iso    = 'G:\ISO\Win\Win11_25H2_Chinese_Simplified_x64_v2.iso'
$vhdDir = 'C:\HyperV'

Import-Module Hyper-V

if (-not (Test-Path $iso)) { throw "ISO not found: $iso" }
if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) {
    throw "VM '$vmName' already exists - refusing to touch it. Delete it manually first if this is a rebuild."
}

$vhdPath = Join-Path $vhdDir "$vmName.vhdx"
if (-not (Test-Path $vhdDir)) { New-Item -ItemType Directory -Force $vhdDir | Out-Null }

$switchName = (Get-VMSwitch | Select-Object -First 1).Name
Write-Host "[1/9] Using switch: $switchName"

$null = New-VM -Name $vmName -Generation 2 `
    -MemoryStartupBytes ([int64]8GB) `
    -NewVHDPath $vhdPath -NewVHDSizeBytes ([int64]64GB) `
    -SwitchName $switchName
Write-Host '[2/9] VM created'

Set-VMMemory   -VMName $vmName -DynamicMemoryEnabled $false
Write-Host '[3/9] Fixed 8GB memory (dynamic off - WSL2 guests must not shrink)'

Set-VMProcessor -VMName $vmName -Count 4
Write-Host '[4/9] 4 vCPUs'

Set-VMKeyProtector     -VMName $vmName -NewLocalKeyProtector
$null = Add-VMKeyStorageDevice -VMName $vmName
Write-Host '[5/9] Virtual TPM added'

$dvd = Add-VMDvdDrive -VMName $vmName -Path $iso
Set-VMFirmware -VMName $vmName -FirstBootDevice $dvd
Write-Host '[6/9] ISO attached + DVD-first boot'

# THE reason this whole exercise exists: hand hardware VT-x down to the
# guest so nested WSL2 (Docker Desktop backend) can run inside it.
Set-VMProcessor -VMName $vmName -ExposeVirtualizationExtensions $true
Write-Host '[7/9] Nested virtualization EXPOSED'

Start-VM -Name $vmName
Write-Host '[8/9] VM started - connect via Hyper-V Manager to see Windows Setup'

$vm = Get-VM -Name $vmName
[pscustomobject]@{
    Name            = $vm.Name
    State           = $vm.State
    Generation      = $vm.Generation
    Processors      = $vm.ProcessorCount
    MemoryStartGB   = [math]::Round($vm.MemoryStartup / 1GB, 0)
    DynamicMemory   = $vm.DynamicMemoryEnabled
    NestedVirtOn    = (Get-VMProcessor -VMName $vmName).ExposeVirtualizationExtensions
    VhdGB           = [math]::Round((Get-VMHardDiskDrive -VMName $vmName | Get-VHD).Size / 1GB, 0)
} | Format-List
Write-Host '[9/9] Done - install Windows 11 in the connected console next.'
