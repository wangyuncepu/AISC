"""Doctor checks — host-only diagnosis.

Each check is a simple callable that returns a ``CheckResult``.
Checks are ordered and the report determines the final exit code.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Callable, List, Optional

from aisc.domain.models import CheckResult, CheckStatus, DoctorReport
from aisc.adapters.system import ProcessRunner, RealProcessRunner


# ---------------------------------------------------------------------------
# Timeout constants (seconds)
# ---------------------------------------------------------------------------

DOCKER_TIMEOUT = 8.0
GIT_TIMEOUT = 5.0
COMPOSE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_docker_cli(
    docker_path: str,
    runner: ProcessRunner,
) -> CheckResult:
    """Check 1: Docker CLI discovery / version."""
    result = runner.run([docker_path, "--version"], timeout=DOCKER_TIMEOUT)
    if result.command_not_found:
        return CheckResult(
            name="docker-cli",
            status=CheckStatus.FAIL,
            message="Docker CLI not found",
            detail="docker command not available on PATH",
            hint="Install Docker: https://docs.docker.com/get-docker/",
        )
    if result.timed_out:
        return CheckResult(
            name="docker-cli",
            status=CheckStatus.FAIL,
            message="Docker CLI timed out",
            detail="docker --version did not respond",
        )
    if result.exit_code != 0:
        return CheckResult(
            name="docker-cli",
            status=CheckStatus.FAIL,
            message="Docker CLI returned an error",
            detail=result.stderr.strip() or result.stdout.strip(),
        )
    version_line = (
        result.stdout.strip().splitlines()[0]
        if result.stdout.strip()
        else "(unknown)"
    )
    return CheckResult(
        name="docker-cli",
        status=CheckStatus.PASS,
        message=version_line,
    )


def _check_docker_daemon(
    docker_path: str,
    runner: ProcessRunner,
    docker_cli_available: bool,
) -> CheckResult:
    """Check 2: Docker daemon (``docker info``)."""
    if not docker_cli_available:
        return CheckResult(
            name="docker-daemon",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    result = runner.run([docker_path, "info"], timeout=DOCKER_TIMEOUT)
    if result.timed_out:
        return CheckResult(
            name="docker-daemon",
            status=CheckStatus.FAIL,
            message="Docker daemon check timed out",
            hint="Ensure the Docker daemon is running",
        )
    if result.exit_code != 0:
        return CheckResult(
            name="docker-daemon",
            status=CheckStatus.FAIL,
            message="Docker daemon not running or unreachable",
            detail=result.stderr.strip() or result.stdout.strip(),
            hint="Ensure the Docker daemon is running",
        )
    return CheckResult(
        name="docker-daemon",
        status=CheckStatus.PASS,
        message="Docker daemon is running",
    )


def _check_docker_permission(
    docker_path: str,
    runner: ProcessRunner,
    docker_cli_available: bool,
    docker_daemon_failed: bool,
) -> CheckResult:
    """Check 3: Docker permission (``docker ps``)."""
    if not docker_cli_available:
        return CheckResult(
            name="docker-permission",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    if docker_daemon_failed:
        return CheckResult(
            name="docker-permission",
            status=CheckStatus.SKIP,
            message="Docker daemon not available",
        )
    result = runner.run([docker_path, "ps"], timeout=DOCKER_TIMEOUT)
    if result.timed_out:
        return CheckResult(
            name="docker-permission",
            status=CheckStatus.FAIL,
            message="Docker permission check timed out",
        )
    if result.exit_code != 0:
        return CheckResult(
            name="docker-permission",
            status=CheckStatus.FAIL,
            message="Permission denied — cannot access Docker daemon",
            detail=result.stderr.strip() or result.stdout.strip(),
            hint="Ensure your user has access to Docker (e.g. docker group membership)",
        )
    return CheckResult(
        name="docker-permission",
        status=CheckStatus.PASS,
        message="Docker permission OK",
    )


def _check_docker_buildx(
    docker_path: str,
    runner: ProcessRunner,
    docker_cli_available: bool,
    docker_daemon_failed: bool,
) -> CheckResult:
    """Check 4: Docker Buildx (``docker buildx version``)."""
    if not docker_cli_available:
        return CheckResult(
            name="docker-buildx",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    if docker_daemon_failed:
        return CheckResult(
            name="docker-buildx",
            status=CheckStatus.SKIP,
            message="Docker daemon not available",
        )
    result = runner.run([docker_path, "buildx", "version"], timeout=DOCKER_TIMEOUT)
    if result.timed_out:
        return CheckResult(
            name="docker-buildx",
            status=CheckStatus.WARN,
            message="Docker Buildx check timed out",
        )
    if result.exit_code != 0:
        return CheckResult(
            name="docker-buildx",
            status=CheckStatus.WARN,
            message="Docker Buildx not available",
            detail=result.stderr.strip() or result.stdout.strip(),
            hint="Install buildx: https://docs.docker.com/buildx/",
        )
    version_line = (
        result.stdout.strip().splitlines()[0]
        if result.stdout.strip()
        else "(unknown)"
    )
    return CheckResult(
        name="docker-buildx",
        status=CheckStatus.PASS,
        message=version_line,
    )


def _check_tun_device() -> CheckResult:
    """Check 5: Linux ``/dev/net/tun`` (character device)."""
    if sys.platform != "linux":
        return CheckResult(
            name="tun-device",
            status=CheckStatus.SKIP,
            message="Not Linux — /dev/net/tun check skipped",
        )
    tun = Path("/dev/net/tun")
    try:
        st = tun.stat()
        if stat.S_ISCHR(st.st_mode):
            return CheckResult(
                name="tun-device",
                status=CheckStatus.PASS,
                message="/dev/net/tun exists and is a character device",
            )
        return CheckResult(
            name="tun-device",
            status=CheckStatus.WARN,
            message="/dev/net/tun exists but is not a character device",
        )
    except FileNotFoundError:
        return CheckResult(
            name="tun-device",
            status=CheckStatus.WARN,
            message="/dev/net/tun not found",
            detail="TUN device required for transparent proxy mode",
        )
    except OSError:
        return CheckResult(
            name="tun-device",
            status=CheckStatus.WARN,
            message="/dev/net/tun inaccessible",
        )


def _check_aisc_root(
    root: Optional[Path],
    root_error: Optional[str] = None,
) -> CheckResult:
    """Check 6: AISC root / bundle discovery.

    *root_error* is the original error message when an explicit or env
    source was invalid.  Passed through verbatim.
    """
    if root_error is not None:
        return CheckResult(
            name="aisc-root",
            status=CheckStatus.FAIL,
            message=root_error,
        )
    if root is not None:
        return CheckResult(
            name="aisc-root",
            status=CheckStatus.PASS,
            message=f"Found at {root}",
        )
    return CheckResult(
        name="aisc-root",
        status=CheckStatus.WARN,
        message="AISC root not found (no repo in parent directories)",
        detail="Some checks require a repo root to read VERSION / container files",
    )


def _check_root_files(root: Optional[Path]) -> List[CheckResult]:
    """Check 7: Verify key root files exist."""
    if root is None:
        return [
            CheckResult(
                name="aisc-root-files",
                status=CheckStatus.SKIP,
                message="No AISC root found — file checks skipped",
            )
        ]

    required = {
        "VERSION": "VERSION",
        "container/Dockerfile": "container/Dockerfile",
        "config/versions.env": "config/versions.env",
    }
    results: List[CheckResult] = []
    for label, rel in required.items():
        p = root / rel
        if p.is_file():
            results.append(
                CheckResult(
                    name=f"root-file:{label}",
                    status=CheckStatus.PASS,
                    message=f"{rel} exists",
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"root-file:{label}",
                    status=CheckStatus.FAIL,
                    message=f"{rel} not found",
                )
            )
    return results


def _check_git(
    git_path: str,
    runner: ProcessRunner,
) -> CheckResult:
    """Check 8: Git discovery / version."""
    result = runner.run([git_path, "--version"], timeout=GIT_TIMEOUT)
    if result.command_not_found or result.exit_code != 0:
        return CheckResult(
            name="git",
            status=CheckStatus.WARN,
            message="Git not available",
        )
    version_line = (
        result.stdout.strip().splitlines()[0]
        if result.stdout.strip()
        else "(unknown)"
    )
    return CheckResult(
        name="git",
        status=CheckStatus.PASS,
        message=version_line,
    )


def _check_docker_compose(
    docker_path: Optional[str],
    runner: ProcessRunner,
    docker_cli_available: bool,
) -> CheckResult:
    """Check 9: Docker Compose (``docker compose version``)."""
    if not docker_cli_available or docker_path is None:
        return CheckResult(
            name="docker-compose",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    result = runner.run(
        [docker_path, "compose", "version"], timeout=COMPOSE_TIMEOUT,
    )
    if result.command_not_found:
        return CheckResult(
            name="docker-compose",
            status=CheckStatus.WARN,
            message="Docker Compose subcommand not available",
            detail="docker command exists but 'compose' subcommand not found",
            hint="Ensure Docker Compose plugin is installed: https://docs.docker.com/compose/install/",
        )
    if result.timed_out:
        return CheckResult(
            name="docker-compose",
            status=CheckStatus.WARN,
            message="Docker Compose check timed out",
        )
    if result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        lowered = detail.lower()
        if "unknown command" in lowered or "not a docker command" in lowered:
            return CheckResult(
                name="docker-compose",
                status=CheckStatus.WARN,
                message="Docker Compose subcommand not available",
                detail=detail,
                hint="Install the Docker Compose plugin: https://docs.docker.com/compose/install/",
            )
        return CheckResult(
            name="docker-compose",
            status=CheckStatus.WARN,
            message="Docker Compose returned an error",
            detail=detail,
            hint="Run 'docker compose version' manually and check the Docker Compose plugin installation.",
        )
    version_line = (
        result.stdout.strip().splitlines()[0]
        if result.stdout.strip()
        else "(unknown)"
    )
    return CheckResult(
        name="docker-compose",
        status=CheckStatus.PASS,
        message=version_line,
    )


def _check_root_writable(root: Optional[Path]) -> CheckResult:
    """Check 10: Project root directory writability (read-only diagnostic)."""
    if root is None:
        return CheckResult(
            name="root-writable",
            status=CheckStatus.SKIP,
            message="No AISC root found — writability check skipped",
        )
    try:
        if not root.exists():
            return CheckResult(
                name="root-writable",
                status=CheckStatus.WARN,
                message=f"Root directory does not exist: {root}",
                hint="Verify the project root path is correct",
            )
        if not root.is_dir():
            return CheckResult(
                name="root-writable",
                status=CheckStatus.WARN,
                message=f"Root path is not a directory: {root}",
                hint="The project root must be a directory",
            )
        if os.access(str(root), os.W_OK):
            return CheckResult(
                name="root-writable",
                status=CheckStatus.PASS,
                message=f"Root directory is writable: {root}",
            )
        else:
            return CheckResult(
                name="root-writable",
                status=CheckStatus.WARN,
                message=f"Root directory may not be writable: {root}",
                detail="Permission pre-check only — not a write guarantee",
                hint="Check directory permissions (e.g. ls -ld on the directory)",
            )
    except OSError as exc:
        return CheckResult(
            name="root-writable",
            status=CheckStatus.WARN,
            message=f"Cannot check root writability: {root}",
            detail=str(exc),
        )


def _check_launcher(root: Optional[Path]) -> List[CheckResult]:
    """Check 11: Launcher script executability (start.sh, start.command on macOS)."""
    if sys.platform == "win32":
        return [
            CheckResult(
                name="launcher",
                status=CheckStatus.SKIP,
                message="Windows — POSIX executable-bit checks skipped",
            )
        ]

    results: List[CheckResult] = []
    scripts: List[tuple] = [("start.sh", "chmod +x start.sh")]
    if sys.platform == "darwin":
        scripts.append(("start.command", "chmod +x start.command"))

    if root is None:
        for fname, _ in scripts:
            results.append(
                CheckResult(
                    name=f"launcher:{fname}",
                    status=CheckStatus.SKIP,
                    message="No AISC root found — launcher check skipped",
                )
            )
        return results

    for fname, fix_cmd in scripts:
        fpath = root / fname
        try:
            if not fpath.exists():
                results.append(
                    CheckResult(
                        name=f"launcher:{fname}",
                        status=CheckStatus.WARN,
                        message=f"{fname} not found",
                        detail=f"Expected at {fpath}",
                        hint="Verify the launcher script exists in the project root",
                    )
                )
                continue
            if not fpath.is_file():
                results.append(
                    CheckResult(
                        name=f"launcher:{fname}",
                        status=CheckStatus.WARN,
                        message=f"{fname} exists but is not a regular file",
                    )
                )
                continue
            st = fpath.stat()
            if st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                results.append(
                    CheckResult(
                        name=f"launcher:{fname}",
                        status=CheckStatus.PASS,
                        message=f"{fname} is executable",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=f"launcher:{fname}",
                        status=CheckStatus.WARN,
                        message=f"{fname} is not executable",
                        detail=f"Found at {fpath} but missing execute permission",
                        hint=f"Run '{fix_cmd}' to make it executable",
                    )
                )
        except OSError as exc:
            results.append(
                CheckResult(
                    name=f"launcher:{fname}",
                    status=CheckStatus.WARN,
                    message=f"Cannot check {fname}",
                    detail=str(exc),
                )
            )

    return results


def _check_brief_py_syntax(root: Optional[Path]) -> CheckResult:
    """Check 12: ``apps/ai-brief/brief.py`` Python syntax (read-only compile)."""
    if root is None:
        return CheckResult(
            name="brief-py-syntax",
            status=CheckStatus.SKIP,
            message="No AISC root found — syntax check skipped",
        )
    fpath = root / "apps" / "ai-brief" / "brief.py"
    try:
        source = fpath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return CheckResult(
            name="brief-py-syntax",
            status=CheckStatus.WARN,
            message=f"apps/ai-brief/brief.py not found",
            detail=f"Expected at {fpath}",
        )
    except (OSError, UnicodeError) as exc:
        return CheckResult(
            name="brief-py-syntax",
            status=CheckStatus.FAIL,
            message=f"Cannot read brief.py: {exc}",
            detail=str(fpath),
        )

    try:
        compile(source, str(fpath), "exec")
    except SyntaxError as exc:
        return CheckResult(
            name="brief-py-syntax",
            status=CheckStatus.FAIL,
            message=f"Syntax error in apps/ai-brief/brief.py at line {exc.lineno}",
            detail=f"Error at {fpath}:{exc.lineno}",
            hint="Fix the syntax error before running the application",
        )
    except Exception as exc:
        return CheckResult(
            name="brief-py-syntax",
            status=CheckStatus.FAIL,
            message=f"Unexpected error checking brief.py syntax: {exc}",
            detail=str(fpath),
        )

    return CheckResult(
        name="brief-py-syntax",
        status=CheckStatus.PASS,
        message="apps/ai-brief/brief.py syntax is valid",
    )


# ---------------------------------------------------------------------------
# Exit code priority logic
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_DOCKER_UNAVAILABLE = 3
EXIT_PERMISSION_DENIED = 9

ERR_GENERAL = "AISC_ERR_GENERAL"
ERR_DOCKER_UNAVAILABLE = "AISC_ERR_DOCKER_UNAVAILABLE"
ERR_PERMISSION_DENIED = "AISC_ERR_PERMISSION_DENIED"


def _compute_exit_code(checks: List[CheckResult]) -> tuple:
    """Compute final exit code and error details from a completed check list."""
    docker_cli_fail = any(
        c.name == "docker-cli" and c.status == CheckStatus.FAIL for c in checks
    )
    docker_daemon_fail = any(
        c.name == "docker-daemon" and c.status == CheckStatus.FAIL for c in checks
    )
    docker_permission_fail = any(
        c.name == "docker-permission" and c.status == CheckStatus.FAIL for c in checks
    )
    explicit_root_invalid = any(
        c.name == "aisc-root" and c.status == CheckStatus.FAIL for c in checks
    )
    any_other_fail = any(
        c.status == CheckStatus.FAIL
        and c.name
        not in ("docker-cli", "docker-daemon", "docker-permission", "aisc-root")
        for c in checks
    )

    if docker_cli_fail or docker_daemon_fail:
        return EXIT_DOCKER_UNAVAILABLE, ERR_DOCKER_UNAVAILABLE, "Docker is not available"

    if docker_permission_fail:
        return EXIT_PERMISSION_DENIED, ERR_PERMISSION_DENIED, "Docker permission denied"

    if explicit_root_invalid or any_other_fail:
        return EXIT_GENERAL, ERR_GENERAL, "One or more checks failed"

    return EXIT_OK, None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

CheckFunc = Callable[[], CheckResult]
CheckListFunc = Callable[[], List[CheckResult]]


def run_doctor(
    runner: Optional[ProcessRunner] = None,
    root: Optional[Path] = None,
    root_error: Optional[str] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> DoctorReport:
    """Run all host doctor checks and return a ``DoctorReport``.

    Parameters
    ----------
    runner:
        Process runner.  Defaults to ``RealProcessRunner``.
    root:
        Pre-located AISC root (may be ``None``).
    root_error:
        Original error message when an explicit or env root source was
        invalid.  Passed through verbatim to the aisc-root check.
    which:
        Command-discovery callable.  Defaults to ``shutil.which``.
        When ``which('docker')`` returns ``None``, docker-cli is **FAIL**
        (exit 3 / AISC_ERR_DOCKER_UNAVAILABLE) and subsequent docker
        sub-command checks are SKIP with zero subprocess calls.
    """
    import shutil as _shutil

    r = runner or RealProcessRunner()
    w: Callable[[str], Optional[str]] = which if which is not None else _shutil.which

    docker_raw = w("docker")  # may be None when not on PATH / injected None-return
    git_raw = w("git")

    checks: List[CheckResult] = []

    # 1. docker-cli
    #    which('docker') is None  → FAIL (Docker CLI not found, exit 3)
    #    which('docker') returns a path → run --version check
    if docker_raw is None:
        docker_cli = CheckResult(
            name="docker-cli",
            status=CheckStatus.FAIL,
            message="Docker CLI not found",
            detail="docker command not available on PATH",
            hint="Install Docker: https://docs.docker.com/get-docker/",
        )
        docker_cli_available = False
        docker_path = None
    else:
        docker_path = docker_raw
        docker_cli = _check_docker_cli(docker_path, r)
        docker_cli_available = docker_cli.status != CheckStatus.FAIL
    checks.append(docker_cli)

    # 2. docker-daemon  (SKIP when CLI unavailable — no subprocess call)
    if docker_path and docker_cli_available:
        docker_daemon = _check_docker_daemon(docker_path, r, docker_cli_available)
    else:
        docker_daemon = CheckResult(
            name="docker-daemon",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    checks.append(docker_daemon)
    docker_daemon_failed = docker_daemon.status == CheckStatus.FAIL

    # 3. docker-permission  (SKIP when CLI/daemon unavailable)
    if docker_path and docker_cli_available:
        docker_perm = _check_docker_permission(
            docker_path, r, docker_cli_available, docker_daemon_failed
        )
    else:
        docker_perm = CheckResult(
            name="docker-permission",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    checks.append(docker_perm)

    # 4. buildx  (SKIP when CLI/daemon unavailable)
    if docker_path and docker_cli_available:
        buildx = _check_docker_buildx(
            docker_path, r, docker_cli_available, docker_daemon_failed
        )
    else:
        buildx = CheckResult(
            name="docker-buildx",
            status=CheckStatus.SKIP,
            message="Docker CLI not available",
        )
    checks.append(buildx)

    # 5. TUN
    checks.append(_check_tun_device())

    # 6. aisc root — pass through root_error verbatim
    checks.append(_check_aisc_root(root, root_error=root_error))

    # 7. root files
    checks.extend(_check_root_files(root))

    # 8. git  (WARN when missing, not SKIP)
    if git_raw:
        checks.append(_check_git(git_raw, r))
    else:
        checks.append(
            CheckResult(
                name="git",
                status=CheckStatus.WARN,
                message="Git not available",
            )
        )

    # 9. docker-compose
    checks.append(_check_docker_compose(docker_path, r, docker_cli_available))

    # 10. root writability
    checks.append(_check_root_writable(root))

    # 11. launcher scripts
    checks.extend(_check_launcher(root))

    # 12. brief.py syntax
    checks.append(_check_brief_py_syntax(root))

    exit_code, error_code, error_message = _compute_exit_code(checks)

    return DoctorReport(
        checks=checks,
        exit_code=exit_code,
        error_code=error_code,
        error_message=error_message,
    )
