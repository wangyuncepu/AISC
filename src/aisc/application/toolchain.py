"""Persistent toolchain host-side lifecycle (runtime-lifecycle-ux 3a).

prepare/mount/metadata for the project-scope persistent toolchain
(host_bind backend, per the Windows spike decision). The toolchain root is
the frozen data-root layout's sibling of the runtime state dir:

    <data-root>/workspaces/<hash>/toolchain/{bin,npm-global,python,cargo,cache}

The environment baseline marker is seeded host-side once (never
overwritten — the entrypoint merges container-side facts); a mismatch
writes a warning file that runtime inspect surfaces as a NON-blocking
warning (D-RUNTIME-11: no manifest, no gate).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.toolchain import (
    ENVIRONMENT_MARKER,
    TOOLCHAIN_SUBDIRS,
    TOOLCHAIN_WARNING_FILE,
    base_environment_marker,
    toolchain_bind_argv,
)

import aisc


def toolchain_dir_for(workspace_dir: Path) -> Path:
    """Toolchain root for a resolved data-root workspace dir
    (``workspaces/<hash>/toolchain`` — sibling of the state subdirs)."""
    return workspace_dir / "toolchain"


def prepare_toolchain(
    workspace_dir: Path,
    *,
    image_id: str = "",
) -> Path:
    """Idempotently create the toolchain skeleton + seed the environment
    marker (only when absent — never overwrite an existing baseline)."""
    root = toolchain_dir_for(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    for sub in TOOLCHAIN_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    marker = root / ENVIRONMENT_MARKER
    if not marker.exists():
        version = getattr(aisc, "__version__", "") or "dev"
        payload = base_environment_marker(
            source_version=version,
            image_id=image_id,
            written_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        tmp = marker.with_name(marker.name + ".tmp")
        tmp.write_text(
            __import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(marker)
    return root


def toolchain_mount_argv(workspace_dir: Path) -> List[str]:
    """-v argv for the persistent toolchain mount (host_bind)."""
    return toolchain_bind_argv(str(toolchain_dir_for(workspace_dir)).replace("\\", "/"))


def toolchain_health(workspace_dir: Path) -> Dict[str, Any]:
    """Inspect-time toolchain summary (02 §8.4 shape, host_bind view).

    ``compatibility`` is ``warning`` when the entrypoint wrote the mismatch
    file, ``unknown`` when no marker exists, else ``compatible``. Never a
    block; no secrets (paths/ids only).
    """
    root = toolchain_dir_for(workspace_dir)
    marker = root / ENVIRONMENT_MARKER
    warning = root / TOOLCHAIN_WARNING_FILE
    if warning.exists():
        compatibility = "warning"
    elif marker.exists():
        compatibility = "compatible"
    else:
        compatibility = "unknown"
    return {
        "mounted": root.exists(),
        "storage": "host_bind",
        "path": str(root),
        "compatibility": compatibility,
    }
