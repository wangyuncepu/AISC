# AISC portable uninstall — removes the installed aisc.exe and bundle
#
# Usage:
#   .\uninstall.ps1                     # also cleans AISC Docker resources
#   .\uninstall.ps1 -KeepDockerResources  # keep containers + image
#
# Removes:
#   - AISC Docker containers and the workstation image (via the bundled
#     CLI's centralized lifecycle service; default, needs Docker running)
#   - The install directory (%LOCALAPPDATA%\AISC)
#   - The install directory from the user PATH
#
# Does NOT remove:
#   - User configuration (e.g. %USERPROFILE%\.aisc, data root)
#   - Workspace directories
#   - Persistent project toolchains (host_bind dirs under the data root)

[CmdletBinding()]
param(
    [switch]$KeepDockerResources
)

$ErrorActionPreference = "Stop"

$ExeName = "aisc.exe"
$InstallDir = Join-Path $env:LOCALAPPDATA "AISC"

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Write-Warn {
    param([string]$Message)
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

$removedAny = $false

# ---------------------------------------------------------------------------
# 1. Remove from user PATH
# ---------------------------------------------------------------------------

try {
    $regPath = "HKCU:\Environment"
    $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -ErrorAction SilentlyContinue).PATH

    if ($currentPath) {
        $entries = $currentPath -split ';'
        $normalizedInstallDir = $InstallDir.TrimEnd('\')

        $newEntries = @()
        $foundInPath = $false
        foreach ($entry in $entries) {
            $trimmed = $entry.Trim()
            if ($trimmed.TrimEnd('\') -eq $normalizedInstallDir) {
                $foundInPath = $true
                Write-Info "Removing from PATH: $trimmed"
            } else {
                $newEntries += $entry
            }
        }

        if ($foundInPath) {
            $newPath = ($newEntries -join ';').TrimEnd(';')
            if ([string]::IsNullOrWhiteSpace($newPath)) {
                Remove-ItemProperty -Path $regPath -Name "PATH" -Force -ErrorAction Stop
            } else {
                Set-ItemProperty -Path $regPath -Name "PATH" -Value $newPath -ErrorAction Stop
            }
            $removedAny = $true

            # Also update current session PATH
            $env:Path = $newPath

            # Broadcast environment change
            try {
                $HWND_BROADCAST = [IntPtr]0xffff
                $WM_SETTINGCHANGE = 0x001a
                $signature = @'
[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(
    IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam,
    uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
                Add-Type -MemberDefinition $signature -Name "WinUser" -Namespace "AISC_Uninstall" -ErrorAction SilentlyContinue
                $result = [UIntPtr]::Zero
                [AISC_Uninstall.WinUser]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE,
                    [UIntPtr]::Zero, "Environment", 2, 5000, [ref] $result) | Out-Null
            } catch {
                # Best-effort
            }
        } else {
            Write-Info "Install directory was not in user PATH."
        }
    } else {
        Write-Info "No user PATH entry found."
    }
} catch {
    Write-Warn "Failed to update user PATH: $_"
}

# ---------------------------------------------------------------------------
# 1.5 Docker companion cleanup (docker-resource-lifecycle D)
#
# Default ON per 01 §4/§6 (pass -KeepDockerResources to keep). Runs the
# bundled CLI's centralized lifecycle service BEFORE the install dir is
# removed — the exe performing the cleanup must still exist. Best-effort:
# an unreachable engine or partial failures never block the uninstall.
# ---------------------------------------------------------------------------

if (-not $KeepDockerResources) {
    $aiscExe = Join-Path $InstallDir $ExeName
    if (Test-Path $aiscExe) {
        Write-Info "Cleaning AISC Docker resources (containers + image)..."
        & $aiscExe maintenance docker-cleanup --context uninstall --format json
        if ($LASTEXITCODE -eq 3) {
            Write-Warn "Docker unreachable — AISC containers/image kept."
        } elseif ($LASTEXITCODE -ne 0) {
            Write-Warn "Partial cleanup failures (exit $LASTEXITCODE) — see output above."
        } else {
            Write-Info "AISC Docker resources cleaned."
        }
    } else {
        Write-Info "aisc.exe not found — skipping Docker cleanup."
    }
} else {
    Write-Info "Keeping Docker resources (-KeepDockerResources)."
}

# ---------------------------------------------------------------------------
# 2. Remove install directory
# ---------------------------------------------------------------------------

if (Test-Path $InstallDir) {
    Write-Info "Removing install directory: $InstallDir"
    try {
        Remove-Item $InstallDir -Recurse -Force -ErrorAction Stop
        $removedAny = $true
    } catch {
        Write-Warn "Failed to remove install directory: $_"
    }
} else {
    Write-Info "Install directory not found: $InstallDir"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

Write-Info ""
if ($removedAny) {
    Write-Info "AISC has been uninstalled."
    Write-Info ""
    Write-Info "The following were NOT removed (preserve these manually if desired):"
    Write-Info "  - User configuration: %USERPROFILE%\.aisc and the data root"
    Write-Info "  - Workspace directories and persistent toolchains"
    Write-Info ""
    Write-Info "Restart your terminal for PATH changes to take effect."
} else {
    Write-Info "No AISC installation found — nothing to uninstall."
}
