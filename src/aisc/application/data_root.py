"""DataRootResolver — the only producer of the AISC data root (Stage 7, 7a).

Mirrors the branch style of ``application/artifact.py::data_root()`` (the
Stage-3 precedent this generalizes) with the Stage-7 contract layered on top
(D7-01/02/04/05):

- default root: ``%LOCALAPPDATA%\\AISC\\data`` on Windows, XDG data elsewhere
  (Python CLI/container stay cross-platform per D-24);
- ``AISC_DATA_ROOT`` is an explicit dev/test/enterprise override only: it must
  be absolute and must not overlap the workspace (fail closed — never fall
  back to polluting the workspace);
- every existing path segment of the root is checked for reparse
  points/symlinks (junction escapes, OneDrive placeholders) before use;
- ``resolve`` is READ-ONLY (lifecycle contract): it builds the structured
  ``ResolvedDataRoot`` and reports writability; directory creation is
  ``prepare`` (7b), never here.

Stable error codes: AISC_ERR_DATA_ROOT_OVERRIDE_RELATIVE,
AISC_ERR_DATA_ROOT_REPARSE_POINT, AISC_ERR_DATA_ROOT_WORKSPACE_OVERLAP.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping, Optional

from aisc.domain.data_root import (
    DATA_ROOT_PROTOCOL,
    DATA_ROOT_SCHEMA_VERSION,
    SHARED_SUBDIRS,
    WORKSPACE_SUBDIRS,
    ResolvedDataRoot,
    workspace_dir_name,
    workspace_hash_v1,
)
from aisc.domain.models import CliError

ENV_OVERRIDE = "AISC_DATA_ROOT"

# Stable error codes (exit 1 — no dedicated exit-code registry entry yet).
ERR_OVERRIDE_RELATIVE = "AISC_ERR_DATA_ROOT_OVERRIDE_RELATIVE"
ERR_REPARSE_POINT = "AISC_ERR_DATA_ROOT_REPARSE_POINT"
ERR_WORKSPACE_OVERLAP = "AISC_ERR_DATA_ROOT_WORKSPACE_OVERLAP"

# windows.h FILE_ATTRIBUTE_REPARSE_POINT (symlinks, junctions, OneDrive
# placeholders, app-exec links — any tag, per D7-04 fail-closed).
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _default_root(env: Mapping[str, str], is_windows: bool) -> Path:
    """Platform default, injectable for tests (no os.environ/os.name reads)."""
    if is_windows:
        base = env.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "AISC" / "data"
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "aisc" / "data"
    return Path.home() / ".local" / "share" / "aisc" / "data"


def _is_reparse_point(path: Path) -> bool:
    """True if the path itself (not its target) is a reparse point/symlink."""
    try:
        st = os.lstat(path)
    except OSError:
        return False  # non-existent segments are fine (created by prepare)
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _nearest_existing(path: Path) -> Optional[Path]:
    """Deepest existing ancestor-or-self of *path* (None if even the drive is
    missing — the writability probe is skipped then)."""
    cur = path
    while True:
        if cur.exists():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


class DataRootResolver:
    """Resolves (and validates, but never creates) the canonical data root."""

    def __init__(self, env: Optional[Mapping[str, str]] = None) -> None:
        # ``env`` injection keeps resolver tests hermetic; production callers
        # use the process environment (test_artifact_contract.py precedent).
        self._env = os.environ if env is None else env

    def resolve(self, workspace: Path) -> ResolvedDataRoot:
        ws = Path(workspace)
        root, origin = self._select_root(ws)

        self._check_overlap(root, ws)
        self._check_reparse_segments(root)

        ws_hash = workspace_hash_v1(ws)
        shared = {name: root / name for name in SHARED_SUBDIRS}
        ws_root_dir = shared["workspaces"] / workspace_dir_name(ws_hash)
        return ResolvedDataRoot(
            schema=DATA_ROOT_PROTOCOL,
            schema_version=DATA_ROOT_SCHEMA_VERSION,
            root=root,
            origin=origin,
            workspace_hash=ws_hash,
            writable=self._probe_writable(root),
            shared_dirs=shared,
            workspace_dirs={name: ws_root_dir / name for name in WORKSPACE_SUBDIRS},
        )

    # -- root selection ---------------------------------------------------

    def _select_root(self, workspace: Path) -> tuple[Path, str]:
        override = self._env.get(ENV_OVERRIDE, "")
        if override:
            # Whitespace edges are a misconfiguration, not something to strip
            # silently (domain/config.py::_validate_absolute_root precedent).
            if override != override.strip():
                raise CliError(
                    f"{ENV_OVERRIDE} has leading/trailing whitespace: {override!r}",
                    exit_code=1,
                    error_code=ERR_OVERRIDE_RELATIVE,
                )
            if not Path(override).is_absolute():
                raise CliError(
                    f"{ENV_OVERRIDE} must be an absolute path: {override!r}",
                    exit_code=1,
                    error_code=ERR_OVERRIDE_RELATIVE,
                    hint="Use an absolute path, or unset the variable to use "
                         f"the platform default ({ENV_OVERRIDE} is a "
                         "dev/test/enterprise override).",
                )
            return Path(override), "env"
        return _default_root(self._env, os.name == "nt"), "default"

    # -- containment (fail closed, D7-04) ---------------------------------

    def _check_overlap(self, root: Path, workspace: Path) -> None:
        """The data root and the workspace must be disjoint subtrees: a root
        inside the workspace recreates DATA-01 pollution; a workspace inside
        the root lets migration/quarantine touch user files."""
        try:
            root_rel = root.resolve().relative_to(workspace.resolve())
        except ValueError:
            root_rel = None
        try:
            ws_rel = workspace.resolve().relative_to(root.resolve())
        except ValueError:
            ws_rel = None
        if root_rel is not None or ws_rel is not None:
            which = "inside the workspace" if root_rel is not None else "contains the workspace"
            raise CliError(
                f"data root {which}: {root}",
                exit_code=1,
                error_code=ERR_WORKSPACE_OVERLAP,
                hint=f"{ENV_OVERRIDE} must not overlap the opened workspace; "
                     "pick a directory outside it.",
            )

    def _check_reparse_segments(self, root: Path) -> None:
        """Reject reparse points on any EXISTING segment of the root path
        (01-risk-analysis: junction/symlink escapes → arbitrary paths)."""
        cur = root
        while True:
            if _is_reparse_point(cur):
                raise CliError(
                    f"data root path component is a reparse point/symlink: {cur}",
                    exit_code=1,
                    error_code=ERR_REPARSE_POINT,
                    hint="Point the data root at a real directory (not a "
                         "junction/symlink/OneDrive placeholder).",
                )
            parent = cur.parent
            if parent == cur:
                return
            cur = parent

    # -- writability (informational; prepare fails closed on real writes) --

    def _probe_writable(self, root: Path) -> bool:
        probe = _nearest_existing(root)
        if probe is None:
            return False
        return os.access(probe, os.W_OK)
