# AISC portable install — user-level installation without Python/uv
#
# Usage:
#   .\install.ps1 -Source "C:\path\to\AISC-2.0.0-dev-windows-x86_64.zip"
#   .\install.ps1 -Source "C:\path\to\extracted-archive\"
#
# Installs aisc.exe and aisc-bundle\ into %LOCALAPPDATA%\AISC
# and adds the install directory to the user PATH.
#
# Repeated installations atomically replace the previous installation.
# aisc.exe and aisc-bundle\ must remain adjacent after install.
#
# This script does NOT:
#   - Create, upload, or publish GitHub Releases
#   - Sign, notarise, or auto-update
#   - Modify Docker, Python, or user workspaces

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"

$ExeName = "aisc.exe"
$BundleDir = "aisc-bundle"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Write-Warn {
    param([string]$Message)
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Write-Die {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Resolve source path
# ---------------------------------------------------------------------------

try {
    $Source = [System.IO.Path]::GetFullPath($Source)
} catch {
    Write-Die "Invalid source path: $Source"
}

if (-not (Test-Path $Source)) {
    Write-Die "Source not found: $Source"
}

# ---------------------------------------------------------------------------
# Install paths
# ---------------------------------------------------------------------------

$InstallDir = Join-Path $env:LOCALAPPDATA "AISC"
$ExeDest = Join-Path $InstallDir $ExeName
$BundleDest = Join-Path $InstallDir $BundleDir

# ---------------------------------------------------------------------------
# Locate aisc.exe and aisc-bundle\ in source
# ---------------------------------------------------------------------------

function Find-InSource {
    param([string]$Src)

    $foundExe = $null
    $foundBundle = $null

    if (Test-Path $Src -PathType Container) {
        # Check direct layout
        $directExe = Join-Path $Src $ExeName
        $directBundle = Join-Path $Src $BundleDir
        if ((Test-Path $directExe -PathType Leaf) -and (Test-Path $directBundle -PathType Container)) {
            return @{ Exe = $directExe; Bundle = $directBundle; IsArchive = $false }
        }
        # Check one level down for AISC-*\ layout
        $innerDirs = Get-ChildItem $Src -Directory | Where-Object { $_.Name -like "AISC-*" }
        if ($innerDirs) {
            $innerDir = $innerDirs[0].FullName
            $innerExe = Join-Path $innerDir $ExeName
            $innerBundle = Join-Path $innerDir $BundleDir
            if ((Test-Path $innerExe -PathType Leaf) -and (Test-Path $innerBundle -PathType Container)) {
                return @{ Exe = $innerExe; Bundle = $innerBundle; IsArchive = $false }
            }
        }
        Write-Die "Cannot find $ExeName + $BundleDir\ in directory: $Src"
    }

    # Check if it's a .zip
    if ($Src -like "*.zip") {
        return @{ Exe = $null; Bundle = $null; IsArchive = $true; ArchivePath = $Src }
    }

    Write-Die "Source must be a directory or .zip archive: $Src"
}

# ---------------------------------------------------------------------------
# Verify bundle structure
# ---------------------------------------------------------------------------

function Verify-Bundle {
    param([string]$BundlePath)

    $required = @(
        "VERSION",
        "container\Dockerfile",
        "config\versions.env"
    )

    $errors = @()
    foreach ($f in $required) {
        $fp = Join-Path $BundlePath $f
        if (-not (Test-Path $fp -PathType Leaf)) {
            $errors += "Missing: aisc-bundle\$f"
        }
    }

    if ($errors.Count -gt 0) {
        foreach ($e in $errors) { Write-Warn $e }
        Write-Die "Bundle verification failed: $($errors.Count) missing required file(s)"
    }

    $verFile = Join-Path $BundlePath "VERSION"
    if (Test-Path $verFile) {
        $ver = (Get-Content $verFile -First 1).Trim()
        Write-Info "Bundle VERSION: $ver"
    }
}

# ---------------------------------------------------------------------------
# Check PATH and warn if install dir is not in PATH
# ---------------------------------------------------------------------------

function Test-PathInUserPath {
    param([string]$Dir)

    try {
        $regPath = "HKCU:\Environment"
        $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -ErrorAction SilentlyContinue).PATH
        if (-not $currentPath) { return $false }
        $entries = $currentPath -split ';' | ForEach-Object { $_.Trim().TrimEnd('\') }
        return ($entries -contains $Dir.TrimEnd('\'))
    } catch {
        return $false
    }
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

function Install-AISC {
    param(
        [string]$ExeSource,
        [string]$BundleSource
    )

    # Verify source executable exists
    if (-not (Test-Path $ExeSource -PathType Leaf)) {
        Write-Die "Source executable not found: $ExeSource"
    }

    # Verify bundle
    Verify-Bundle $BundleSource

    # Create install parent directory
    $parentDir = Split-Path $InstallDir -Parent
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }

    # Stage into temp directory for atomic install
    $stagingDir = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        "aisc-install-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    )
    New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null

    try {
        Write-Info "Staging files..."

        # Copy executable
        Copy-Item $ExeSource (Join-Path $stagingDir $ExeName) -Force

        # Copy bundle
        Copy-Item $BundleSource (Join-Path $stagingDir $BundleDir) -Recurse -Force

        # Verify staged install
        $stagedExe = Join-Path $stagingDir $ExeName
        if (-not (Test-Path $stagedExe)) { throw "Staged executable not found" }
        Verify-Bundle (Join-Path $stagingDir $BundleDir)

        # Remove previous installation
        if (Test-Path $InstallDir) {
            Write-Info "Removing previous installation at $InstallDir ..."
            Remove-Item $InstallDir -Recurse -Force -ErrorAction Stop
        }

        # Move staging to final location
        Move-Item $stagingDir $InstallDir -Force
        $stagingDir = $null  # prevent cleanup in finally
        Write-Info "Installed to: $InstallDir"

    } finally {
        if ($stagingDir -and (Test-Path $stagingDir)) {
            Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # Add to user PATH
    $alreadyInPath = Test-PathInUserPath $InstallDir

    if (-not $alreadyInPath) {
        Write-Info "Adding to user PATH: $InstallDir"

        try {
            $regPath = "HKCU:\Environment"
            $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -ErrorAction SilentlyContinue).PATH
            if ($currentPath) {
                $newPath = $currentPath.TrimEnd(';') + ";" + $InstallDir
            } else {
                $newPath = $InstallDir
            }
            Set-ItemProperty -Path $regPath -Name "PATH" -Value $newPath

            # Notify Explorer of environment change (broadcast)
            $HWND_BROADCAST = [IntPtr]0xffff
            $WM_SETTINGCHANGE = 0x001a
            $env = "Environment"
            try {
                # Use SendMessageTimeout via p/invoke
                $signature = @'
[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(
    IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam,
    uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
                Add-Type -MemberDefinition $signature -Name "WinUser" -Namespace "AISC" -ErrorAction SilentlyContinue
                $result = [UIntPtr]::Zero
                [AISC.WinUser]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE,
                    [UIntPtr]::Zero, $env, 2, 5000, [ref] $result) | Out-Null
            } catch {
                # Best-effort; PATH is set, user just needs to restart terminal
            }

            # Also update current session PATH
            $env:Path = $env:Path.TrimEnd(';') + ";" + $InstallDir

            Write-Info "PATH updated. Restart your terminal for the change to take full effect."
        } catch {
            Write-Warn "Failed to update user PATH: $_"
            Write-Warn "Please add the following to your PATH manually:"
            Write-Warn "  $InstallDir"
        }
    } else {
        Write-Info "Install directory already in user PATH (skipped)."
    }

    Write-Info ""
    Write-Info "========================================="
    Write-Info " AISC installed successfully!"
    Write-Info "========================================="
    Write-Info ""
    Write-Info "  Install directory: $InstallDir"
    Write-Info "  Executable:        $ExeDest"
    Write-Info "  Bundle:            $BundleDest"
    Write-Info ""
    if (-not $alreadyInPath) {
        Write-Info "  IMPORTANT: Restart your terminal for PATH changes to take effect."
        Write-Info ""
    }
    Write-Info "  Verify installation:"
    Write-Info "    aisc version"
    Write-Info ""
    Write-Info "  Uninstall:"
    Write-Info "    .\uninstall.ps1"
    Write-Info ""
}

# ---------------------------------------------------------------------------
# Handle zip archive source
# ---------------------------------------------------------------------------

function Install-FromArchive {
    param([string]$ArchivePath)

    $extractDir = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        "aisc-extract-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    )
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

    try {
        Write-Info "Extracting $ArchivePath ..."
        Expand-Archive -Path $ArchivePath -DestinationPath $extractDir -Force

        # Find inner directory
        $innerDirs = Get-ChildItem $extractDir -Directory | Where-Object { $_.Name -like "AISC-*" }
        if (-not $innerDirs) {
            Write-Die "No AISC-*\ top-level directory found in archive"
        }
        $innerDir = $innerDirs[0].FullName

        $exe = Join-Path $innerDir $ExeName
        $bundle = Join-Path $innerDir $BundleDir

        if (-not (Test-Path $exe -PathType Leaf)) {
            Write-Die "Executable not found after extraction: $exe"
        }
        if (-not (Test-Path $bundle -PathType Container)) {
            Write-Die "Bundle not found after extraction: $bundle"
        }

        Install-AISC -ExeSource $exe -BundleSource $bundle
    } finally {
        if (Test-Path $extractDir) {
            Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$found = Find-InSource $Source

if ($found.IsArchive) {
    Install-FromArchive $found.ArchivePath
} else {
    Install-AISC -ExeSource $found.Exe -BundleSource $found.Bundle
}

Write-Info "Source: $Source can now be safely deleted."
