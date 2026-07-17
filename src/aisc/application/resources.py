"""Resource location — find the AISC root directory.

Priority:
  1. Explicit ``--aisc-root`` / *explicit_root* parameter
  2. Environment variable ``AISC_ROOT``
  3. Frozen executable: adjacent ``aisc-bundle/`` directory
     (bundle missing → continue to repo discovery; bundle corrupt → raise)
  4. Walk up from *cwd* discovering a repo (``.git`` + structure markers)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Optional, List


# ---------------------------------------------------------------------------
# Structure markers
# ---------------------------------------------------------------------------

_STRUCTURE_MARKERS: List[str] = [
    "VERSION",
    "container/Dockerfile",
    "config/versions.env",
]


def _is_root(path: Path) -> bool:
    for marker in _STRUCTURE_MARKERS:
        if not (path / marker).is_file():
            return False
    return True


def _has_git(path: Path) -> bool:
    return (path / ".git").exists()


def _find_repo_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    while True:
        if _has_git(current) and _is_root(current):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


# ---------------------------------------------------------------------------
# Lightweight error-info helper
# ---------------------------------------------------------------------------

class _RootSourceError(Exception):
    """Indicates a root source is invalid.  Carries the source label."""

    def __init__(self, message: str, source: str) -> None:
        super().__init__(message)
        self.source = source  # "--aisc-root", "AISC_ROOT", "frozen-bundle"
        self.message = message  # duplicate for clarity


# ---------------------------------------------------------------------------
# Frozen helper (reads nothing — fully parametric)
# ---------------------------------------------------------------------------

def _resolve_frozen_bundle(exe_path: str) -> Optional[Path]:
    """Look for an adjacent ``aisc-bundle/`` relative to *exe_path*.

    Returns the bundle path if valid, ``None`` when absent,
    raises ``_RootSourceError`` when the bundle exists but is corrupt.
    """
    exe_dir = Path(exe_path).resolve().parent
    bundle = exe_dir / "aisc-bundle"
    if not bundle.is_dir():
        return None
    if not _is_root(bundle):
        raise _RootSourceError(
            f"Frozen bundle at {bundle} is corrupt: missing structure markers",
            source="frozen-bundle",
        )
    return bundle


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def locate_aisc_root(
    explicit_root: Optional[str] = None,
    cwd: Optional[Path] = None,
    is_frozen: Optional[Callable[[], bool]] = None,
    executable_path: Optional[str] = None,
) -> Optional[Path]:
    """Find the AISC root directory.

    Parameters
    ----------
    explicit_root:
        Explicit path supplied via ``--aisc-root``.
    cwd:
        Starting directory for repo discovery.  Defaults to ``os.getcwd()``.
    is_frozen:
        Callable that returns ``True`` when we are a frozen executable.
        Default: ``getattr(sys, 'frozen', False)`` (lazy, at call time).
    executable_path:
        Path to the executable when frozen.  Default: ``sys.executable``.

    Returns
    -------
    Path
        The AISC root, or ``None`` if no root could be located.

    Raises
    ------
    _RootSourceError
        When an explicit/bundle/env source is provided but invalid.
        The ``source`` attribute distinguishes the origin.
    """
    # -- 1. Explicit --
    if explicit_root is not None:
        p = Path(explicit_root).resolve()
        if not p.is_dir():
            raise _RootSourceError(
                f"--aisc-root {explicit_root}: not a directory",
                source="--aisc-root",
            )
        if not _is_root(p):
            raise _RootSourceError(
                f"--aisc-root {explicit_root}: missing required structure markers",
                source="--aisc-root",
            )
        return p

    # -- 2. Environment variable --
    env_root = os.environ.get("AISC_ROOT")
    if env_root is not None:
        p = Path(env_root).resolve()
        if not p.is_dir():
            raise _RootSourceError(
                f"AISC_ROOT={env_root}: not a directory",
                source="AISC_ROOT",
            )
        if not _is_root(p):
            raise _RootSourceError(
                f"AISC_ROOT={env_root}: missing required structure markers",
                source="AISC_ROOT",
            )
        return p

    # -- 3. Frozen bundle --
    # Production defaults: lazy-read sys at call time (not at import)
    frozen_check = is_frozen if is_frozen is not None else (
        lambda: getattr(sys, "frozen", False)
    )
    if frozen_check():
        exe = executable_path if executable_path is not None else sys.executable
        if exe:
            bundle = _resolve_frozen_bundle(exe)
            if bundle is not None:
                return bundle
        # Bundle not found → fall through to repo discovery

    # -- 4. Repo discovery --
    start = cwd if cwd is not None else Path.cwd()
    return _find_repo_root(start)
