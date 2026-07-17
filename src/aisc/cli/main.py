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
                    default="direct", help="Network mode: direct or proxy (default: direct)")
    rp.add_argument("--dry-run", action="store_true", default=False,
                    help="Plan the run without executing")

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
    known = {"version", "doctor", "build", "run"}
    for arg in argv:
        if arg in known:
            return arg
    return None


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

    plan = plan_build(
        root=root,
        tag=getattr(args, "tag", "super-claude:latest"),
        no_cache=getattr(args, "no_cache", False),
        pull=getattr(args, "pull", False),
        dry_run=getattr(args, "dry_run", False),
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

    # Locate AISC root for proxy config resolution
    aisc_root = None
    try:
        aisc_root = locate_aisc_root(explicit_root=aisc_root_arg)
    except _RootSourceError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc

    is_interactive = (effective_format == "text" and emitter is None)

    plan = plan_run(
        image=getattr(args, "image", "super-claude:latest"),
        workspace=getattr(args, "workspace", None) or str(Path.cwd()),
        name=getattr(args, "name", "super-claude-station"),
        network=getattr(args, "network", "direct"),
        dry_run=getattr(args, "dry_run", False),
        interactive=is_interactive,
        aisc_root=aisc_root,
    )

    result = run_container(plan, emitter=emitter)
    return result.to_dict(), 0, []


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

    try:
        args = parser.parse_args(args_list)
    except SystemExit:
        raise

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

    use_color = sys.stdout.isatty() and not getattr(args, "no_color", False)
    aisc_root = getattr(args, "aisc_root", None)
    if aisc_root is argparse.SUPPRESS:
        aisc_root = None

    # Set up JSONL emitter
    emitter: Optional[JsonlEmitter] = None
    if args_events and args.command in ("build", "run"):
        emitter = JsonlEmitter(command=args.command)
    elif args_events and args.command in ("version", "doctor"):
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

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
