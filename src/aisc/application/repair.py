"""Environment repair — automatic installation of missing dependencies.

Provides interactive installation for Docker and other dependencies when
aisc doctor detects missing components.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple

from aisc.adapters.system import ProcessRunner, RealProcessRunner
from aisc.domain.models import ProcessResult


def _run_install_command(
    runner: ProcessRunner,
    argv: list[str],
    timeout: float,
) -> ProcessResult:
    """Run installers on the terminal when the runner supports streaming."""
    run_streaming = getattr(runner, "run_streaming", None)
    if callable(run_streaming):
        return run_streaming(argv, timeout=timeout)
    return runner.run(argv, timeout=timeout)


def _find_brew_executable() -> Optional[str]:
    discovered = shutil.which("brew")
    if discovered:
        return discovered
    for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(candidate).is_file():
            return candidate
    return None


def detect_platform() -> Tuple[str, str]:
    """Detect OS platform and architecture.

    Returns:
        (platform, arch) where platform is 'linux', 'darwin', or 'windows'
        and arch is 'x86_64' or 'arm64'
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize platform name
    if system == "darwin":
        plat = "darwin"
    elif system == "linux":
        plat = "linux"
    elif system in ("windows", "cygwin", "msys"):
        plat = "windows"
    else:
        plat = "unknown"

    # Normalize architecture
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = "unknown"

    return plat, arch


def can_install_docker(runner: Optional[ProcessRunner] = None) -> Tuple[bool, str]:
    """Check if Docker can be automatically installed on this platform.

    Returns:
        (can_install, method) where method is the installation tool name
    """
    if runner is None:
        runner = RealProcessRunner()

    plat, _ = detect_platform()

    if plat == "linux":
        # Check for curl (needed for get.docker.com)
        if shutil.which("curl"):
            return True, "get.docker.com"
        return False, "curl not found"

    elif plat == "darwin":
        # Check for Homebrew
        if shutil.which("brew"):
            return True, "homebrew"
        return True, "homebrew-install-first"

    elif plat == "windows":
        # Check for winget
        if shutil.which("winget"):
            return True, "winget"
        return False, "winget not found"

    return False, "unsupported platform"


def get_docker_install_prompt(method: str) -> str:
    """Get user-facing prompt for Docker installation.

    Args:
        method: Installation method from can_install_docker()

    Returns:
        Prompt message explaining what will be done
    """
    if method == "get.docker.com":
        return """
Docker is not installed. AISC can automatically install it using the
official Docker installation script.

This will:
  • Download and run https://get.docker.com
  • Install Docker Engine and CLI tools
  • Add your user to the 'docker' group (requires sudo)
  • You may need to log out and log back in for group changes to take effect

Do you want to install Docker now?"""

    elif method == "homebrew":
        return """
Docker is not installed. AISC can automatically install Docker Desktop
using Homebrew.

This will:
  • Run: brew install --cask docker
  • Download and install Docker Desktop (~500MB)
  • Automatically start Docker Desktop
  • You may need to accept system permissions

Do you want to install Docker now?"""

    elif method == "homebrew-install-first":
        return """
Docker is not installed. AISC can install it via Homebrew, but Homebrew
is not currently installed.

This will:
  • First install Homebrew (the macOS package manager)
  • Then install Docker Desktop via: brew install --cask docker
  • You will see prompts for your password and admin approval

Do you want to proceed?"""

    elif method == "winget":
        return """
Docker is not installed. AISC can automatically install Docker Desktop
using Windows Package Manager (winget).

This will:
  • Run: winget install Docker.DockerDesktop --silent
  • Download and install Docker Desktop (~500MB)
  • Require administrator privileges (UAC prompt)
  • Require logging out and back in (or restarting) after installation

Do you want to install Docker now?"""

    return "Unknown installation method"


def install_docker_linux(runner: ProcessRunner) -> Tuple[bool, str]:
    """Install Docker on Linux using get.docker.com.

    Returns:
        (success, message)
    """
    print("Downloading Docker installation script...")

    # Download and run the official Docker install script
    result = _run_install_command(
        runner,
        ["sh", "-c", "curl -fsSL https://get.docker.com | sudo sh"],
        300.0,
    )

    if result.exit_code != 0:
        return False, f"Docker installation failed: {result.stderr or result.stdout}"

    print("Docker installed successfully!")
    print("\nConfiguring user permissions...")

    # Add user to docker group
    username = os.getenv("USER", os.getenv("USERNAME", ""))
    if username:
        perm_result = runner.run(
            ["sudo", "usermod", "-aG", "docker", username],
            timeout=10.0,
        )
        if perm_result.exit_code == 0:
            return True, f"""
Docker installed successfully!

IMPORTANT: You need to log out and log back in for group permissions to take effect.

After logging back in, run 'aisc doctor' to verify the installation.
"""
        else:
            return True, """
Docker installed, but failed to configure user permissions.
You may need to manually run: sudo usermod -aG docker $USER
Then log out and log back in.
"""

    return True, "Docker installed successfully!"


def install_docker_macos(runner: ProcessRunner, install_brew_first: bool) -> Tuple[bool, str]:
    """Install Docker on macOS using Homebrew.

    Args:
        install_brew_first: Whether to install Homebrew first

    Returns:
        (success, message)
    """
    if install_brew_first:
        print("Installing Homebrew first...")
        brew_result = _run_install_command(
            runner,
            [
                "/bin/bash", "-c",
                "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh | /bin/bash",
            ],
            300.0,
        )
        if brew_result.exit_code != 0:
            return False, "Failed to install Homebrew"
        print("Homebrew installed successfully!")

    brew_executable = _find_brew_executable()
    if not brew_executable:
        return False, "Homebrew installation completed, but brew was not found"

    brew_dir = os.path.dirname(brew_executable)
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if brew_dir not in path_entries:
        os.environ["PATH"] = os.pathsep.join([brew_dir, *path_entries])

    print("Installing Docker Desktop via Homebrew...")
    print("This may take several minutes to download (~500MB)...")

    result = _run_install_command(
        runner,
        [brew_executable, "install", "--cask", "docker"],
        600.0,
    )

    if result.exit_code != 0:
        return False, f"Docker installation failed: {result.stderr or result.stdout}"

    print("Docker Desktop installed successfully!")
    print("Starting Docker Desktop...")

    # Try to start Docker Desktop
    start_result = runner.run(
        ["open", "-a", "Docker"],
        timeout=10.0,
    )

    if start_result.exit_code == 0:
        return True, """
Docker Desktop installed and started successfully!

Docker Desktop is launching in the background. This may take a minute.
Please accept any system permission prompts and the Docker service agreement.

Run 'aisc doctor' in a minute to verify Docker is running.
"""
    else:
        return True, """
Docker Desktop installed, but failed to start automatically.
Please manually open Docker Desktop from your Applications folder.

After Docker Desktop is running, run 'aisc doctor' to verify.
"""


def install_docker_windows(runner: ProcessRunner) -> Tuple[bool, str]:
    """Install Docker on Windows using winget.

    Returns:
        (success, message)
    """
    print("Installing Docker Desktop via winget...")
    print("You will see a UAC (User Account Control) prompt - please accept it.")
    print("This may take several minutes to download (~500MB)...")

    result = _run_install_command(
        runner,
        [
            "winget", "install", "Docker.DockerDesktop",
            "--silent",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ],
        600.0,
    )

    if result.exit_code != 0:
        return False, f"Docker installation failed: {result.stderr or result.stdout}"

    return True, """
Docker Desktop installed successfully!

IMPORTANT: You need to log out and log back in (or restart your computer)
for the installation to complete.

After logging back in:
1. Start Docker Desktop from the Start menu
2. Accept the service agreement
3. Run 'aisc doctor' to verify the installation
"""


def install_docker_interactive(runner: Optional[ProcessRunner] = None) -> bool:
    """Interactively install Docker if missing.

    Returns:
        True if installation was successful (or user declined)
        False if installation failed
    """
    if runner is None:
        runner = RealProcessRunner()

    can_install, method = can_install_docker(runner)

    if not can_install:
        print(f"\nCannot automatically install Docker: {method}", file=sys.stderr)
        print("Please install Docker manually:", file=sys.stderr)
        print("  https://docs.docker.com/get-docker/", file=sys.stderr)
        return True  # Not a failure, just unsupported

    # Show installation prompt
    prompt = get_docker_install_prompt(method)
    print(prompt)

    try:
        response = input("\nProceed with installation? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nInstallation cancelled.")
        return True

    if response not in ("y", "yes"):
        print("Installation cancelled. You can install Docker manually:")
        print("  https://docs.docker.com/get-docker/")
        return True

    # Perform installation
    print("\nStarting Docker installation...")

    plat, _ = detect_platform()
    success = False
    message = ""

    try:
        if plat == "linux" and method == "get.docker.com":
            success, message = install_docker_linux(runner)
        elif plat == "darwin":
            install_brew = (method == "homebrew-install-first")
            success, message = install_docker_macos(runner, install_brew)
        elif plat == "windows" and method == "winget":
            success, message = install_docker_windows(runner)
        else:
            print(f"Unsupported platform/method: {plat}/{method}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"\nInstallation failed with error: {exc}", file=sys.stderr)
        return False

    # Show result
    print("\n" + "=" * 60)
    if success:
        print("✓ Installation completed")
        print(message)
    else:
        print("✗ Installation failed")
        print(message, file=sys.stderr)
    print("=" * 60)

    return success
