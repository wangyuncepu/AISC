"""Main CLI entry point — argument parsing, command dispatch, output formatting.

``aisc version``, ``aisc doctor``, ``aisc build``, and ``aisc run`` commands.
``python -m aisc`` and console_script ``aisc`` are both supported.

All docker operations are injected through a ``DockerExecutor``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aisc import __version__
from aisc.cli.output import (
    JsonlEmitter,
    build_envelope,
    build_error,
    emit_json,
    emit_json_usage_error,
    print_doctor_text,
)
from aisc.domain.models import CliError, DoctorReport, VersionInfo


# ---------------------------------------------------------------------------
# Custom argument parser — JSON-aware error handling
# ---------------------------------------------------------------------------

class _AiscArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that respects ``--format json`` when reporting errors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._aisc_format: Optional[str] = None
        self._aisc_command: str = "aisc"

    def error(self, message: str) -> None:  # type: ignore[override]
        if self._aisc_format == "json":
            emit_json_usage_error(
                command=self._aisc_command or "aisc",
                version=__version__,
                message=message,
            )
            sys.exit(2)
        else:
            super().error(message)


# ---------------------------------------------------------------------------
# Parser setup
# ---------------------------------------------------------------------------

def _add_global_args(p: argparse.ArgumentParser, *, is_subparser: bool = False) -> None:
    """Add global options."""
    default_val = argparse.SUPPRESS if is_subparser else "text"
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default=default_val,
        help="Output format (default: text)",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS if is_subparser else False,
        help="Disable ANSI color output",
    )
    p.add_argument(
        "--aisc-root",
        type=str,
        default=argparse.SUPPRESS if is_subparser else None,
        help="Path to AISC repository root",
    )
    p.add_argument(
        "--events",
        action="store_true",
        default=argparse.SUPPRESS if is_subparser else False,
        help="Enable JSONL event stream output (build/run commands)",
    )


def _build_parser() -> _AiscArgumentParser:
    """Build the top-level argument parser."""
    parser = _AiscArgumentParser(
        prog="aisc",
        description="AISC CLI — Super Claude workstation management",
    )
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command", title="commands")

    # --- version ---
    vp = sub.add_parser("version", help="Show version information", allow_abbrev=False)
    _add_global_args(vp, is_subparser=True)

    # --- doctor ---
    dp = sub.add_parser("doctor", help="Run environment diagnostics", allow_abbrev=False)
    _add_global_args(dp, is_subparser=True)

    # --- build ---
    bp = sub.add_parser("build", help="Build Docker image", allow_abbrev=False)
    _add_global_args(bp, is_subparser=True)
    bp.add_argument("--tag", "-t", type=str, default="super-claude:latest",
                    help="Image tag (default: super-claude:latest)")
    bp.add_argument("--no-cache", action="store_true", default=False,
                    help="Disable Docker build cache")
    bp.add_argument("--pull", action="store_true", default=False,
                    help="Always pull the base image")
    bp.add_argument("--dry-run", action="store_true", default=False,
                    help="Plan the build without executing")

    # --- run ---
    rp = sub.add_parser("run", help="Run Docker container", allow_abbrev=False)
    _add_global_args(rp, is_subparser=True)
    rp.add_argument("--image", "-i", type=str, default="super-claude:latest",
                    help="Docker image (default: super-claude:latest)")
    rp.add_argument("--workspace", type=str, default=None,
                    help="Host workspace path to bind-mount (default: current directory)")
    rp.add_argument("--name", type=str, default="super-claude-station",
                    help="Container name prefix (unique suffix appended)")
    rp.add_argument("--network", type=str, choices=["direct", "proxy"],
                    default=argparse.SUPPRESS,
                    help="Network mode: direct or proxy (default: direct)")
    rp.add_argument("--profile", type=str, choices=["proxy"],
                    default=None,
                    help="Compatibility alias for --network proxy (prefer --network proxy)")
    rp.add_argument("--non-interactive", action="store_true", default=False,
                    help="Run without interactive terminal (no -it, stdin=DEVNULL)")
    rp.add_argument("--dry-run", action="store_true", default=False,
                    help="Plan the run without executing")
    rp.add_argument("--label", type=str, default="",
                    help="Container label for multi-container addressing (optional)")
    rp.add_argument("--keep-alive", action="store_true", default=False,
                    help="Keep container after exit (omit --rm flag)")

    # --- config ---
    cp = sub.add_parser("config", help="Config management", allow_abbrev=False)
    _add_global_args(cp, is_subparser=True)
    csub = cp.add_subparsers(dest="config_command", title="config commands",
                              parser_class=_AiscArgumentParser)

    cv = csub.add_parser("validate", help="Validate config files", allow_abbrev=False)
    _add_global_args(cv, is_subparser=True)
    cv.add_argument("--config", type=str, default=None,
                    help="Explicit user config file path")
    cv.add_argument("--workspace", type=str, default=None,
                    help="Workspace root path")

    ce = csub.add_parser("effective", help="Show effective config", allow_abbrev=False)
    _add_global_args(ce, is_subparser=True)
    ce.add_argument("--config", type=str, default=None,
                    help="Explicit user config file path")
    ce.add_argument("--workspace", type=str, default=None,
                    help="Workspace root path")

    cs = csub.add_parser("show", help="Alias for 'config effective' (compatibility name)",
                         allow_abbrev=False)
    _add_global_args(cs, is_subparser=True)
    cs.add_argument("--config", type=str, default=None,
                    help="Explicit user config file path")
    cs.add_argument("--workspace", type=str, default=None,
                    help="Workspace root path")

    # --- profile ---
    prp = sub.add_parser("profile", help="Profile management", allow_abbrev=False)
    _add_global_args(prp, is_subparser=True)
    prsub = prp.add_subparsers(dest="profile_command", title="profile commands",
                                parser_class=_AiscArgumentParser)

    prl = prsub.add_parser("list", help="List available profiles", allow_abbrev=False)
    _add_global_args(prl, is_subparser=True)

    prs = prsub.add_parser("show", help="Show profile details", allow_abbrev=False)
    _add_global_args(prs, is_subparser=True)
    prs.add_argument("name", type=str, nargs="?", default=None,
                      help="Profile name (default: safe)")

    # --- provider ---
    pp = sub.add_parser("provider", help="Provider management", allow_abbrev=False)
    _add_global_args(pp, is_subparser=True)
    psub = pp.add_subparsers(dest="provider_command", title="provider commands",
                              parser_class=_AiscArgumentParser)

    pl = psub.add_parser("list", help="List available providers", allow_abbrev=False)
    _add_global_args(pl, is_subparser=True)

    ps = psub.add_parser("show", help="Show provider details", allow_abbrev=False)
    _add_global_args(ps, is_subparser=True)
    ps.add_argument("name", type=str, help="Provider id or alias")

    pa = psub.add_parser("add", help="Open providers.json for editing", allow_abbrev=False)
    _add_global_args(pa, is_subparser=True)
    pa.add_argument("--id", dest="provider_id", default="", help="(Deprecated) Provider id")
    pa.add_argument("--name", default="", help="(Deprecated) Display name")
    pa.add_argument("--auth-type", default="", choices=("", "token", "api_key"), help="(Deprecated) Auth type")
    pa.add_argument("--auth-key-name", default="", help="(Deprecated) Environment key name")
    pa.add_argument("--base-url", default="", help="(Deprecated) Provider HTTP(S) base URL")
    pa.add_argument("--alias", dest="aliases", action="append", default=[], help="(Deprecated) Alias")
    pa.add_argument("--model", default="")
    pa.add_argument("--default-opus", default="")
    pa.add_argument("--default-sonnet", default="")
    pa.add_argument("--default-haiku", default="")
    pa.add_argument("--subagent", default="")
    pa.add_argument("--effort", default="")
    pa.add_argument("--compact", default="")
    pa.add_argument("--overwrite", action="store_true", help="(Deprecated) Replace existing provider")

    # --- status ---
    stp = sub.add_parser("status", help="Show container status", allow_abbrev=False)
    _add_global_args(stp, is_subparser=True)
    stp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    stp.add_argument("--label", type=str, default=None,
                     help="Target container by label")

    # --- stop ---
    spp = sub.add_parser("stop", help="Stop the container", allow_abbrev=False)
    _add_global_args(spp, is_subparser=True)
    spp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    spp.add_argument("--label", type=str, default=None,
                     help="Target container by label")

    # --- restart ---
    rsp = sub.add_parser("restart", help="Restart the container", allow_abbrev=False)
    _add_global_args(rsp, is_subparser=True)
    rsp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    rsp.add_argument("--label", type=str, default=None,
                     help="Target container by label")

    # --- shell ---
    shp = sub.add_parser("shell", help="Open a bash shell in the container", allow_abbrev=False)
    _add_global_args(shp, is_subparser=True)
    shp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    shp.add_argument("--label", type=str, default=None,
                     help="Target container by label")

    # --- skill ---
    skp = sub.add_parser("skill", help="Manage skill bundle imports", allow_abbrev=False)
    _add_global_args(skp, is_subparser=True)
    sksub = skp.add_subparsers(dest="skill_command", title="skill commands",
                                parser_class=_AiscArgumentParser)

    ska = sksub.add_parser("add", help="Add a skill from GitHub URL", allow_abbrev=False)
    _add_global_args(ska, is_subparser=True)
    ska.add_argument("url", type=str, help="GitHub HTTPS blob/tree/raw URL for SKILL.md or directory")

    skl = sksub.add_parser("list", help="List lock-managed skills", allow_abbrev=False)
    _add_global_args(skl, is_subparser=True)

    skr = sksub.add_parser("remove", help="Remove a lock-managed skill", allow_abbrev=False)
    _add_global_args(skr, is_subparser=True)
    skr.add_argument("name", type=str, help="Skill name to remove")

    skc = sksub.add_parser("check", help="Check lock integrity offline", allow_abbrev=False)
    _add_global_args(skc, is_subparser=True)

    # --- switch ---
    swp = sub.add_parser("switch", help="Switch AI provider in the container", allow_abbrev=False)
    _add_global_args(swp, is_subparser=True)
    swp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    swp.add_argument("--label", type=str, default=None,
                     help="Target container by label")
    swp.add_argument("--quick", type=str, default=None,
                     help="Provider id or alias for quick switch (e.g. deepseek)")

    # --- ps ---
    psp = sub.add_parser("ps", help="List all registered containers", allow_abbrev=False)
    _add_global_args(psp, is_subparser=True)

    return parser


# ---------------------------------------------------------------------------
# JSON format / events detection from raw argv
# ---------------------------------------------------------------------------

def _detect_json_format(argv: List[str]) -> bool:
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv) and argv[i + 1] == "json":
            return True
        if arg == "--format=json":
            return True
    return False


def _detect_events(argv: List[str]) -> bool:
    return "--events" in argv


def _detect_command(argv: List[str]) -> Optional[str]:
    known = {"version", "doctor", "build", "run", "config", "provider", "profile",
             "status", "stop", "restart", "shell", "switch", "skill"}
    for arg in argv:
        if arg in known:
            return arg
    return None


def _resolve_aisc_root_from_argv(argv: List[str]) -> Optional[str]:
    """Resolve ``--aisc-root`` from raw *argv* with last-wins semantics.

    Returns the last ``--aisc-root VALUE`` or ``--aisc-root=VALUE``,
    or ``None`` if the flag is absent.
    """
    last = None
    for i, arg in enumerate(argv):
        if arg == "--aisc-root" and i + 1 < len(argv):
            last = argv[i + 1]
        elif arg.startswith("--aisc-root="):
            last = arg.split("=", 1)[1]
    return last


# ---------------------------------------------------------------------------
# Arg post-processing: resolve last-wins --format
# ---------------------------------------------------------------------------

def _resolve_format(args: argparse.Namespace, argv: List[str]) -> str:
    last = "text"
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv):
            val = argv[i + 1]
            if val in ("text", "json"):
                last = val
        elif arg.startswith("--format="):
            val = arg.split("=", 1)[1]
            if val in ("text", "json"):
                last = val
    return last


# ---------------------------------------------------------------------------
# Command implementations (existing, unchanged)
# ---------------------------------------------------------------------------

def _cmd_version(args: argparse.Namespace) -> VersionInfo:
    from aisc.application.version import gather_version_info
    from aisc.application.resources import _RootSourceError
    try:
        info = gather_version_info(explicit_root=args.aisc_root, cwd=Path.cwd())
    except _RootSourceError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc
    except Exception as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc
    return info


def _cmd_doctor(args: argparse.Namespace) -> Tuple[Dict[str, Any], DoctorReport]:
    from aisc.application.doctor import run_doctor
    from aisc.application.resources import locate_aisc_root, _RootSourceError
    root = None
    root_error: Optional[str] = None
    try:
        root = locate_aisc_root(explicit_root=args.aisc_root)
    except _RootSourceError as exc:
        root_error = str(exc)
    except Exception as exc:
        root_error = str(exc)
    report = run_doctor(root=root, root_error=root_error)
    data: Dict[str, Any] = {"host": report.to_dict(), "container": None}
    return data, report


def _cmd_profile(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Dispatch profile list/show."""
    from aisc.cli.commands.profile import cmd_profile_list, cmd_profile_show

    sub = getattr(args, "profile_command", None)
    if sub not in ("list", "show"):
        if effective_format == "json":
            emit_json_usage_error(
                command="profile", version=__version__,
                message="Unknown profile subcommand",
            )
        else:
            print("Error: Unknown profile subcommand", file=sys.stderr)
        sys.exit(2)

    if sub == "list":
        result = cmd_profile_list()
    else:
        # show — optional NAME defaults to "safe"
        name = getattr(args, "name", None) or "safe"
        result = cmd_profile_show(name)

    errors: List[Dict[str, Any]] = []
    if result.exit_code != 0:
        errors.append(build_error(result.error_code or "AISC_ERR_GENERAL",
                                   result.error_message))

    return result.data, result.exit_code, errors




# ---------------------------------------------------------------------------
# Build / Run command dispatch — all docker through injected executor
# ---------------------------------------------------------------------------

def _cmd_build(
    args: argparse.Namespace,
    emitter: Optional[JsonlEmitter],
    effective_format: str,
) -> Tuple[Optional[Dict[str, Any]], int, List[Dict[str, Any]]]:
    """Execute ``aisc build``. Returns (data, exit_code, errors)."""
    from aisc.cli.commands.build import plan_build, run_build, BuildResult
    from aisc.application.resources import locate_aisc_root, _RootSourceError

    root = None
    try:
        root = locate_aisc_root(explicit_root=args.aisc_root)
    except _RootSourceError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc
    if root is None:
        raise CliError(
            message="AISC root not found. Use --aisc-root to specify a path, "
                    "or run from within an AISC repository.",
            exit_code=1, error_code="AISC_ERR_GENERAL",
        )

    # Run wizard if in interactive text mode and no explicit flags provided
    tag = getattr(args, "tag", "super-claude:latest")
    no_cache = getattr(args, "no_cache", False)
    pull = getattr(args, "pull", False)
    dry_run = getattr(args, "dry_run", False)

    # Check if user provided explicit build options
    tag_provided = any(arg in sys.argv for arg in ["--tag", "-t"])
    cache_provided = "--no-cache" in sys.argv
    pull_provided = "--pull" in sys.argv

    # Run wizard if: text mode + interactive + no explicit options
    if (effective_format == "text" and emitter is None and
        not dry_run and not tag_provided and not cache_provided and not pull_provided):
        from aisc.cli.commands.wizard import run_build_wizard
        try:
            tag, no_cache, pull, proxy_config = run_build_wizard(
                default_tag=tag, aisc_root=root
            )
        except KeyboardInterrupt:
            raise CliError(message="Build cancelled by user", exit_code=130,
                           error_code="AISC_ERR_CANCELLED")

    plan = plan_build(
        root=root,
        tag=tag,
        no_cache=no_cache,
        pull=pull,
        dry_run=dry_run,
    )

    # text mode → streaming (real-time build log); json/events → captured
    is_streaming = (effective_format == "text" and emitter is None)
    result = run_build(plan, emitter=emitter, streaming=is_streaming)
    return result.to_dict(), 0, []


def _cmd_run(
    args: argparse.Namespace,
    emitter: Optional[JsonlEmitter],
    effective_format: str,
    aisc_root_arg: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], int, List[Dict[str, Any]]]:
    """Execute ``aisc run``. Returns (data, exit_code, errors)."""
    from aisc.cli.commands.run import plan_run, run_container
    from aisc.application.resources import locate_aisc_root, _RootSourceError
    from aisc.application.provider_service import (
        ensure_user_provider_catalog,
        user_provider_catalog_path,
    )

    # Locate AISC root for proxy config resolution
    aisc_root = None
    try:
        aisc_root = locate_aisc_root(explicit_root=aisc_root_arg)
    except _RootSourceError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc

    # Resolve --profile proxy alias
    profile = getattr(args, "profile", None)
    network = getattr(args, "network", argparse.SUPPRESS)
    network_explicit = network is not argparse.SUPPRESS
    if network is argparse.SUPPRESS:
        network = "direct"  # default when neither --network nor --profile is given

    if profile == "proxy":
        if network_explicit and network == "direct":
            raise CliError(
                message="--profile proxy conflicts with --network direct",
                exit_code=2, error_code="AISC_ERR_USAGE",
            )
        network = "proxy"

    non_interactive = getattr(args, "non_interactive", False)
    is_interactive = (effective_format == "text" and emitter is None and not non_interactive)
    capture = (effective_format != "text" or emitter is not None)

    provider_config_dir = str(user_provider_catalog_path().parent)
    if aisc_root is not None:
        try:
            if not getattr(args, "dry_run", False):
                provider_config_dir = str(
                    ensure_user_provider_catalog(str(aisc_root)).parent
                )
        except PermissionError as exc:
            raise CliError(
                message=f"Cannot initialize provider catalog: {exc}",
                exit_code=9, error_code="AISC_ERR_PERMISSION_DENIED",
            ) from exc
        except (OSError, ValueError) as exc:
            raise CliError(
                message=f"Cannot initialize provider catalog: {exc}",
                exit_code=1, error_code="AISC_ERR_GENERAL",
            ) from exc

    plan = plan_run(
        image=getattr(args, "image", "super-claude:latest"),
        workspace=getattr(args, "workspace", None) or str(Path.cwd()),
        name=getattr(args, "name", "super-claude-station"),
        network=network,
        dry_run=getattr(args, "dry_run", False),
        interactive=is_interactive,
        non_interactive=non_interactive,
        label=getattr(args, "label", ""),
        keep_alive=getattr(args, "keep_alive", False),
        provider_config_dir=provider_config_dir,
        aisc_root=aisc_root,
    )

    result = run_container(plan, emitter=emitter, capture=capture,
                           aisc_root=aisc_root)
    return result.to_dict(), 0, []


def _cmd_config(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Dispatch config validate/effective.  ServiceResult owns exit codes."""
    from aisc.cli.commands.config import (
        cmd_config_validate, cmd_config_effective,
    )

    sub = getattr(args, "config_command", None)
    if sub not in ("validate", "effective", "show"):
        if effective_format == "json":
            emit_json_usage_error(
                command="config", version=__version__,
                message="Unknown config subcommand",
            )
        else:
            print("Error: Unknown config subcommand", file=sys.stderr)
        sys.exit(2)

    explicit_config = getattr(args, "config", None)
    workspace = getattr(args, "workspace", None)

    if sub == "validate":
        result = cmd_config_validate(
            explicit_config=explicit_config, workspace=workspace,
        )
    else:
        # effective / show — same handler
        result = cmd_config_effective(
            explicit_config=explicit_config, workspace=workspace,
        )

    # Build errors list — exactly one top-level error on failure
    errors: List[Dict[str, Any]] = []
    if result.exit_code != 0:
        errors.append(build_error(result.error_code or "AISC_ERR_GENERAL",
                                   result.error_message))

    return result.data, result.exit_code, errors


def _cmd_provider(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Dispatch provider list/show/add."""
    from aisc.cli.commands.provider import cmd_provider_add, cmd_provider_list, cmd_provider_show

    sub = getattr(args, "provider_command", None)
    if sub not in ("list", "show", "add"):
        if effective_format == "json":
            emit_json_usage_error(
                command="provider", version=__version__,
                message="Unknown provider subcommand",
            )
        else:
            print("Error: Unknown provider subcommand", file=sys.stderr)
        sys.exit(2)

    if sub == "list":
        result = cmd_provider_list(aisc_root=getattr(args, "aisc_root", None))
    elif sub == "show":
        # show
        name = getattr(args, "name", None)
        if not name:
            if effective_format == "json":
                emit_json_usage_error(
                    command="provider", version=__version__,
                    message="Provider name required for 'show'",
                )
            else:
                print("Error: Provider name required for 'show'", file=sys.stderr)
            sys.exit(2)
        result = cmd_provider_show(
            name=name,
            aisc_root=getattr(args, "aisc_root", None),
        )
    else:
        result = cmd_provider_add(
            provider_id=args.provider_id, name=args.name,
            auth_type=args.auth_type, auth_key_name=args.auth_key_name,
            base_url=args.base_url, aliases=args.aliases, model=args.model,
            default_opus=args.default_opus, default_sonnet=args.default_sonnet,
            default_haiku=args.default_haiku, subagent=args.subagent,
            effort=args.effort, compact=args.compact, overwrite=args.overwrite,
            aisc_root=getattr(args, "aisc_root", None),
        )

    errors: List[Dict[str, Any]] = []
    if result.exit_code != 0:
        errors.append(build_error(result.error_code or "AISC_ERR_GENERAL",
                                   result.error_message))

    return result.data, result.exit_code, errors


# ---------------------------------------------------------------------------
# Container lifecycle command handlers
# ---------------------------------------------------------------------------

def _cmd_status(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc status``.  Supports --format json."""
    from aisc.cli.commands.container import cmd_status

    result = cmd_status(
        name_override=getattr(args, "name", None),
        explicit_root=getattr(args, "aisc_root", None),
        label_override=getattr(args, "label", None),
    )
    return result.to_dict(), 0, []


def _cmd_stop(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc stop``.  Supports --format json."""
    from aisc.cli.commands.container import cmd_stop

    data = cmd_stop(
        name_override=getattr(args, "name", None),
        explicit_root=getattr(args, "aisc_root", None),
        label_override=getattr(args, "label", None),
    )
    return data, 0, []


def _cmd_restart(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc restart``.  Supports --format json."""
    from aisc.cli.commands.container import cmd_restart

    data = cmd_restart(
        name_override=getattr(args, "name", None),
        explicit_root=getattr(args, "aisc_root", None),
        label_override=getattr(args, "label", None),
    )
    return data, 0, []


def _cmd_skill(
    args: argparse.Namespace,
    effective_format: str,
    aisc_root_arg: Optional[str],
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Dispatch aisc skill add/list/remove/check."""
    from aisc.application.resources import locate_aisc_root, _RootSourceError
    from aisc.application import skill_service

    # Resolve AISC root
    try:
        root = locate_aisc_root(explicit_root=aisc_root_arg)
    except _RootSourceError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc
    if root is None:
        raise CliError(
            message="AISC root not found. Use --aisc-root to specify a path, "
                    "or run from within an AISC repository.",
            exit_code=1, error_code="AISC_ERR_GENERAL",
        )

    sub = getattr(args, "skill_command", None)
    if sub not in ("add", "list", "remove", "check"):
        if effective_format == "json":
            emit_json_usage_error(
                command="skill", version=__version__,
                message="Unknown skill subcommand. Use: add, list, remove, check",
            )
        else:
            print("Error: Unknown skill subcommand. Use: add, list, remove, check",
                  file=sys.stderr)
        sys.exit(2)

    if sub == "add":
        url = getattr(args, "url", "")
        if not url:
            raise CliError(message="URL required for skill add", exit_code=2,
                           error_code="AISC_ERR_USAGE")
        try:
            entry, warnings = skill_service.skill_add(url, root=root)
        except Exception as exc:
            raise CliError(message=str(exc), exit_code=1,
                           error_code="AISC_ERR_GENERAL") from exc

        data: Dict[str, Any] = {
            "name": entry.name,
            "source_url": entry.source_url,
            "resolved_commit": entry.resolved_commit,
            "requested_ref": entry.requested_ref,
            "owner": entry.owner,
            "repo": entry.repo,
            "file_count": len(entry.files),
            "warnings": warnings,
            "dependencies": sorted(entry.detected_references),
        }
        if effective_format == "text":
            _print_skill_add_text(entry, warnings)
        return data, 0, []

    elif sub == "list":
        try:
            entries = skill_service.skill_list(root=root)
        except Exception as exc:
            raise CliError(message=str(exc), exit_code=1,
                           error_code="AISC_ERR_GENERAL") from exc
        data = {"skills": [
            {
                "name": e.name,
                "source_url": e.source_url,
                "resolved_commit": e.resolved_commit,
                "file_count": len(e.files),
                "dependencies": sorted(e.detected_references),
            }
            for e in entries
        ]}
        if effective_format == "text":
            _print_skill_list_text(entries)
        return data, 0, []

    elif sub == "remove":
        name = getattr(args, "name", "")
        if not name:
            raise CliError(message="Skill name required for remove", exit_code=2,
                           error_code="AISC_ERR_USAGE")
        try:
            removed, info = skill_service.skill_remove(name, root=root)
        except Exception as exc:
            raise CliError(message=str(exc), exit_code=1,
                           error_code="AISC_ERR_GENERAL") from exc

        data: Dict[str, Any] = {"removed": removed}
        if info.get("directory_missing"):
            data["directory_missing"] = True
        if info.get("stale_backup"):
            data["stale_backup"] = info["stale_backup"]
            data["cleanup_warning"] = info.get("cleanup_warning", "")
        if effective_format == "text":
            print(f"Removed skill: {removed}")
            if info.get("directory_missing"):
                print("  Note: managed directory was already missing")
            if info.get("stale_backup"):
                print(f"  Warning: stale backup at {info['stale_backup']}: {info.get('cleanup_warning','')}")
        return data, 0, []

    elif sub == "check":
        try:
            result = skill_service.skill_check(root=root)
        except Exception as exc:
            raise CliError(message=str(exc), exit_code=1,
                           error_code="AISC_ERR_GENERAL") from exc
        data = {
            "in_sync": result.in_sync,
            "drift_items": result.drift_items,
        }
        exit_code = 0 if result.in_sync else 1
        if effective_format == "text":
            _print_skill_check_text(result)
        return data, exit_code, []

    return {}, 0, []


def _print_skill_add_text(entry: Any, warnings: List[str]) -> None:
    """Print text output for skill add."""
    print(f"Added skill: {entry.name}")
    print(f"  Source:   {entry.source_url}")
    print(f"  Commit:   {entry.resolved_commit}")
    print(f"  Ref:      {entry.requested_ref}")
    print(f"  Files:    {len(entry.files)}")
    if entry.detected_references:
        print(f"  Deps:     {', '.join(sorted(entry.detected_references))}")
    for w in warnings:
        print(f"  Warning:  {w}")


def _print_skill_list_text(entries: List[Any]) -> None:
    """Print text output for skill list."""
    if not entries:
        print("No skills managed by skills-lock.json")
        return
    for e in entries:
        print(f"  {e.name}")
        print(f"    Source: {e.source_url}")
        print(f"    Commit: {e.resolved_commit[:12]}...")
        print(f"    Files:  {len(e.files)}")
        if e.detected_references:
            print(f"    Deps:   {', '.join(sorted(e.detected_references))}")
        print()


def _print_skill_check_text(result: Any) -> None:
    """Print text output for skill check."""
    if result.in_sync:
        print("Skills are in sync with lock.")
        return
    print("Drift detected:")
    for item in result.drift_items:
        print(f"  - {item}")



def _cmd_shell(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc shell``.  Text-only interactive."""
    from aisc.cli.commands.container import cmd_shell, discover_container

    if effective_format == "json":
        emit_json_usage_error(
            command="shell", version=__version__,
            message="shell only supports text output, --format json is not supported",
        )
        sys.exit(2)

    # Discover name once for use in returned data
    name_override = getattr(args, "name", None)
    label_override = getattr(args, "label", None)
    try:
        discovered_name = name_override or discover_container(
            name_override=None,
            explicit_root=getattr(args, "aisc_root", None),
            label_override=label_override,
        )
    except Exception:
        discovered_name = name_override or ""

    proc = cmd_shell(
        name_override=name_override,
        explicit_root=getattr(args, "aisc_root", None),
        label_override=label_override,
    )

    exit_code = proc.exit_code if proc.exit_code >= 0 else 1
    errors: List[Dict[str, Any]] = []
    if exit_code != 0:
        errors.append(build_error(
            "AISC_ERR_GENERAL",
            proc.stderr or f"docker exec exited with code {exit_code}",
        ))

    return {"name": discovered_name, "exit_code": exit_code}, exit_code, errors


def _cmd_switch(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc switch``.  Text-only interactive."""
    from aisc.cli.commands.container import cmd_switch, discover_container

    if effective_format == "json":
        emit_json_usage_error(
            command="switch", version=__version__,
            message="switch only supports text output, --format json is not supported",
        )
        sys.exit(2)

    # Discover name once for use in returned data
    name_override = getattr(args, "name", None)
    label_override = getattr(args, "label", None)
    try:
        discovered_name = name_override or discover_container(
            name_override=None,
            explicit_root=getattr(args, "aisc_root", None),
            label_override=label_override,
        )
    except Exception:
        discovered_name = name_override or ""

    quick = getattr(args, "quick", None)

    proc = cmd_switch(
        name_override=name_override,
        explicit_root=getattr(args, "aisc_root", None),
        quick=quick,
        label_override=label_override,
    )

    exit_code = proc.exit_code if proc.exit_code >= 0 else 1
    errors: List[Dict[str, Any]] = []
    if exit_code != 0:
        errors.append(build_error(
            "AISC_ERR_GENERAL",
            proc.stderr or f"docker exec exited with code {exit_code}",
        ))

    data: Dict[str, Any] = {
        "name": discovered_name,
        "exit_code": exit_code,
    }
    if quick:
        data["provider"] = quick
        data["quick"] = True
    return data, exit_code, errors


def _cmd_ps(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[List[Dict[str, Any]], int, List[Dict[str, Any]]]:
    """Execute ``aisc ps``.  Supports --format json."""
    from aisc.cli.commands.container import cmd_ps

    rows = cmd_ps(
        explicit_root=getattr(args, "aisc_root", None),
    )
    data = [{"name": r.name, "label": r.label, "status": r.status,
             "running": r.running, "image": r.image, "workspace": r.workspace}
            for r in rows]
    return data, 0, []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:
    """Main CLI entry point."""
    parser = _build_parser()
    args_list = list(argv) if argv is not None else sys.argv[1:]

    # Pre-detect format/events/command for error messages
    json_requested = _detect_json_format(args_list)
    events_requested = _detect_events(args_list)
    cmd_hint = _detect_command(args_list) or "aisc"
    parser._aisc_format = "json" if json_requested else None
    parser._aisc_command = cmd_hint

    # Propagate json format to config subparser for unknown-subcommand errors
    if "config" in args_list:
        try:
            cfg_parser = [a for a in parser._subparsers._group_actions
                          if a.dest == "command"][0].choices["config"]
            cfg_parser._aisc_format = "json" if json_requested else None
            cfg_parser._aisc_command = "config"
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate json format to provider subparser for unknown-subcommand errors
    if "provider" in args_list:
        try:
            pv_parser = [a for a in parser._subparsers._group_actions
                          if a.dest == "command"][0].choices["provider"]
            pv_parser._aisc_format = "json" if json_requested else None
            pv_parser._aisc_command = "provider"
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate json format to profile subparser for unknown-subcommand errors
    if "profile" in args_list:
        try:
            pf_parser = [a for a in parser._subparsers._group_actions
                          if a.dest == "command"][0].choices["profile"]
            pf_parser._aisc_format = "json" if json_requested else None
            pf_parser._aisc_command = "profile"
        except (AttributeError, IndexError, KeyError):
            pass

    try:
        args = parser.parse_args(args_list)
    except SystemExit:
        raise

    # Resolve --aisc-root from raw argv with last-wins semantics.
    # This decouples root resolution from argparse's subparser defaults
    # and ensures --aisc-root works both before and after any command.
    resolved_root = _resolve_aisc_root_from_argv(args_list)
    if resolved_root is not None:
        args.aisc_root = resolved_root

    # Resolve effective format
    effective_format = _resolve_format(args, args_list)
    parser._aisc_format = effective_format
    if getattr(args, "command", None):
        parser._aisc_command = args.command

    # --events flag
    args_events = getattr(args, "events", False)
    if args_events is argparse.SUPPRESS:
        args_events = False

    # --format json and --events are mutually exclusive
    if effective_format == "json" and args_events:
        emit_json_usage_error(
            command=args.command or cmd_hint, version=__version__,
            error_code="AISC_ERR_USAGE",
            message="--format json and --events are mutually exclusive",
        )
        sys.exit(2)

    # Require a command
    if not getattr(args, "command", None):
        if effective_format == "json":
            emit_json_usage_error(command=cmd_hint, version=__version__,
                                  message="No command specified")
            sys.exit(2)
        else:
            parser.print_help()
            sys.exit(2)

    # --- Bare grouped commands → print group help, exit 0 ---
    _grouped_dests: Dict[str, str] = {
        "config": "config_command",
        "provider": "provider_command",
        "profile": "profile_command",
        "skill": "skill_command",
    }
    if args.command in _grouped_dests:
        if getattr(args, _grouped_dests[args.command], None) is None:
            # Bare group — print the group's own help.  Use the actual
            # argparse subparser so that future options stay synchronised
            # across all sub-subcommands.  No JSON envelope; always text
            # help and exit 0.
            try:
                group_choices = [
                    a for a in parser._subparsers._group_actions
                    if a.dest == "command"
                ][0].choices
                group_parser_obj = group_choices.get(args.command)
                if group_parser_obj is not None:
                    group_parser_obj.print_help()
                    sys.exit(0)
            except (AttributeError, IndexError, KeyError):
                pass
            # Fallback (should not be reached)
            parser.print_help()
            sys.exit(0)

    use_color = sys.stdout.isatty() and not getattr(args, "no_color", False)
    aisc_root = getattr(args, "aisc_root", None)
    # Raw-argv resolver may have set this to a valid string; keep it as-is.
    # If the raw-argv resolver set it, argparse.SUPPRESS is irrelevant.
    if aisc_root is argparse.SUPPRESS:
        aisc_root = None

    # Set up JSONL emitter
    emitter: Optional[JsonlEmitter] = None
    if args_events and args.command in ("build", "run"):
        emitter = JsonlEmitter(command=args.command)
    elif args_events and args.command in ("version", "doctor", "config", "provider", "profile",
                                            "status", "stop", "restart", "shell", "switch", "skill"):
        if effective_format == "json":
            emit_json_usage_error(
                command=args.command, version=__version__,
                message=f"--events is not supported for '{args.command}' command",
            )
            sys.exit(2)
        else:
            print(f"Error: --events is not supported for '{args.command}' command",
                  file=sys.stderr)
            sys.exit(2)

    # Execute command
    data: Any = None
    report: Optional[DoctorReport] = None
    exit_code = 0
    errors: List[Dict[str, Any]] = []
    version_info: Optional[VersionInfo] = None

    try:
        if args.command == "version":
            version_info = _cmd_version(args)
            data = version_info.to_dict()
        elif args.command == "doctor":
            data, report = _cmd_doctor(args)
            exit_code = report.exit_code
            if report.error_code:
                errors.append(build_error(report.error_code, report.error_message or ""))
        elif args.command == "build":
            data, exit_code, errors = _cmd_build(args, emitter, effective_format)
        elif args.command == "run":
            data, exit_code, errors = _cmd_run(args, emitter, effective_format, aisc_root)
        elif args.command == "config":
            data, exit_code, errors = _cmd_config(args, effective_format)
        elif args.command == "provider":
            data, exit_code, errors = _cmd_provider(args, effective_format)
        elif args.command == "profile":
            data, exit_code, errors = _cmd_profile(args, effective_format)
        elif args.command == "status":
            data, exit_code, errors = _cmd_status(args, effective_format)
        elif args.command == "stop":
            data, exit_code, errors = _cmd_stop(args, effective_format)
        elif args.command == "restart":
            data, exit_code, errors = _cmd_restart(args, effective_format)
        elif args.command == "shell":
            data, exit_code, errors = _cmd_shell(args, effective_format)
        elif args.command == "switch":
            data, exit_code, errors = _cmd_switch(args, effective_format)
        elif args.command == "ps":
            data, exit_code, errors = _cmd_ps(args, effective_format)
        elif args.command == "skill":
            data, exit_code, errors = _cmd_skill(args, effective_format, aisc_root)
        else:
            if effective_format == "json":
                emit_json_usage_error(
                    command=args.command, version=__version__,
                    message=f"Unknown command: {args.command}",
                )
            else:
                parser.error(f"Unknown command: {args.command}")
            sys.exit(2)
            return

    except CliError as exc:
        # --- unified terminal: main owns the single terminal event ---
        if emitter is not None and not emitter.terminated:
            cmd = args.command or "aisc"
            term_type = f"{cmd}.failed"
            term_data = dict(exc.data or {})
            term_data["exit_code"] = exc.exit_code
            term_data["error_code"] = exc.error_code
            term_data["message"] = exc.message
            emitter.emit(term_type, term_data, terminal=True)
            sys.exit(exc.exit_code)

        # JSON envelope — use exc.data if present
        if effective_format == "json":
            envelope = build_envelope(
                command=args.command,
                exit_code=exc.exit_code,
                version=__version__,
                data=exc.data,  # structured outcome, not null
                errors=[build_error(exc.error_code, exc.message, exc.hint)],
            )
            emit_json(envelope)
        else:
            print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(exc.exit_code)
        return

    except KeyboardInterrupt:
        if emitter is not None and not emitter.terminated:
            cmd = args.command or "aisc"
            emitter.emit(f"{cmd}.cancelled", {"exit_code": 130}, terminal=True)
            sys.exit(130)
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)

    # --- success: terminal event if events mode ---
    if emitter is not None and not emitter.terminated:
        cmd = args.command or "aisc"
        term_data = dict(data or {})
        term_data["exit_code"] = exit_code
        emitter.emit(f"{cmd}.complete", term_data, terminal=True)
        sys.exit(exit_code)

    # Output for non-events mode
    if effective_format == "json":
        envelope = build_envelope(
            command=args.command, exit_code=exit_code,
            version=__version__, data=data, errors=errors,
        )
        emit_json(envelope)
    else:
        if args.command == "version":
            assert version_info is not None
            print(version_info.to_text())
        elif args.command == "doctor":
            assert report is not None
            print_doctor_text(report, use_color=use_color)
        elif args.command in ("build", "run"):
            from aisc.adapters.docker_ import format_argv_display
            if isinstance(data, dict) and data.get("dry_run"):
                label = "Build" if args.command == "build" else "Run"
                print(f"{label} plan (dry-run):")
                argv_list = data.get("docker_argv", [])
                print(f"  docker {format_argv_display(argv_list)}")
            elif isinstance(data, dict) and data.get("executed"):
                if args.command == "build":
                    print(f"Build succeeded: {data.get('image_tag', '')}")
                else:
                    print("Container finished.")
        elif args.command == "config":
            from aisc.cli.commands.config import print_validate_text, print_effective_text
            from aisc.application.config_service import ServiceResult
            sub = getattr(args, "config_command", "validate")
            if sub == "validate":
                sr = ServiceResult(valid=data.get("valid", True), exit_code=exit_code,
                                   error_code=errors[0]["code"] if errors else "",
                                   error_message=errors[0]["message"] if errors else "",
                                   data=data)
                print_validate_text(sr)
            else:
                sr = ServiceResult(valid=data.get("valid", True), exit_code=exit_code,
                                   error_code=errors[0]["code"] if errors else "",
                                   error_message=errors[0]["message"] if errors else "",
                                   data=data)
                print_effective_text(sr)
        elif args.command == "provider":
            from aisc.cli.commands.provider import (
                print_provider_add_text, print_provider_list_text, print_provider_show_text,
            )
            sub = getattr(args, "provider_command", "list")
            if sub == "show":
                print_provider_show_text(data)
            elif sub == "add":
                print_provider_add_text(data)
            else:
                print_provider_list_text(data)
        elif args.command == "profile":
            from aisc.cli.commands.profile import print_profile_list_text, print_profile_show_text
            sub = getattr(args, "profile_command", "list")
            if sub == "show":
                print_profile_show_text(data)
            else:
                print_profile_list_text(data)
        elif args.command == "status":
            from aisc.cli.commands.container import print_status_text, StatusResult
            sr = StatusResult(
                name=data.get("name", ""),
                exists=data.get("exists", False),
                running=data.get("running", False),
                status=data.get("status", ""),
                image=data.get("image", ""),
                container_id=data.get("container_id", ""),
            )
            print_status_text(sr)
        elif args.command == "stop":
            from aisc.cli.commands.container import print_stop_text
            print_stop_text(data if isinstance(data, dict) else {})
        elif args.command == "restart":
            from aisc.cli.commands.container import print_restart_text
            print_restart_text(data if isinstance(data, dict) else {})
        elif args.command == "ps":
            from aisc.cli.commands.container import print_ps_text, PsRow
            ps_rows = [PsRow(
                name=r.get("name", ""), label=r.get("label", ""),
                status=r.get("status", ""), running=r.get("running", False),
                image=r.get("image", ""), workspace=r.get("workspace", ""),
            ) for r in (data if isinstance(data, list) else [])]
            print_ps_text(ps_rows)
        elif args.command in ("shell", "switch", "skill"):
            # interactive output / skill text printed directly by _cmd_*
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
