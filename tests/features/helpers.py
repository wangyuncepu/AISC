"""Shared helpers for feature / characterization tests.

Keeps test files DRY without polluting the harness layer.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional


# Resolve repo root relative to this file (tests/features/helpers.py → repo root)
_REPO_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


def repo_root() -> str:
    """Absolute path to the repository root."""
    return _REPO_ROOT


# ---------------------------------------------------------------------------
# Temp project skeleton
# ---------------------------------------------------------------------------

class TempProject:
    """Create an isolated mini repo skeleton in a temp directory.

    Copies the real scripts under test into ``{tmpdir}/scripts/`` so they can
    be sourced / executed without touching the real ``.aisc/`` or ``.deploy/``.
    """

    def __init__(self, *, scripts: tuple = ()) -> None:
        """*scripts*: names of scripts to copy from the real ``scripts/`` dir."""
        self.tmpdir: str = tempfile.mkdtemp(prefix="aisc_test_")
        self.scripts_dir: str = os.path.join(self.tmpdir, "scripts")
        os.makedirs(self.scripts_dir, exist_ok=True)

        real_scripts = os.path.join(_REPO_ROOT, "scripts")
        for name in scripts:
            src = os.path.join(real_scripts, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(self.scripts_dir, name))

    def destroy(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def path(self, *parts: str) -> str:
        return os.path.join(self.tmpdir, *parts)


# ---------------------------------------------------------------------------
# Fake docker
# ---------------------------------------------------------------------------

FAKE_DOCKER_TEMPLATE = r"""#!/usr/bin/env bash
# Fake docker for AISC testing — logs all invocations with argv boundaries.
# Behaviours controlled by env vars:
#   DOCKER_IMAGE_EXISTS=1   → 'docker image inspect' succeeds (exit 0)
#   DOCKER_EXIT_CODE=N      → exit code for 'docker run' / 'docker build' (default 0)
set -uo pipefail

_trace_file="${DOCKER_TRACE_FILE:-/dev/null}"

# --- Structured invocation record (preserves argv boundaries) ---
{
  printf 'INVOKE-BEGIN\n'
  for _a in "$@"; do
    printf 'ARG %q\n' "$_a"
  done
  _sub="${1:-}"
  printf 'INVOKE-END %s\n' "$_sub"
} >> "$_trace_file"

case "${1:-}" in
  image)
    if [ "${DOCKER_IMAGE_EXISTS:-0}" = "1" ]; then exit 0; else exit 1; fi
    ;;
  build)
    echo "BUILD_ARGS: $*" >> "$_trace_file"
    exit "${DOCKER_EXIT_CODE:-0}"
    ;;
  run)
    echo "RUN_ARGS: $*" >> "$_trace_file"
    exit "${DOCKER_EXIT_CODE:-0}"
    ;;
  ps|rm|rmi)
    exit 0
    ;;
  *)
    exit "${DOCKER_EXIT_CODE:-0}"
    ;;
esac
"""


def install_fake_docker(bindir: str, trace_file: str) -> str:
    """Write a fake ``docker`` script into *bindir* and return its path.

    The fake logs every invocation to *trace_file* and returns exit codes
    controlled by ``DOCKER_IMAGE_EXISTS`` / ``DOCKER_EXIT_CODE`` env vars.
    """
    docker_path = os.path.join(bindir, "docker")
    with open(docker_path, "w") as fh:
        fh.write(FAKE_DOCKER_TEMPLATE)
    os.chmod(docker_path, 0o755)
    return docker_path


# ---------------------------------------------------------------------------
# Structured trace parser
# ---------------------------------------------------------------------------

class _Invocation:
    """Single docker invocation parsed from the structured trace."""
    __slots__ = ("subcommand", "args")
    def __init__(self, subcommand: str, args: List[str]) -> None:
        self.subcommand = subcommand
        self.args = args


def parse_docker_trace(text: str) -> List[_Invocation]:
    """Parse the structured fake-docker trace into a list of invocations.

    Each invocation block::

        INVOKE-BEGIN
        ARG <bash-%q-quoted arg>
        ...
        INVOKE-END <subcommand>

    Returns a list of ``_Invocation`` objects with ``.subcommand`` and
    ``.args`` (list of unquoted strings).
    """
    invocations: List[_Invocation] = []
    current_args: List[str] = []
    in_block = False

    for line in text.splitlines():
        line = line.rstrip("\n")
        if in_block:
            m_arg = re.match(r"^ARG (.*)$", line)
            m_end = re.match(r"^INVOKE-END (\S+)$", line)
            if m_arg:
                raw = m_arg.group(1)
                # bash %q produces single-quoted strings for safe values,
                # and $'...' for strings with special chars.
                # Use bash to eval each ARG back to its literal value.
                current_args.append(_bash_unquote(raw))
            elif m_end:
                invocations.append(_Invocation(m_end.group(1), current_args))
                current_args = []
                in_block = False
        else:
            if line == "INVOKE-BEGIN":
                in_block = True
    return invocations


def _bash_unquote(raw: str) -> str:
    """Reverse bash ``%q`` quoting back to the literal string.

    Uses ``bash -c 'eval "v=$1"; printf %s "$v"'`` which lets bash's own
    parser undo the ``%q`` escaping.  The value is passed as a positional
    parameter (``$1``) to avoid injection through the ``-c`` script text.
    """
    import subprocess as _sp
    try:
        proc = _sp.run(
            ["bash", "-c", 'eval "v=$1"; printf %s "$v"', "_", raw],
            capture_output=True, text=True, timeout=5,
        )
        return proc.stdout
    except Exception:
        return raw


def find_invocation(invocations: List[_Invocation], subcommand: str) -> Optional[_Invocation]:
    """Return the first invocation whose subcommand matches."""
    for inv in invocations:
        if inv.subcommand == subcommand:
            return inv
    return None
