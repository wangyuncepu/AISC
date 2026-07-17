"""Version information gathering.

Reads ``VERSION`` and ``config/versions.env`` when a root is available;
returns ``None`` for fields that depend on the repo when no root is found.

RFCDirection: always output 6 fixed keys:
  cli_version, bundle_version, contract_version, image_version,
  claude_version, python_version

Unknown values are ``None`` (serialized as ``null`` in JSON).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from aisc import __version__
from aisc.domain.models import VersionInfo
from aisc.application.resources import locate_aisc_root, _RootSourceError


def _read_version_file(root: Path) -> Optional[str]:
    """Read the first non-empty line of ``VERSION`` in *root*."""
    version_file = root / "VERSION"
    if not version_file.is_file():
        return None
    text = version_file.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return text


def _parse_versions_env(root: Path) -> dict:
    """Parse ``config/versions.env`` returning a dict of KEY->value.

    Strips inline comments (``# ...``).
    """
    env_file = root / "config" / "versions.env"
    if not env_file.is_file():
        return {}
    result: dict = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].rstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def gather_version_info(
    explicit_root: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> VersionInfo:
    """Assemble ``VersionInfo`` from the environment.

    Parameters
    ----------
    explicit_root:
        Explicit path via ``--aisc-root``.
    cwd:
        Working directory for repo discovery.

    Returns
    -------
    VersionInfo
        Always contains all fields; root-dependent fields are ``None``
        when no root is found.

    Raises
    ------
    _RootSourceError
        When *explicit_root* is invalid.
    """
    python_version = (sys.version.split()[0] if hasattr(sys, "version")
                      else sys.version)

    root = None
    bundle_version = None
    declared_claude_version = None

    try:
        found = locate_aisc_root(explicit_root=explicit_root, cwd=cwd)
    except _RootSourceError:
        raise
    except Exception:
        raise
    else:
        root = found

    if root is not None:
        bundle_version = _read_version_file(root)
        env = _parse_versions_env(root)
        declared_claude_version = env.get("CLAUDE_CODE_VERSION")

    # Always return 6 fixed keys per RFC; unknown → None
    return VersionInfo(
        cli_version=__version__,
        python_version=python_version,
        bundle_version=bundle_version,
        declared_claude_version=declared_claude_version,
        image_version=None,
        contract_version=None,
    )
