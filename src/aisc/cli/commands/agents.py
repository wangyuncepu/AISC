"""F2-C (fix2-design.md): `aisc claude` / `aisc codex` — agent entry sugar.

One command opens the AGENT inside the ACTIVE workspace's container (the
registry's default pointer = last `aisc run`); `--workspace` retargets
without switching the default. Args after `--` pass through verbatim
(`aisc claude -- -c` → container-side `claude -c`).

Text mode streams the TTY (docker exec -it); JSON mode runs captured and
returns the exit code in the envelope — scripting-friendly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.domain.models import CliError, ProcessResult

AGENTS = ("claude", "codex")


def _resolve_by_workspace(workspace: str, explicit_root: Optional[str]) -> str:
    """Find the registered container bound to this workspace path."""
    from aisc.adapters.container_registry import list_containers
    from aisc.application.resources import locate_aisc_root

    try:
        root = locate_aisc_root(explicit_root=explicit_root)
    except Exception as exc:
        raise CliError(message=f"no AISC root to resolve the workspace: {exc}",
                       exit_code=1, error_code="AISC_ERR_GENERAL") from exc
    # Path-level comparison: separator forms differ between the recording
    # host and this one (POSIX vs Windows); components must not.
    target = Path(workspace)
    matches = [
        entry for entry in list_containers(root)
        if Path(str(entry.get("meta", {}).get("workspace", ""))) == target
    ]
    if not matches:
        raise CliError(
            message=f"no active container is registered for {target} — "
                    f"start one first: aisc run {target}",
            exit_code=4, error_code="AISC_ERR_NOT_FOUND",
        )
    return str(matches[0]["name"])


def cmd_agent(
    agent: str,
    agent_args: List[str],
    workspace: Optional[str] = None,
    name_override: Optional[str] = None,
    explicit_root: Optional[str] = None,
    capture: bool = False,
    executor: Optional[DockerExecutor] = None,
) -> ProcessResult | Dict[str, Any]:
    """Open one agent in the active (or --workspace) container.

    Returns the streaming ProcessResult in text mode; in capture mode a
    JSON-serializable dict for the envelope.
    """
    exec_ = executor or RealDockerExecutor()

    if agent not in AGENTS:
        raise CliError(message=f"unknown agent {agent!r}", exit_code=2,
                       error_code="AISC_ERR_USAGE")

    if workspace:
        name = _resolve_by_workspace(workspace, explicit_root)
    else:
        from aisc.cli.commands import runs as cli_runs
        from aisc.cli.commands.container import discover_container

        # Default leg: the machine-global ACTIVE workspace (never cwd — the
        # cwd anchor trips the data-root overlap gate from $HOME and reads
        # the wrong registry).
        active = cli_runs.get_active()
        if active:
            from aisc.application.data_root import workspace_state_dir

            try:
                root = str(workspace_state_dir(Path(active)))
            except Exception:
                root = explicit_root
        else:
            root = explicit_root
        name = discover_container(name_override=name_override,
                                  explicit_root=root,
                                  executor=exec_)

    # -it only when a real TTY rides along — capture mode pipes stdio, and
    # docker exec -t without a TTY dies with "the input device is not a TTY".
    argv = ["exec", *(["-it"] if not capture else []), name, agent, *agent_args]
    if capture:
        proc = exec_.run_captured(argv)
        return {
            "container": name,
            "agent": agent,
            "agent_args": list(agent_args),
            "exit_code": proc.exit_code,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    proc = exec_.run_streaming(argv)
    if proc.command_not_found:
        raise CliError(message="Docker CLI not found", exit_code=3,
                       error_code="AISC_ERR_DOCKER_UNAVAILABLE")
    return proc
