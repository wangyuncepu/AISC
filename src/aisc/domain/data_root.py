"""Data root domain contract (Stage 7, DATA-01..04, D7-01/02/05).

The single source of truth for the canonical Windows data layout:
``%LOCALAPPDATA%\\AISC\\data`` (see 02-domain-contract.md). Everything AISC
auto-generates — config, state, runtime, logs, cache, artifacts, diagnostics,
migrations — lives under one resolver-produced root; the workspace keeps only
user files.

This module is PURE (no env, no filesystem): canonicalization helpers, the
versioned workspace hash, the layout contract and the structured resolve
result. Env/platform selection and containment probing live in
``aisc.application.data_root.DataRootResolver``; the Rust mirror is
``workbench/src-tauri/src/data_root.rs`` (kept in sync via
``tests/fixtures/data-root/hash-vectors.json``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

DATA_ROOT_PROTOCOL = "aisc.data-root/v1"
DATA_ROOT_SCHEMA_VERSION = 1

# Versioned workspace isolation hash (D7-02). ``sha256-v1:<64 hex>`` in JSON
# fields; the directory-name form swaps the colon for a dash (':' is illegal
# in Windows filenames).
WORKSPACE_HASH_ALGO = "sha256-v1"

# Shared-root layout (02-domain-contract.md "Canonical layout"). Order is the
# contract order; consumers must not invent siblings.
SHARED_SUBDIRS = ("config", "state", "workspaces", "artifacts", "cache", "diagnostics", "migrations")

# Per-workspace layout under workspaces/<hash>/.
WORKSPACE_SUBDIRS = ("claude", "codex", "cc-switch", "runtime", "logs")

# Locks live under state/ (contract: "locks/indexes"). Workspace-scoped
# locks share the dir with a hash prefix, keeping the contract layout intact.
LOCKS_SUBDIR = "state/locks"

# Stable error codes (exit mapping is the caller's job). Domain-owned so the
# application resolver and adapter writers share one spelling.
ERR_OVERRIDE_RELATIVE = "AISC_ERR_DATA_ROOT_OVERRIDE_RELATIVE"
ERR_REPARSE_POINT = "AISC_ERR_DATA_ROOT_REPARSE_POINT"
ERR_WORKSPACE_OVERLAP = "AISC_ERR_DATA_ROOT_WORKSPACE_OVERLAP"
ERR_LOCK_TIMEOUT = "AISC_ERR_DATA_ROOT_LOCK_TIMEOUT"


def strip_verbatim(path_str: str) -> str:
    """Drop Windows verbatim (``\\\\?\\``) prefixes so both languages hash the
    same string (Python ``resolve()`` usually omits the prefix, Rust
    ``canonicalize()`` always adds it)."""
    if path_str.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path_str[len("\\\\?\\UNC\\"):]
    if path_str.startswith("\\\\?\\"):
        return path_str[len("\\\\?\\"):]
    return path_str


def canonical_workspace_path(workspace: Path) -> str:
    """Canonical absolute path string used as the hash input (non-strict:
    a missing workspace resolves as-given, matching domain/artifacts.py)."""
    return strip_verbatim(str(Path(workspace).resolve()))


def hash_canonical_path(canon: str) -> str:
    """Pure hash of an ALREADY-canonical path string → ``sha256-v1:<64 hex>``.

    Full digest (not the 16-hex short form used by the Stage-3 artifact
    registry): collision tests in 04-observability-testing rely on the whole
    digest, and D7-02 asks for the versioned form.
    """
    return WORKSPACE_HASH_ALGO + ":" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def workspace_hash_v1(workspace: Path) -> str:
    """Versioned hash of a workspace path (irreversible; never stores the raw
    path in a directory name — D7-02)."""
    return hash_canonical_path(canonical_workspace_path(workspace))


def workspace_dir_name(workspace_hash: str) -> str:
    """Windows-safe directory form: ``sha256-v1:<hex>`` → ``sha256-v1-<hex>``."""
    return workspace_hash.replace(":", "-", 1)


@dataclass(frozen=True)
class ResolvedDataRoot:
    """Structured resolver result (schema/versioned, 01-cross-stage-contracts
    §1: callers never concatenate data-root paths themselves).

    ``workspace`` is deliberately NOT in ``to_dict()`` — doctor/diagnostics
    expose the hash, not the raw workspace path, unless the user explicitly
    exports it (04-observability-testing "证据与脱敏").
    """

    schema: str = DATA_ROOT_PROTOCOL
    schema_version: int = DATA_ROOT_SCHEMA_VERSION
    root: Path = Path()
    origin: str = "default"  # "default" | "env" (AISC_DATA_ROOT override)
    workspace_hash: str = ""
    writable: bool = False
    # Relative-name → absolute-path maps (contract order).
    shared_dirs: Dict[str, Path] = field(default_factory=dict)
    workspace_dirs: Dict[str, Path] = field(default_factory=dict)

    @property
    def workspace_dir(self) -> Path:
        """workspaces/<hash>/ — the per-workspace subtree root."""
        return self.shared_dirs["workspaces"] / workspace_dir_name(self.workspace_hash)

    def to_dict(self) -> Dict[str, str]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "root": str(self.root),
            "origin": self.origin,
            "workspace_hash": self.workspace_hash,
            "writable": self.writable,
            "shared_dirs": {k: str(v) for k, v in self.shared_dirs.items()},
            "workspace_dirs": {k: str(v) for k, v in self.workspace_dirs.items()},
        }
