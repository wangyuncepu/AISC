"""``aisc status | stop | restart | shell | switch`` — container lifecycle commands.

All container operations go through an injected ``DockerExecutor``.
Container discovery: ``--name`` override → state file → structured error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from aisc.application.resources import locate_aisc_root, _RootSourceError
from aisc.adapters.state_file import read_state_key
from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.domain.models import CliError, ProcessResult


# ---------------------------------------------------------------------------
# Shared helper — classify process errors
# ---------------------------------------------------------------------------

def _classify_process_error(proc: ProcessResult, name: str, action: str) -> CliError:
    """Map a failed ProcessResult to a controlled CliError with stable codes."""
    if proc.command_not_found:
        return CliError(
            message="Docker CLI not found",
            exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
        )
    if proc.timed_out:
        return CliError(
            message=f"docker {action} timed out for container '{name}'",
            exit_code=1, error_code="AISC_ERR_GENERAL",
        )
    stderr_lower = (proc.stderr or "").lower()
    if "permission denied" in stderr_lower:
        return CliError(
            message=f"Permission denied accessing container '{name}'",
            exit_code=9, error_code="AISC_ERR_PERMISSION_DENIED",
        )
    if any(kw in stderr_lower for kw in (
        "cannot connect", "is the docker daemon running",
        "connection refused", "error during connect",
    )):
        return CliError(
            message="Docker daemon unreachable",
            exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
        )
    return CliError(
        message=f"docker {action} failed for container '{name}' (exit {proc.exit_code}): "
                f"{(proc.stderr or '').strip()[:200]}",
        exit_code=1, error_code="AISC_ERR_GENERAL",
    )


# ---------------------------------------------------------------------------
# Container discovery
# ---------------------------------------------------------------------------

def discover_container(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
) -> str:
    """Discover the target container name.

    Priority:
    1. Explicit ``--name`` override
    2. ``CONTAINER_NAME`` from ``<aisc_root>/.aisc/state.env``

    Returns:
        Container name string.

    Raises:
        CliError: If no container can be discovered and no name override given.
    """
    if name_override:
        return name_override

    # Try explicit_root path directly first (no structure marker check needed)
    root: Optional[Path] = None
    if explicit_root is not None:
        root = Path(explicit_root).resolve()
        if root.is_dir():
            name = read_state_key(root, "CONTAINER_NAME")
            if name:
                return name

    # Fall back to locate_aisc_root for auto-discovery
    if root is None:
        try:
            root = locate_aisc_root(explicit_root=explicit_root)
        except _RootSourceError:
            pass

    if root is not None:
        name = read_state_key(root, "CONTAINER_NAME")
        if name:
            return name

    raise CliError(
        message=(
            "No container discovered.  Either:\n"
            "  1. Run 'aisc run' in another terminal first (state auto-discovered), or\n"
            "  2. Pass --name CONTAINER_NAME explicitly."
        ),
        exit_code=1,
        error_code="AISC_ERR_CONTAINER_NOT_FOUND",
    )


# ---------------------------------------------------------------------------
# Status result
# ---------------------------------------------------------------------------

@dataclass
class StatusResult:
    """Structured result of container status query."""
    name: str = ""
    exists: bool = False
    running: bool = False
    status: str = ""
    image: str = ""
    container_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "exists": self.exists,
            "running": self.running,
            "status": self.status,
            "image": self.image,
            "container_id": self.container_id,
        }


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

def cmd_status(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> StatusResult:
    """Query container status via ``docker inspect``.

    A missing container returns ``exists=False`` (success), while daemon /
    permission failures raise CliError.
    """
    exec_ = executor or RealDockerExecutor()
    name = discover_container(name_override=name_override,
                              explicit_root=explicit_root)

    # Use docker inspect with Go template for structured output
    fmt = '{{.Name}}\t{{.State.Running}}\t{{.State.Status}}\t{{.Config.Image}}\t{{.Id}}'
    argv = ["inspect", "--format", fmt, name]

    proc = exec_.run_captured(argv, timeout=10.0)

    if proc.command_not_found or proc.timed_out:
        raise _classify_process_error(proc, name, "inspect")

    stderr_lower = (proc.stderr or "").lower()
    if proc.exit_code != 0:
        # "No such object" / "not found" → container doesn't exist (success)
        if any(kw in stderr_lower for kw in (
            "no such object", "no such container", "not found",
        )):
            return StatusResult(name=name, exists=False)
        # Delegate other errors to classifier
        raise _classify_process_error(proc, name, "inspect")

    # Parse tab-separated output
    stdout = proc.stdout.strip()
    if not stdout:
        return StatusResult(name=name, exists=False)

    parts = stdout.split("\t")
    running = parts[1].lower() == "true" if len(parts) > 1 else False
    status = parts[2] if len(parts) > 2 else ""
    image = parts[3] if len(parts) > 3 else ""
    cid = parts[4][:12] if len(parts) > 4 else ""

    return StatusResult(
        name=name,
        exists=True,
        running=running,
        status=status,
        image=image,
        container_id=cid,
    )


def print_status_text(result: StatusResult) -> None:
    """Print status in human-readable format."""
    if not result.exists:
        print(f"Container '{result.name}' not found.")
        return

    running_str = "running" if result.running else "stopped"
    print(f"Container:  {result.name}")
    print(f"Exists:     yes")
    print(f"Running:    {running_str}")
    print(f"Status:     {result.status}")
    print(f"Image:      {result.image}")
    if result.container_id:
        print(f"ID:         {result.container_id}")


# ---------------------------------------------------------------------------
# Stop command
# ---------------------------------------------------------------------------

def cmd_stop(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Stop the discovered container via ``docker stop``.

    Requires the container to exist. Idempotent: stopping an already-stopped
    container returns success.
    """
    exec_ = executor or RealDockerExecutor()
    name = discover_container(name_override=name_override,
                              explicit_root=explicit_root)

    # First check if container exists
    status = cmd_status(name_override=name, explicit_root=explicit_root,
                         executor=executor)

    if not status.exists:
        raise CliError(
            message=f"Container '{name}' not found — nothing to stop.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )

    if not status.running:
        return {"name": name, "stopped": False, "already_stopped": True}

    argv = ["stop", name]
    proc = exec_.run_captured(argv, timeout=30.0)

    if proc.exit_code != 0:
        raise _classify_process_error(proc, name, "stop")

    return {"name": name, "stopped": True, "already_stopped": False}


def print_stop_text(data: Dict[str, Any]) -> None:
    """Print stop result in human-readable format."""
    if data.get("already_stopped"):
        print(f"Container '{data['name']}' was already stopped.")
    else:
        print(f"Container '{data['name']}' stopped.")


# ---------------------------------------------------------------------------
# Restart command
# ---------------------------------------------------------------------------

def cmd_restart(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Restart the discovered container via ``docker restart``.

    Requires the container to exist.
    """
    exec_ = executor or RealDockerExecutor()
    name = discover_container(name_override=name_override,
                              explicit_root=explicit_root)

    # First check if container exists
    status = cmd_status(name_override=name, explicit_root=explicit_root,
                         executor=executor)

    if not status.exists:
        raise CliError(
            message=f"Container '{name}' not found — cannot restart.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )

    argv = ["restart", name]
    proc = exec_.run_captured(argv, timeout=30.0)

    if proc.exit_code != 0:
        raise _classify_process_error(proc, name, "restart")

    return {"name": name, "restarted": True}


def print_restart_text(data: Dict[str, Any]) -> None:
    """Print restart result in human-readable format."""
    print(f"Container '{data['name']}' restarted.")


# ---------------------------------------------------------------------------
# Shell command
# ---------------------------------------------------------------------------

def cmd_shell(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> ProcessResult:
    """Open an interactive shell via ``docker exec -it NAME bash``.

    Uses streaming executor for interactive terminal.  Text-only.
    Returns ProcessResult so caller can inspect exit_code / errors.
    """
    exec_ = executor or RealDockerExecutor()
    name = discover_container(name_override=name_override,
                              explicit_root=explicit_root)

    # Verify container exists and is running
    status = cmd_status(name_override=name, explicit_root=explicit_root,
                         executor=executor)

    if not status.exists:
        raise CliError(
            message=f"Container '{name}' not found — cannot open shell.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )
    if not status.running:
        raise CliError(
            message=f"Container '{name}' is not running — cannot open shell.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )

    argv = ["exec", "-it", name, "bash"]
    proc = exec_.run_streaming(argv)

    # Map transport errors — nonzero exit from docker exec is returned to caller
    if proc.command_not_found or proc.timed_out:
        raise _classify_process_error(proc, name, "exec")

    return proc


# ---------------------------------------------------------------------------
# Switch command — scope-preserving Bash wrapper
# ---------------------------------------------------------------------------
#
# ``docker exec`` starts a new process that does **not** inherit
# CLAUDE_CONFIG_DIR / CC_CONFIG_DIR dynamically exported by entrypoint.sh
# for PID 1.  This wrapper reads the NUL-delimited /proc/1/environ
# **without eval** using a ``while IFS= read -r -d ''`` loop and a ``case``
# statement, so literal special characters (spaces, ``$``, ``;``, quotes,
# backticks, glob chars) in the values survive exactly.
#
# The environ source path is passed as the first positional argument
# (``$1``).  In production this is always ``/proc/1/environ``; tests may
# substitute a temp file.  The wrapper shifts past the source and the
# ``--`` guard, then ``exec "$@"`` with the target command.  The provider
# / subcommand is always positional — never shell-interpolated.
#
# Fail-closed: if the source cannot be read or either variable is absent
# or empty the wrapper exits 101.  No ``$HOME/.claude`` fallback.
#
# .. code-block:: text
#
#    docker exec -it NAME bash -c '
#      while IFS= read -r -d """" entry; do
#        case "$entry" in
#          CLAUDE_CONFIG_DIR=*) ... ;;
#          CC_CONFIG_DIR=*)     ... ;;
#        esac
#      done < "$1"
#      shift; shift   # past source, past --
#      [ -n "${CLAUDE_CONFIG_DIR:-}" ] && [ -n "${CC_CONFIG_DIR:-}" ] || exit 101
#      export CLAUDE_CONFIG_DIR CC_CONFIG_DIR
#      exec "$@"
#    ' aisc-scope /proc/1/environ -- cc-switch
_SCOPE_WRAPPER = "\n".join([
    "while IFS= read -r -d '' entry; do",
    '  case "$entry" in',
    '    CLAUDE_CONFIG_DIR=*) CLAUDE_CONFIG_DIR=${entry#*=} ;;',
    '    CC_CONFIG_DIR=*)     CC_CONFIG_DIR=${entry#*=}     ;;',
    '  esac',
    'done < "$1"',
    'shift',
    'shift',
    'if [ -z "${CLAUDE_CONFIG_DIR:-}" ] || [ -z "${CC_CONFIG_DIR:-}" ]; then',
    "  echo 'Error: Cannot read scope environment from PID 1' >&2",
    '  exit 101',
    'fi',
    'export CLAUDE_CONFIG_DIR CC_CONFIG_DIR',
    'exec "$@"',
    '',  # trailing newline
])

# Production environ source — always /proc/1/environ.
_SCOPE_ENV_SOURCE = "/proc/1/environ"


def _build_switch_argv(name: str, quick: Optional[str]) -> list:
    """Build the ``docker exec`` argv for switch.

    Wraps the target command in a Bash snippet that reads PID 1's
    ``CLAUDE_CONFIG_DIR`` / ``CC_CONFIG_DIR`` from ``_SCOPE_ENV_SOURCE``
    (a NUL-delimited environ file, normally ``/proc/1/environ``).

    The source path and the ``--`` guard are passed as positional
    arguments.  The provider / subcommand follows as positional argv,
    **never** shell-interpolated.

    Returns a list suitable for ``DockerExecutor.run_streaming``.
    """
    if quick:
        return ["exec", "-it", name, "bash", "-c", _SCOPE_WRAPPER,
                "aisc-scope", _SCOPE_ENV_SOURCE, "--", "cs", quick]
    else:
        return ["exec", "-it", name, "bash", "-c", _SCOPE_WRAPPER,
                "aisc-scope", _SCOPE_ENV_SOURCE, "--", "cc-switch"]


def _validate_provider_id(provider: str, explicit_root: Optional[str] = None) -> None:
    """Validate that *provider* is a non-empty token and optionally exists in catalog.

    Catalog lookup is best-effort; if the catalog is unavailable, validation
    is deferred to the container's ``cs`` command.
    """
    if not provider or not provider.strip():
        raise CliError(
            message="Provider name required for --quick switch",
            exit_code=2, error_code="AISC_ERR_USAGE",
        )

    # Try to validate against catalog (best-effort)
    try:
        from aisc.application.provider_service import run_provider_show
        result = run_provider_show(provider, explicit_root=explicit_root)
        if result.exit_code != 0 and result.error_message:
            if "not found" in result.error_message.lower():
                raise CliError(
                    message=f"Unknown provider: {provider}",
                    exit_code=2, error_code="AISC_ERR_USAGE",
                )
    except CliError:
        raise
    except Exception:
        # Catalog not available — defer to container's cs command
        pass


def cmd_switch(
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    quick: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> ProcessResult:
    """Switch AI provider inside the container.

    Default (no --quick): ``docker exec -it NAME cc-switch`` (full TUI).
    Quick mode: ``docker exec -it NAME cs PROVIDER``.

    Uses streaming executor for interactive terminal.  Text-only.
    Returns ProcessResult so caller can inspect exit_code / errors.
    """
    exec_ = executor or RealDockerExecutor()

    # Validate --quick provider early (before any Docker interaction)
    if quick is not None:
        _validate_provider_id(quick, explicit_root=explicit_root)
        if not quick:
            raise CliError(
                message="Provider name required for --quick switch",
                exit_code=2, error_code="AISC_ERR_USAGE",
            )

    name = discover_container(name_override=name_override,
                              explicit_root=explicit_root)

    # Verify container exists and is running
    status = cmd_status(name_override=name, explicit_root=explicit_root,
                         executor=executor)

    if not status.exists:
        raise CliError(
            message=f"Container '{name}' not found — cannot switch provider.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )
    if not status.running:
        raise CliError(
            message=f"Container '{name}' is not running — cannot switch provider.",
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )

    # Build argv via the scope-preserving wrapper
    argv = _build_switch_argv(name, quick)

    proc = exec_.run_streaming(argv)

    if proc.command_not_found or proc.timed_out:
        raise _classify_process_error(proc, name, "exec")

    return proc


def print_switch_text(data: Dict[str, Any]) -> None:
    """Print switch result summary."""
    name = data.get("name", "")
    provider = data.get("provider", "")
    quick = data.get("quick", False)
    if quick and provider:
        print(f"Switched container '{name}' to provider '{provider}'.")
    elif provider:
        print(f"Switched container '{name}' to provider '{provider}'.")
    else:
        print(f"Provider switch completed for container '{name}'.")
