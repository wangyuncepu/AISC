# AISC portable uninstall — removes the installed aisc.exe and bundle
#
# Usage:
#   .\uninstall.ps1
#
# Removes:
#   - The install directory (%LOCALAPPDATA%\AISC)
#   - The install directory from the user PATH
#
# Does NOT remove:
#   - User configuration (e.g. %USERPROFILE%\.aisc, %USERPROFILE%\.cc-config)
#   - Docker images or containers
#   - Workspace directories

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
    Write-Info "  - User configuration: %USERPROFILE%\.aisc, %USERPROFILE%\.cc-config"
    Write-Info "  - Docker images and containers (use 'docker' commands)"
    Write-Info "  - Workspace directories"
    Write-Info ""
    Write-Info "Restart your terminal for PATH changes to take effect."
} else {
    Write-Info "No AISC installation found — nothing to uninstall."
}
