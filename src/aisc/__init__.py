"""AISC CLI — Super Claude workstation management."""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path


def _read_version() -> str:
    """Resolve the project version from the canonical ``VERSION`` file."""
    candidates = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "VERSION")

    candidates.extend(
        (
            Path(__file__).with_name("VERSION"),
            Path(__file__).resolve().parents[2] / "VERSION",
            Path(sys.prefix) / "aisc" / "VERSION",
            Path(sys.executable).resolve().parent / "aisc-bundle" / "VERSION",
        )
    )

    for version_file in candidates:
        try:
            version = version_file.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        if version:
            return version

    try:
        return metadata.version("aisc")
    except metadata.PackageNotFoundError:
        return "0+unknown"


__version__ = _read_version()
