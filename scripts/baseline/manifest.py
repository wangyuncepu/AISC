"""BaselineManifest construction and content-addressed fixture hashing.

The manifest is deterministic: two builds from the same checkout/environment
differ only in ``generated_at`` (B-A01). It never records secrets — only the
explicitly allowlisted environment variables passed in by the caller.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional


SCHEMA_VERSION = 1


def hash_file(path: Path) -> str:
    """Return a ``sha256:<hex>`` content address for *path* (binary-safe)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def fixture_hashes(fixture_dir: Optional[Path]) -> Dict[str, str]:
    """Recursively hash files under *fixture_dir* as ``{rel_posix_path: sha256}``.

    Directory traversal is sorted so the result is deterministic across runs.
    Empty directories are not represented.
    """
    if fixture_dir is None or not fixture_dir.is_dir():
        return {}

    result: Dict[str, str] = {}
    for root, dirs, files in os.walk(fixture_dir):
        dirs.sort()
        for name in sorted(files):
            path = Path(root) / name
            rel = path.relative_to(fixture_dir).as_posix()
            result[rel] = hash_file(path)
    return result


def build_manifest(
    *,
    git_commit: Optional[str],
    git_branch: Optional[str],
    os_name: str,
    os_arch: Optional[str],
    os_release: Optional[str],
    toolchain: Dict[str, Dict[str, Optional[str]]],
    commands: List[str],
    env_allowlist: Dict[str, Optional[str]],
    fixture_hashes: Dict[str, str],
    probe_status: str,
    generated_at: Optional[str] = None,
) -> Dict[str, object]:
    """Build a single deterministic ``BaselineManifest`` dict.

    ``generated_at`` is the only field expected to vary between identical runs.
    ``env_allowlist`` must already contain only allowlisted keys.
    """
    from datetime import datetime, timezone

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "probe_status": probe_status,
        "git": {"commit": git_commit, "branch": git_branch},
        "os": {"name": os_name, "arch": os_arch, "release": os_release},
        "toolchain": toolchain,
        "commands": commands,
        "env_allowlist": env_allowlist,
        "fixture_hashes": fixture_hashes,
    }


def toolchain_payload(tools) -> Dict[str, Dict[str, Optional[str]]]:
    """Flatten probe ``ToolInfo`` objects into the manifest toolchain section."""
    payload: Dict[str, Dict[str, Optional[str]]] = {}
    for name, tool in tools.items():
        payload[name] = {
            "version": tool.version,
            "path": tool.path,
            "error": tool.error,
        }
    return payload
