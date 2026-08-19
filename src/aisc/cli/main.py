"""Main CLI entry point — argument parsing, command dispatch, output formatting.

``aisc version``, ``aisc doctor``, ``aisc build``, and ``aisc run`` commands.
``python -m aisc`` and console_script ``aisc`` are both supported.

All docker operations are injected through a ``DockerExecutor``.
"""

from __future__ import annotations

import argparse
import json
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
from aisc.domain.models import CheckStatus, CliError, DoctorReport, VersionInfo
from aisc.domain.models import SessionAgent
from aisc.domain.models import RuntimeErrorCode
from aisc.domain.artifacts import ArtifactAction, ArtifactKind, ArtifactOpenWith


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
    # Stage 8b (CS-01/CS-02): cc-switch release resolution. `latest` resolves
    # the newest stable upstream release live (fail closed, never a silent
    # pin); an explicit vX.Y.Z is reproducible; --cc-switch-manifest builds
    # fully offline from a previously written resolution receipt.
    bp.add_argument("--cc-switch-version", type=str, default=argparse.SUPPRESS,
                    help="cc-switch version: 'latest' (default) or vX.Y.Z "
                         "(env: CC_SWITCH_VERSION)")
    bp.add_argument("--cc-switch-channel", type=str, default=argparse.SUPPRESS,
                    choices=["stable"],
                    help="cc-switch release channel (default: stable; "
                         "env: CC_SWITCH_CHANNEL)")
    bp.add_argument("--cc-switch-manifest", type=str, default=None, metavar="PATH",
                    help="Build from a resolver manifest file (offline / "
                         "reproducible; skips the live resolve)")

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

    cshow = csub.add_parser("show", help="Alias for 'config effective' (compatibility name)",
                            allow_abbrev=False)
    _add_global_args(cshow, is_subparser=True)
    cshow.add_argument("--config", type=str, default=None,
                       help="Explicit user config file path")
    cshow.add_argument("--workspace", type=str, default=None,
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

    # --- switch ---
    swp = sub.add_parser("switch", help="Switch AI provider in the container", allow_abbrev=False)
    _add_global_args(swp, is_subparser=True)
    swp.add_argument("--name", type=str, default=None,
                     help="Container name (overrides registry discovery)")
    swp.add_argument("--label", type=str, default=None,
                     help="Target container by label")
    swp.add_argument("--quick", type=str, default=None,
                     help="Provider id or alias for quick switch (e.g. deepseek)")

    # --- provider ---
    prp = sub.add_parser("provider", help="Manage AI provider configuration", allow_abbrev=False)
    _add_global_args(prp, is_subparser=True)
    prsub = prp.add_subparsers(dest="provider_command", title="provider commands",
                                parser_class=_AiscArgumentParser)

    prsk = prsub.add_parser(
        "set-key",
        help="Open the secure interactive editor for a provider",
        allow_abbrev=False,
    )
    _add_global_args(prsk, is_subparser=True)
    prsk.add_argument("provider_id", type=str,
                      help="Provider ID (e.g., deepseek, zhipu, kimi)")
    prsk.add_argument("--name", type=str, default=None,
                      help="Container name (overrides registry discovery)")
    prsk.add_argument("--label", type=str, default=None,
                      help="Target container by label")
    prsk.add_argument("--agent", type=str, default="claude",
                      help="Target agent (default: claude)")

    # provider current (Workbench S0.4): non-interactive, --format json
    prpc = prsub.add_parser(
        "current",
        help="Show the current provider status for an agent (Workbench)",
        allow_abbrev=False,
    )
    _add_global_args(prpc, is_subparser=True)
    prpc.add_argument("--runtime-id", type=str, required=True,
                      help="Runtime ID (UUID v4)")
    prpc.add_argument("--agent", type=str, required=True,
                      choices=["claude", "codex"],
                      help="Agent (claude|codex)")
    prpc.add_argument("--workspace", type=str, default=None,
                      help="Workspace path (default: current directory)")

    # --- cc-switch (Stage 8d: provider data plane, aisc.cc-switch-provider/v1) ---
    csp = sub.add_parser(
        "cc-switch", help="Manage cc-switch providers (list/add/edit/delete)",
        allow_abbrev=False,
    )
    _add_global_args(csp, is_subparser=True)
    cssub = csp.add_subparsers(dest="cc_switch_command", title="cc-switch commands",
                               parser_class=_AiscArgumentParser)

    def _cc_switch_common(p):
        _add_global_args(p, is_subparser=True)
        p.add_argument("--runtime-id", type=str, required=True,
                       help="Runtime ID (UUID v4)")
        p.add_argument("--agent", type=str, required=True,
                       choices=["claude", "codex"], help="Agent (claude|codex)")
        p.add_argument("--workspace", type=str, default=None,
                       help="Workspace path (default: current directory)")

    csl = cssub.add_parser("list", help="List providers (secret-free snapshot)",
                           allow_abbrev=False)
    _cc_switch_common(csl)

    csa = cssub.add_parser("add", help="Add a provider (request JSON on stdin)",
                           allow_abbrev=False)
    _cc_switch_common(csa)
    # KI-7①: default None, NOT "simple" — the Workbench never passes --mode,
    # and a truthy argparse default unconditionally clobbered the stdin
    # document's "mode":"custom" (observed as "unknown preset provider").
    csa.add_argument("--mode", choices=["simple", "custom"], default=None,
                     help="simple = preset provider + api key; custom = full "
                          "fields (the stdin request's mode wins unless set)")
    csa.add_argument("--provider", type=str, default=None,
                     help="Preset provider id (simple mode, e.g. deepseek)")
    csa.add_argument("--id", dest="new_id", type=str, default=None,
                     help="Provider id to create (default: preset id / name slug)")

    cse = cssub.add_parser("edit", help="Edit a provider (patch JSON on stdin)",
                           allow_abbrev=False)
    _cc_switch_common(cse)
    cse.add_argument("provider_id", type=str, help="Provider ID to edit")

    css = cssub.add_parser("switch", help="Activate a provider (make it current)",
                           allow_abbrev=False)
    _cc_switch_common(css)
    css.add_argument("provider_id", type=str, help="Provider ID to activate")

    csd = cssub.add_parser("delete", help="Delete a provider", allow_abbrev=False)
    _cc_switch_common(csd)
    csd.add_argument("provider_id", type=str, help="Provider ID to delete")
    csd.add_argument("--confirm", action="store_true", default=False,
                     help="Required confirmation flag")

    # IDEA-5 (5c): remote model list for the mapping dropdown.
    csf = cssub.add_parser("fetch-models",
                           help="Fetch the remote model list for a provider",
                           allow_abbrev=False)
    _cc_switch_common(csf)
    csf.add_argument("provider_id", type=str, help="Provider ID to query")

    # --- network (IDEA-2: mihomo subscription data plane) ---
    nwp = sub.add_parser(
        "network", help="Network management (mihomo subscription for container TUN)",
        allow_abbrev=False,
    )
    _add_global_args(nwp, is_subparser=True)
    nwsub = nwp.add_subparsers(dest="network_command", title="network commands",
                               parser_class=_AiscArgumentParser, required=True)

    nws = nwsub.add_parser(
        "subscription", help="Manage the proxy subscription (IDEA-2)",
        allow_abbrev=False,
    )
    _add_global_args(nws, is_subparser=True)
    nwssub = nws.add_subparsers(dest="subscription_command",
                                title="subscription commands",
                                parser_class=_AiscArgumentParser, required=True)

    nwi = nwssub.add_parser(
        "import", help="Import a subscription (URL on stdin — a credential, "
                       "never argv)", allow_abbrev=False)
    _add_global_args(nwi, is_subparser=True)

    nwif = nwssub.add_parser(
        "import-file", help="Import manually supplied subscription content "
                            "(full content on stdin; fallback for sources "
                            "that reject automated downloads)", allow_abbrev=False)
    _add_global_args(nwif, is_subparser=True)

    nwr = nwssub.add_parser(
        "refresh", help="Re-fetch the stored subscription URL", allow_abbrev=False)
    _add_global_args(nwr, is_subparser=True)

    nww = nwssub.add_parser(
        "show", help="Show subscription status (secret-free)", allow_abbrev=False)
    _add_global_args(nww, is_subparser=True)

    nwc = nwssub.add_parser("clear", help="Remove the stored subscription",
                            allow_abbrev=False)
    _add_global_args(nwc, is_subparser=True)
    nwc.add_argument("--confirm", action="store_true", default=False,
                     help="Required confirmation flag")

    # --- usage (IDEA-2: provider token usage aggregation) ---
    usp = sub.add_parser(
        "usage", help="Provider token usage statistics (all workspaces)",
        allow_abbrev=False,
    )
    _add_global_args(usp, is_subparser=True)
    ussub = usp.add_subparsers(dest="usage_command", title="usage commands",
                               parser_class=_AiscArgumentParser, required=True)
    uso = ussub.add_parser(
        "overview", help="Subscription status + per-provider token usage",
        allow_abbrev=False)
    _add_global_args(uso, is_subparser=True)
    uso.add_argument("--range", dest="range", type=str, default="7d",
                     choices=["today", "7d", "30d"],
                     help="Time window (default: 7d)")
    uso.add_argument("--workspace", type=str, default=None,
                     help="Limit to one workspace path (default: all)")

    # --- ps ---
    psp = sub.add_parser("ps", help="List all registered containers", allow_abbrev=False)
    _add_global_args(psp, is_subparser=True)

    # --- runtime ---
    rtp = sub.add_parser("runtime", help="Runtime control plane (Workbench Phase 0)", allow_abbrev=False)
    _add_global_args(rtp, is_subparser=True)
    rtsub = rtp.add_subparsers(dest="runtime_command", title="runtime commands",
                                parser_class=_AiscArgumentParser)

    rtpf = rtsub.add_parser("preflight", help="Preflight checks for runtime start", allow_abbrev=False)
    _add_global_args(rtpf, is_subparser=True)
    rtpf.add_argument("--runtime-id", type=str, required=True,
                      help="Runtime ID (UUID v4, provided by Workbench)")
    rtpf.add_argument("--workspace", type=str, default=None,
                      help="Workspace path (default: current directory)")
    rtpf.add_argument("--image", type=str, default="super-claude:latest",
                      help="Docker image (default: super-claude:latest)")
    rtpf.add_argument("--network", type=str, choices=["direct", "proxy"],
                      default="direct",
                      help="Network mode (default: direct)")
    rtpf.add_argument("--scope", type=str, choices=["project", "temporary"],
                      default="project",
                      help="Runtime scope (default: project)")
    rtpf.add_argument("--owner", type=str, default="workbench",
                      help="Owner identifier (default: workbench)")

    # --- runtime start ---
    rts = rtsub.add_parser("start", help="Start a Workbench runtime", allow_abbrev=False)
    _add_global_args(rts, is_subparser=True)
    rts.add_argument("--runtime-id", type=str, required=True,
                     help="Runtime ID (UUID v4, provided by Workbench)")
    rts.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")
    rts.add_argument("--image", type=str, default="super-claude:latest",
                     help="Docker image (default: super-claude:latest)")
    rts.add_argument("--network", type=str, choices=["direct", "proxy"],
                     default="direct", help="Network mode (default: direct)")
    rts.add_argument("--scope", type=str, choices=["project", "temporary"],
                     default="project", help="Runtime scope (default: project)")
    rts.add_argument("--owner", type=str, default="workbench",
                     help="Owner identifier (default: workbench)")
    rts.add_argument("--proxy-config", type=str, default=None,
                     help="Host path to mihomo config.yaml to mount for --network proxy "
                          "(S0.2: proxy caps/device are set; without this, TUN runs without a config)")

    # --- runtime list ---
    rtl = rtsub.add_parser("list", help="List runtimes with Docker reconciliation",
                           allow_abbrev=False)
    _add_global_args(rtl, is_subparser=True)
    rtl.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")
    rtl.add_argument("--owner", type=str, default=None,
                     help="Filter by owner (e.g. workbench)")

    # --- runtime inspect ---
    rti = rtsub.add_parser("inspect", help="Show a single runtime", allow_abbrev=False)
    _add_global_args(rti, is_subparser=True)
    rti.add_argument("--runtime-id", type=str, required=True,
                     help="Runtime ID (UUID v4)")
    rti.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")

    # --- runtime stop ---
    rtst = rtsub.add_parser("stop", help="Stop a runtime (keep container + metadata)",
                            allow_abbrev=False)
    _add_global_args(rtst, is_subparser=True)
    rtst.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    rtst.add_argument("--workspace", type=str, default=None,
                      help="Workspace path (default: current directory)")
    rtst.add_argument("--grace", type=int, default=10,
                      help="docker stop grace period in seconds (1..600; default 10)")

    # --- runtime restart ---
    rtr = rtsub.add_parser("restart", help="Restart a runtime with original config",
                           allow_abbrev=False)
    _add_global_args(rtr, is_subparser=True)
    rtr.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    rtr.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")

    # --- runtime remove ---
    rtrm = rtsub.add_parser("remove", help="Remove a runtime (container + registry)",
                            allow_abbrev=False)
    _add_global_args(rtrm, is_subparser=True)
    rtrm.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    rtrm.add_argument("--workspace", type=str, default=None,
                      help="Workspace path (default: current directory)")
    rtrm.add_argument("--force", action="store_true", default=False,
                      help="Remove even if the runtime is running")

    # --- session ---
    ssp = sub.add_parser("session", help="Session data plane (Workbench Phase 0)", allow_abbrev=False)
    _add_global_args(ssp, is_subparser=True)
    ssub = ssp.add_subparsers(dest="session_command", title="session commands",
                              parser_class=_AiscArgumentParser)

    # session open
    sso = ssub.add_parser("open", help="Open an interactive agent session", allow_abbrev=False)
    _add_global_args(sso, is_subparser=True)
    sso.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    sso.add_argument("--session-id", type=str, required=True, help="Session ID (UUID v4)")
    sso.add_argument("--agent", type=str, required=True,
                     choices=list(SessionAgent.ALL),
                     help="Agent type (claude|codex|bash|cc-switch)")
    sso.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")

    # session list
    ssl = ssub.add_parser("list", help="List sessions in a runtime", allow_abbrev=False)
    _add_global_args(ssl, is_subparser=True)
    ssl.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    ssl.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")

    # session terminate
    sst = ssub.add_parser("terminate", help="Terminate a session", allow_abbrev=False)
    _add_global_args(sst, is_subparser=True)
    sst.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    sst.add_argument("--session-id", type=str, required=True, help="Session ID (UUID v4)")
    sst.add_argument("--workspace", type=str, default=None,
                     help="Workspace path (default: current directory)")
    sst.add_argument("--grace", type=float, default=5.0,
                     help="Grace period in seconds before SIGKILL (default: 5.0)")

    # --- artifact (Stage 3, ART-02) ---
    arp = sub.add_parser("artifact", help="Agent Artifact fact protocol (Stage 3)",
                         allow_abbrev=False)
    _add_global_args(arp, is_subparser=True)
    arsub = arp.add_subparsers(dest="artifact_command", title="artifact commands",
                               parser_class=_AiscArgumentParser)

    arrec = arsub.add_parser("record", help="Record an agent artifact fact",
                             allow_abbrev=False)
    _add_global_args(arrec, is_subparser=True)
    arrec.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    arrec.add_argument("--session-id", type=str, required=True, help="Session ID (UUID v4)")
    arrec.add_argument("--agent", type=str, required=True,
                       choices=["claude", "codex", "bash", "cc-switch"],
                       help="Producer agent")
    arrec.add_argument("--path", type=str, required=True,
                       help="Workspace-relative path of the artifact")
    arrec.add_argument("--action", type=str, choices=ArtifactAction.ALL, default="created",
                       help="created|modified|deleted|renamed")
    arrec.add_argument("--kind", type=str, choices=ArtifactKind.ALL, default="deliverable",
                       help="deliverable|source_change|generated_output")
    arrec.add_argument("--media-type", type=str, default=None,
                       help="media type, e.g. text/markdown")
    arrec.add_argument("--label", type=str, default="", help="Human label (<=256 chars)")
    arrec.add_argument("--open-with", type=str, choices=ArtifactOpenWith.ALL,
                       default="preview", help="preview|system|reveal|none")
    arrec.add_argument("--previous-path", type=str, default=None,
                       help="previous relative path (required for renamed)")
    arrec.add_argument("--workspace", type=str, default=None,
                       help="Workspace path (default: current directory)")

    arlist = arsub.add_parser("list", help="List artifact records", allow_abbrev=False)
    _add_global_args(arlist, is_subparser=True)
    arlist.add_argument("--workspace", type=str, default=None,
                        help="Workspace path (default: current directory)")
    arlist.add_argument("--session-id", type=str, default=None,
                        help="Filter by session id")
    arlist.add_argument("--kind", type=str, choices=ArtifactKind.ALL, default=None,
                        help="Filter by kind")

    arinsp = arsub.add_parser("inspect", help="Inspect one artifact by id",
                              allow_abbrev=False)
    _add_global_args(arinsp, is_subparser=True)
    arinsp.add_argument("--artifact-id", type=str, required=True, help="Artifact ID (UUID)")
    arinsp.add_argument("--workspace", type=str, default=None,
                        help="Workspace path (default: current directory)")

    arclear = arsub.add_parser("clear-session", help="Remove a session's registry",
                               allow_abbrev=False)
    _add_global_args(arclear, is_subparser=True)
    arclear.add_argument("--runtime-id", type=str, required=True, help="Runtime ID (UUID v4)")
    arclear.add_argument("--session-id", type=str, required=True, help="Session ID (UUID v4)")
    arclear.add_argument("--workspace", type=str, default=None,
                         help="Workspace path (default: current directory)")

    # --- data-root (Stage 7, 7d) ---
    drp = sub.add_parser("data-root", help="Data root diagnostics and legacy migration",
                         allow_abbrev=False)
    _add_global_args(drp, is_subparser=True)
    drsub = drp.add_subparsers(dest="data_root_command", title="data-root commands",
                               parser_class=_AiscArgumentParser)

    drdoc = drsub.add_parser("doctor", help="Resolve + legacy findings + manifest state",
                             allow_abbrev=False)
    _add_global_args(drdoc, is_subparser=True)
    drdoc.add_argument("--workspace", type=str, default=None,
                       help="Workspace path (default: current directory)")

    drmig = drsub.add_parser("migrate", help="Migrate legacy layout into the data root",
                             allow_abbrev=False)
    _add_global_args(drmig, is_subparser=True)
    drmig.add_argument("--workspace", type=str, default=None,
                       help="Workspace path (default: current directory)")
    drmig.add_argument("--dry-run", action="store_true", default=False,
                       help="Report the plan without touching anything")
    drmig.add_argument("--apply", action="store_true", default=False,
                       help="Execute the migration (default when --dry-run is absent)")
    drmig.add_argument("--quarantine-unknown", action="store_true", default=False,
                       help="Move unknown files to the migration quarantine "
                            "(explicit consent; sources kept)")

    drroll = drsub.add_parser("rollback", help="Undo one migration via its manifest",
                              allow_abbrev=False)
    _add_global_args(drroll, is_subparser=True)
    drroll.add_argument("--workspace", type=str, default=None,
                        help="Workspace path (default: current directory)")
    drroll.add_argument("manifest", nargs="?", default=None,
                        help="Manifest path (default: this workspace's manifest)")

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
    known = {"version", "doctor", "build", "run", "config", "profile",
             "status", "stop", "restart", "shell", "switch", "provider",
             "cc-switch", "network", "usage", "ps", "runtime", "session",
             "artifact", "data-root"}
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


def _cmd_doctor(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], DoctorReport]:
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

    # Check if Docker is missing and offer to install (interactive mode only)
    docker_missing = any(
        c.name == "docker-cli"
        and c.status == CheckStatus.FAIL
        and c.message == "Docker CLI not found"
        for c in report.checks
    )

    interactive_text = (
        effective_format == "text"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    if docker_missing and interactive_text:
        # Interactive mode - offer to install Docker
        from aisc.application.repair import install_docker_interactive

        print("\n" + "=" * 60)
        print("Docker is required but not installed.")
        print("=" * 60)

        success = install_docker_interactive()

        if success:
            print("\n\nRe-running diagnostics...\n")
            # Re-run doctor to check if Docker is now available
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

def _write_cc_switch_manifest(root: Path, resolved: Any) -> Optional[Path]:
    """Write the resolution receipt next to the build outputs (Stage 8b).

    Best-effort: an unwritable cache warns and builds on (the receipt also
    lives in the image labels + BuildResult). Patched in tests to avoid
    touching the real filesystem.

    Location: the shared data-root cache (NOT the aisc bundle dir — a file
    created inside the installed bundle survives the uninstaller's file list
    and trips the NSIS clean-uninstall gate; resolver artifacts belong with
    the resolver's metadata cache anyway)."""
    from aisc.application.data_root import shared_root

    manifest_path = shared_root() / "cache" / "cc-switch" / "last-resolved.json"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        from aisc.application.cc_switch_resolver import resolved_at_now

        manifest_path.write_text(
            json.dumps(resolved.to_manifest(resolved_at=resolved_at_now()), indent=2),
            encoding="utf-8",
        )
        return manifest_path
    except OSError as exc:
        sys.stderr.write(f"⚠️  could not write cc-switch manifest ({exc}); "
                         f"build continues\n")
        return None


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

    # Stage 8b: resolve the cc-switch release BEFORE planning (D8-02 — the
    # Dockerfile only consumes resolved facts, never resolves on its own).
    import platform as _platform
    from aisc.domain.cc_switch_release import ResolveError, normalize_arch
    from aisc.application.cc_switch_resolver import CcSwitchResolver

    cs_version = getattr(args, "cc_switch_version", None) or os.environ.get("CC_SWITCH_VERSION", "latest")
    cs_channel = getattr(args, "cc_switch_channel", None) or os.environ.get("CC_SWITCH_CHANNEL", "stable")
    cs_manifest = getattr(args, "cc_switch_manifest", None)
    try:
        cs_arch = normalize_arch(_platform.machine())
    except ResolveError:
        cs_arch = "x64"  # validated again inside the Dockerfile (arch assert)
    resolver = CcSwitchResolver()
    try:
        resolved = resolver.resolve(
            channel=cs_channel,
            version=cs_version,
            arch=cs_arch,
            libc="musl",
            manifest_path=Path(cs_manifest) if cs_manifest else None,
        )
    except ResolveError as exc:
        raise CliError(message=f"cc-switch release resolution failed: {exc.message}",
                       exit_code=1, error_code=exc.code) from exc

    # Reproducibility receipt: always written next to the build outputs.
    manifest_path = _write_cc_switch_manifest(root, resolved)

    if effective_format == "text" and emitter is None:
        sys.stderr.write(
            f"cc-switch: {resolved.tag} ({resolved.asset_name}, "
            f"sha256 {resolved.asset_sha256[:12]}…, source {resolved.source})\n"
        )
        sys.stderr.flush()

    plan = plan_build(
        root=root,
        tag=tag,
        no_cache=no_cache,
        pull=pull,
        dry_run=dry_run,
        cc_switch=resolved,
    )

    # text mode → streaming (real-time build log); json/events → captured
    is_streaming = (effective_format == "text" and emitter is None)
    result = run_build(
        plan,
        emitter=emitter,
        streaming=is_streaming,
        cc_switch_summary=resolved.to_manifest(),
        cc_switch_manifest_path=str(manifest_path) if manifest_path else "",
    )
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


def _cmd_cc_switch(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc cc-switch`` subcommands (Stage 8d data plane).

    All four ops are non-interactive and support ``--format json``; secrets
    ride the stdin request document, never argv.
    """
    from aisc.cli.commands import cc_switch as cs_cmd

    sub = getattr(args, "cc_switch_command", None)
    if sub == "list":
        data = cs_cmd.cmd_cc_switch_list(args)
    elif sub == "add":
        data = cs_cmd.cmd_cc_switch_add(args)
    elif sub == "edit":
        data = cs_cmd.cmd_cc_switch_edit(args)
    elif sub == "switch":
        data = cs_cmd.cmd_cc_switch_switch(args)
    elif sub == "delete":
        data = cs_cmd.cmd_cc_switch_delete(args)
    elif sub == "fetch-models":
        data = cs_cmd.cmd_cc_switch_fetch_models(args)
    else:
        raise CliError(message="unknown cc-switch subcommand",
                       exit_code=2, error_code="AISC_ERR_USAGE")

    if effective_format == "text":
        cs_cmd.print_cc_switch_text(data)
    return data, 0, []


def _cmd_network(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc network`` subcommands (IDEA-2 subscription data plane).

    Non-interactive, ``--format json`` throughout; the subscription URL rides
    stdin for ``import`` (secrets never ride argv).
    """
    from aisc.cli.commands import network as nw_cmd

    if getattr(args, "network_command", None) != "subscription":
        raise CliError(message="unknown network subcommand",
                       exit_code=2, error_code="AISC_ERR_USAGE")

    sub = getattr(args, "subscription_command", None)
    if sub == "import":
        data = nw_cmd.cmd_network_subscription_import(args)
    elif sub == "import-file":
        data = nw_cmd.cmd_network_subscription_import_file(args)
    elif sub == "refresh":
        data = nw_cmd.cmd_network_subscription_refresh(args)
    elif sub == "show":
        data = nw_cmd.cmd_network_subscription_show(args)
    elif sub == "clear":
        data = nw_cmd.cmd_network_subscription_clear(args)
    else:
        raise CliError(message="unknown network subscription subcommand",
                       exit_code=2, error_code="AISC_ERR_USAGE")

    if effective_format == "text":
        nw_cmd.print_network_subscription_text(data)
    return data, 0, []


def _cmd_usage(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc usage`` subcommands (IDEA-2 usage data plane)."""
    from aisc.cli.commands import usage as usage_cmd

    if getattr(args, "usage_command", None) != "overview":
        raise CliError(message="unknown usage subcommand",
                       exit_code=2, error_code="AISC_ERR_USAGE")
    data = usage_cmd.cmd_usage_overview(args)
    if effective_format == "text":
        usage_cmd.print_usage_overview_text(data)
    return data, 0, []


def _cmd_provider(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Execute ``aisc provider`` subcommands.

    ``current`` is non-interactive and supports ``--format json`` (S0.4).
    ``set-key`` is text-only interactive.
    """
    sub = getattr(args, "provider_command", None)

    if sub == "current":
        from aisc.cli.commands.provider import cmd_provider_current
        data = cmd_provider_current(
            runtime_id=args.runtime_id,
            agent=args.agent,
            workspace=args.workspace,
        )
        return data, 0, []

    # All other provider subcommands are text-only interactive.
    if effective_format == "json":
        emit_json_usage_error(
            command="provider", version=__version__,
            message="provider set-key only supports text output, --format json is not supported",
        )
        sys.exit(2)

    from aisc.cli.commands.container import cmd_provider_set_key, discover_container

    if sub != "set-key":
        print("Error: Unknown provider subcommand. Use 'aisc provider set-key' "
              "or 'aisc provider current'.", file=sys.stderr)
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

    provider_id = getattr(args, "provider_id", None)
    agent = getattr(args, "agent", "claude")

    proc = cmd_provider_set_key(
        name_override=name_override,
        explicit_root=getattr(args, "aisc_root", None),
        provider_id=provider_id,
        agent=agent,
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
        "provider_id": provider_id,
        "agent": agent,
    }
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


def _cmd_runtime(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """Execute ``aisc runtime`` subcommands.  Supports --format json."""
    from aisc.cli.commands.runtime import (
        cmd_runtime_preflight,
        cmd_runtime_start,
        cmd_runtime_list,
        cmd_runtime_inspect,
        cmd_runtime_stop,
        cmd_runtime_restart,
        cmd_runtime_remove,
    )

    sub = args.runtime_command

    if sub == "preflight":
        result = cmd_runtime_preflight(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
            image=args.image,
            network=args.network,
            scope=args.scope,
            owner=args.owner,
            format=effective_format,
        )
        if "error" in result:
            return None, result["exit_code"], [result["error"]]
        return result, 0, []
    elif sub == "start":
        data = cmd_runtime_start(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
            image=args.image,
            network=args.network,
            scope=args.scope,
            owner=args.owner,
            proxy_config=args.proxy_config,
        )
        return data, 0, []
    elif sub == "list":
        data = cmd_runtime_list(
            workspace=args.workspace,
            owner=args.owner,
        )
        return data, 0, []
    elif sub == "inspect":
        data = cmd_runtime_inspect(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
        )
        return data, 0, []
    elif sub == "stop":
        data = cmd_runtime_stop(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
            grace_seconds=args.grace,
        )
        return data, 0, []
    elif sub == "restart":
        data = cmd_runtime_restart(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
        )
        return data, 0, []
    elif sub == "remove":
        data = cmd_runtime_remove(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
            force=args.force,
        )
        return data, 0, []
    else:
        # Unknown runtime subcommand
        return None, 2, [build_error(
            "AISC_ERR_USAGE",
            f"Unknown runtime subcommand: {sub}"
        )]




def _cmd_session(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """Execute ``aisc session`` subcommands.  Supports --format json.

    ``session open`` is interactive: it inherits stdio via ``docker exec -it``
    and returns the agent exit code.  ``session list`` and ``session terminate``
    are non-interactive and return JSON-serializable data.
    """
    from aisc.cli.commands.session import (
        cmd_session_open,
        cmd_session_list,
        cmd_session_terminate,
    )

    sub = args.session_command

    if sub == "open":
        if effective_format == "json":
            emit_json_usage_error(
                command="session", version=__version__,
                message="session open only supports text output, --format json is not supported",
            )
            sys.exit(2)
        data, exit_code = cmd_session_open(
            runtime_id=args.runtime_id,
            session_id=args.session_id,
            agent=args.agent,
            workspace=args.workspace,
        )
        errors: List[Dict[str, Any]] = []
        if exit_code != 0 and data.get("error"):
            errors.append(build_error(
                RuntimeErrorCode.SESSION_FAILED,
                data["error"],
            ))
        return data, exit_code, errors
    elif sub == "list":
        data = cmd_session_list(
            runtime_id=args.runtime_id,
            workspace=args.workspace,
        )
        return data, 0, []
    elif sub == "terminate":
        data = cmd_session_terminate(
            runtime_id=args.runtime_id,
            session_id=args.session_id,
            workspace=args.workspace,
            grace_seconds=args.grace,
        )
        return data, 0, []
    else:
        return None, 2, [build_error(
            "AISC_ERR_USAGE",
            f"Unknown session subcommand: {sub}"
        )]


def _cmd_artifact(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """Execute ``aisc artifact`` subcommands.  Supports --format json.

    ``record``/``list``/``inspect``/``clear-session`` are non-interactive and
    return JSON-serializable data under the aisc.cli/v1 envelope.
    """
    from aisc.cli.commands.artifact import (
        cmd_artifact_record,
        cmd_artifact_list,
        cmd_artifact_inspect,
        cmd_artifact_clear_session,
    )

    sub = args.artifact_command

    if sub == "record":
        data = cmd_artifact_record(
            runtime_id=args.runtime_id,
            session_id=args.session_id,
            agent=args.agent,
            path=args.path,
            action=args.action,
            kind=args.kind,
            media_type=args.media_type,
            label=args.label,
            open_with=args.open_with,
            previous_path=args.previous_path,
            workspace=args.workspace,
        )
        return data, 0, []
    elif sub == "list":
        data = cmd_artifact_list(
            workspace=args.workspace,
            session_id=args.session_id,
            kind=args.kind,
        )
        return data, 0, []
    elif sub == "inspect":
        data = cmd_artifact_inspect(
            artifact_id=args.artifact_id,
            workspace=args.workspace,
        )
        return data, 0, []
    elif sub == "clear-session":
        data = cmd_artifact_clear_session(
            runtime_id=args.runtime_id,
            session_id=args.session_id,
            workspace=args.workspace,
        )
        return data, 0, []
    else:
        return None, 2, [build_error(
            "AISC_ERR_USAGE",
            f"Unknown artifact subcommand: {sub}"
        )]


def _cmd_data_root(
    args: argparse.Namespace,
    effective_format: str,
) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """Execute ``aisc data-root`` subcommands (Stage 7, 7d).

    doctor/migrate --dry-run/migrate --apply/rollback are non-interactive;
    conflicts and unconsented unknowns raise CliError (stable code, non-zero
    exit) instead of guessing.
    """
    from aisc.cli.commands.data_root import (
        cmd_data_root_doctor,
        cmd_data_root_migrate,
        cmd_data_root_rollback,
    )

    sub = args.data_root_command
    if sub == "doctor":
        return cmd_data_root_doctor(workspace=args.workspace), 0, []
    elif sub == "migrate":
        return cmd_data_root_migrate(
            workspace=args.workspace,
            dry_run=args.dry_run,
            quarantine_unknown=args.quarantine_unknown,
        ), 0, []
    # --apply is accepted for explicitness; applying is the default action
    # when --dry-run is absent (03-ux-flow contract spelling).
    elif sub == "rollback":
        return cmd_data_root_rollback(
            workspace=args.workspace, manifest=args.manifest,
        ), 0, []
    return None, 2, [build_error(
        "AISC_ERR_USAGE",
        f"Unknown data-root subcommand: {sub}"
    )]

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:
    """Main CLI entry point."""
    # Never let stdout's locale encoding (GBK on zh-CN Windows, cp1252 on
    # en-US) crash the CLI with UnicodeEncodeError. Protocol JSON is pure
    # ASCII by construction (ensure_ascii=True in emit_json/JsonlEmitter);
    # any other unencodable output (wizard emoji, non-ASCII messages)
    # degrades to '?' instead of aborting mid-command.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass  # non-TextIOWrapper (PyInstaller wrapper) - protocol sites are ASCII anyway
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

    # Propagate json format to profile subparser for unknown-subcommand errors
    if "profile" in args_list:
        try:
            pf_parser = [a for a in parser._subparsers._group_actions
                          if a.dest == "command"][0].choices["profile"]
            pf_parser._aisc_format = "json" if json_requested else None
            pf_parser._aisc_command = "profile"
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate JSON format to provider subparser for parse-time errors.
    if "provider" in args_list:
        try:
            provider_parser = [a for a in parser._subparsers._group_actions
                               if a.dest == "command"][0].choices["provider"]
            provider_parser._aisc_format = "json" if json_requested else None
            provider_parser._aisc_command = "provider"
            # Also propagate to provider current subparser (S0.4, supports --format json)
            if "current" in args_list:
                try:
                    current_parser = [a for a in provider_parser._subparsers._group_actions
                                      if a.dest == "provider_command"][0].choices["current"]
                    current_parser._aisc_format = "json" if json_requested else None
                    current_parser._aisc_command = "provider current"
                except (AttributeError, IndexError, KeyError):
                    pass
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate JSON format to runtime subparser for parse-time errors.
    if "runtime" in args_list:
        try:
            runtime_parser = [a for a in parser._subparsers._group_actions
                              if a.dest == "command"][0].choices["runtime"]
            runtime_parser._aisc_format = "json" if json_requested else None
            runtime_parser._aisc_command = "runtime"

            # Also propagate to every runtime sub-subparser (CLI-A02/A05: any
            # command that supports --format json must emit a JSON usage error,
            # not fall back to argparse text — matches the session propagation).
            for _sub in ("preflight", "start", "list", "inspect", "stop",
                         "restart", "remove"):
                if _sub in args_list:
                    try:
                        _sp = [a for a in runtime_parser._subparsers._group_actions
                               if a.dest == "runtime_command"][0].choices[_sub]
                        _sp._aisc_format = "json" if json_requested else None
                        _sp._aisc_command = f"runtime {_sub}"
                    except (AttributeError, IndexError, KeyError):
                        pass
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate JSON format to session subparser for parse-time errors.
    if "session" in args_list:
        try:
            session_parser = [a for a in parser._subparsers._group_actions
                              if a.dest == "command"][0].choices["session"]
            session_parser._aisc_format = "json" if json_requested else None
            session_parser._aisc_command = "session"
            # Also propagate to session sub-subparsers (list/terminate support --format json).
            for _sub in ("open", "list", "terminate"):
                if _sub in args_list:
                    try:
                        _sp = [a for a in session_parser._subparsers._group_actions
                               if a.dest == "session_command"][0].choices[_sub]
                        _sp._aisc_format = "json" if json_requested else None
                        _sp._aisc_command = f"session {_sub}"
                    except (AttributeError, IndexError, KeyError):
                        pass
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate JSON format to artifact subparser for parse-time errors.
    if "artifact" in args_list:
        try:
            artifact_parser = [a for a in parser._subparsers._group_actions
                               if a.dest == "command"][0].choices["artifact"]
            artifact_parser._aisc_format = "json" if json_requested else None
            artifact_parser._aisc_command = "artifact"
            for _sub in ("record", "list", "inspect", "clear-session"):
                if _sub in args_list:
                    try:
                        _sp = [a for a in artifact_parser._subparsers._group_actions
                               if a.dest == "artifact_command"][0].choices[_sub]
                        _sp._aisc_format = "json" if json_requested else None
                        _sp._aisc_command = f"artifact {_sub}"
                    except (AttributeError, IndexError, KeyError):
                        pass
        except (AttributeError, IndexError, KeyError):
            pass

    # Propagate JSON format to data-root subparser for parse-time errors.
    if "data-root" in args_list:
        try:
            data_root_parser = [a for a in parser._subparsers._group_actions
                                if a.dest == "command"][0].choices["data-root"]
            data_root_parser._aisc_format = "json" if json_requested else None
            data_root_parser._aisc_command = "data-root"
            for _sub in ("doctor", "migrate", "rollback"):
                if _sub in args_list:
                    try:
                        _sp = [a for a in data_root_parser._subparsers._group_actions
                               if a.dest == "data_root_command"][0].choices[_sub]
                        _sp._aisc_format = "json" if json_requested else None
                        _sp._aisc_command = f"data-root {_sub}"
                    except (AttributeError, IndexError, KeyError):
                        pass
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
        "profile": "profile_command",
        "provider": "provider_command",
        "runtime": "runtime_command",
        "session": "session_command",
        "artifact": "artifact_command",
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
    elif args_events and args.command in ("version", "doctor", "config", "profile",
                                           "status", "stop", "restart", "shell", "switch",
                                           "provider", "ps", "session", "artifact",
                                           "data-root"):
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
            data, report = _cmd_doctor(args, effective_format)
            exit_code = report.exit_code
            if report.error_code:
                errors.append(build_error(report.error_code, report.error_message or ""))
        elif args.command == "build":
            data, exit_code, errors = _cmd_build(args, emitter, effective_format)
        elif args.command == "run":
            data, exit_code, errors = _cmd_run(args, emitter, effective_format, aisc_root)
        elif args.command == "config":
            data, exit_code, errors = _cmd_config(args, effective_format)
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
        elif args.command == "provider":
            data, exit_code, errors = _cmd_provider(args, effective_format)
        elif args.command == "cc-switch":
            data, exit_code, errors = _cmd_cc_switch(args, effective_format)
        elif args.command == "network":
            data, exit_code, errors = _cmd_network(args, effective_format)
        elif args.command == "usage":
            data, exit_code, errors = _cmd_usage(args, effective_format)
        elif args.command == "ps":
            data, exit_code, errors = _cmd_ps(args, effective_format)
        elif args.command == "runtime":
            data, exit_code, errors = _cmd_runtime(args, effective_format)
        elif args.command == "session":
            data, exit_code, errors = _cmd_session(args, effective_format)
        elif args.command == "artifact":
            data, exit_code, errors = _cmd_artifact(args, effective_format)
        elif args.command == "data-root":
            data, exit_code, errors = _cmd_data_root(args, effective_format)
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
        elif args.command == "data-root":
            from aisc.cli.commands.data_root import print_data_root_text
            print_data_root_text(data)
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
        elif args.command in ("shell", "switch"):
            # interactive output printed directly by _cmd_*
            pass
        elif args.command == "provider":
            if getattr(args, "provider_command", "") == "current":
                from aisc.cli.commands.provider import print_provider_current_text
                print_provider_current_text(data)
            # set-key: interactive, output already printed by _cmd_*
        elif args.command == "runtime":
            from aisc.cli.commands.runtime import print_runtime_text
            print_runtime_text(getattr(args, "runtime_command", ""), data, errors)
        elif args.command == "session":
            from aisc.cli.commands.session import print_session_text
            print_session_text(getattr(args, "session_command", ""), data, errors)
        elif args.command == "artifact":
            from aisc.cli.commands.artifact import print_artifact_text
            print_artifact_text(getattr(args, "artifact_command", ""), data, errors)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
