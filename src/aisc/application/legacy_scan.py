"""Read-only legacy-layout scanner (Stage 7, 7c, DATA-02).

Walks the pre-Stage-7 AISC namespaces in a workspace and classifies every
file against the domain allowlist (``domain/data_migration.py``): owned /
transient / unknown / conflict, plus namespace-level ``foreign`` detection
(a ``.claude`` that predates AISC — no init marker — is the user's own and
is never migrated). Produces the migration manifest draft
(``aisc.data-migration/v1``) that 7d executes.

Safety properties:
- strictly read-only: no directory is created, no file touched;
- symlinks/reparse points inside a namespace are never followed — they
  classify as ``unknown`` (quarantine candidate), so a link can neither
  leak content out of the workspace nor smuggle a target in;
- ``owned``/``unknown`` files are hashed (SHA-256, streamed) because the
  manifest commits to exact bytes; conflicts compare hashes, never mtimes.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from aisc.domain.data_migration import (
    AISC_INIT_MARKERS,
    ENTRY_CONFLICT,
    ENTRY_OWNED,
    ENTRY_TRANSIENT,
    ENTRY_UNKNOWN,
    MIGRATION_PROTOCOL,
    MIGRATION_SCHEMA_VERSION,
    NAMESPACE_AISC,
    NAMESPACE_FOREIGN,
    STATE_PREPARED,
    MigrationEntry,
    MigrationManifest,
    classify,
)
from aisc.domain.data_root import ResolvedDataRoot

_HASH_CHUNK = 1 << 16

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400  # windows.h (symlink, junction, …)
_IO_REPARSE_TAG_AF_UNIX = 0x80000023    # winsock AF_UNIX socket files


def _is_reparse(path: Path) -> bool:
    """True for symlinks AND junctions/OneDrive placeholders (Python's
    ``is_symlink`` misses junctions; the attribute bit does not)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class NamespaceFinding:
    """Namespace-level report row (doctor / dry-run UX)."""

    namespace: str          # e.g. ".cc-switch" or ".local/state/cc-switch"
    kind: str               # NAMESPACE_AISC | NAMESPACE_FOREIGN
    file_count: int = 0
    total_bytes: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "namespace": self.namespace,
            "kind": self.kind,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


@dataclass
class LegacyScan:
    """Full read-only scan result for one workspace."""

    workspace: Path
    resolved: ResolvedDataRoot
    findings: List[NamespaceFinding] = field(default_factory=list)
    entries: List[MigrationEntry] = field(default_factory=list)

    # -- rollups ------------------------------------------------------------

    def counts(self) -> Dict[str, int]:
        out = dict.fromkeys(("owned", "transient", "unknown", "conflict"), 0)
        for e in self.entries:
            out[e.classification] = out.get(e.classification, 0) + 1
        return out

    def owned_bytes(self) -> int:
        return sum(e.size for e in self.entries if e.classification == ENTRY_OWNED)

    def summary(self) -> Dict[str, object]:
        """Doctor/dry-run payload (counts and sizes only; paths stay in the
        manifest the user explicitly exports)."""
        return {
            "schema": MIGRATION_PROTOCOL,
            "workspace_hash": self.resolved.workspace_hash,
            "namespaces": [f.to_dict() for f in self.findings],
            "counts": self.counts(),
            "owned_bytes": self.owned_bytes(),
            "has_unknowns": any(e.classification == ENTRY_UNKNOWN for e in self.entries),
            "has_conflicts": any(e.classification == ENTRY_CONFLICT for e in self.entries),
            "has_foreign": any(f.kind == NAMESPACE_FOREIGN for f in self.findings),
        }

    def to_manifest(self) -> MigrationManifest:
        """Draft manifest: 7d persists it (state=prepared) before copying."""
        return MigrationManifest(
            schema=MIGRATION_PROTOCOL,
            schema_version=MIGRATION_SCHEMA_VERSION,
            workspace_hash=self.resolved.workspace_hash,
            source=str(self.workspace.resolve()),
            target=str(self.resolved.workspace_dir),
            entries=list(self.entries),
            state=STATE_PREPARED,
        )


def _is_aisc_initialized(workspace: Path) -> bool:
    return any((workspace / m).exists() for m in AISC_INIT_MARKERS)


def scan_legacy_workspace(workspace: Path, resolved: ResolvedDataRoot) -> LegacyScan:
    """Scan *workspace* for legacy AISC namespaces. Read-only; missing
    namespaces are simply absent from the findings."""
    ws = Path(workspace)
    scan = LegacyScan(workspace=ws, resolved=resolved)
    aisc_initialized = _is_aisc_initialized(ws)

    for namespace in (".aisc", ".claude", ".codex", ".cc-switch", ".local"):
        ns_root = ws / namespace
        if not ns_root.exists():
            continue
        finding = NamespaceFinding(namespace=namespace, kind=NAMESPACE_AISC)
        if not aisc_initialized:
            # None of the AISC init markers exist: these namespaces are the
            # user's own (D7-03) — report, never migrate.
            finding.kind = NAMESPACE_FOREIGN
            finding.file_count, finding.total_bytes = _count_tree(ns_root)
            scan.findings.append(finding)
            continue
        scan.findings.append(finding)
        _scan_namespace(ws, namespace, ns_root, resolved, scan, finding)

    scan.entries.sort(key=lambda e: e.relative)
    return scan


def _scan_namespace(
    ws: Path,
    namespace: str,
    ns_root: Path,
    resolved: ResolvedDataRoot,
    scan: LegacyScan,
    finding: NamespaceFinding,
) -> None:
    for dirpath, dirnames, filenames in os.walk(ns_root, followlinks=False):
        # Never descend into symlinked/junctioned dirs (junctions are not
        # ``is_symlink`` — check the reparse attribute too).
        dirnames[:] = [d for d in dirnames if not _is_reparse(Path(dirpath) / d)]
        for fname in filenames:
            abs_path = Path(dirpath) / fname
            rel_ns = abs_path.relative_to(ns_root).as_posix()
            finding.file_count += 1

            if _is_reparse(abs_path):
                # Windows AF_UNIX sockets are reparse points (Python on
                # Windows does not set S_IFSOCK — decode the tag); they are
                # transient coordination files, not quarantine candidates.
                try:
                    st = os.lstat(abs_path)
                    is_socket = stat.S_ISSOCK(st.st_mode) or (
                        getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_AF_UNIX
                    )
                    if is_socket:
                        scan.entries.append(
                            MigrationEntry(relative=f"{namespace}/{rel_ns}",
                                           classification=ENTRY_TRANSIENT)
                        )
                        continue
                except OSError:
                    pass
                # Never follow or stat the target (a symlink to a huge file
                # must not inflate sizes); quarantine candidate.
                scan.entries.append(
                    MigrationEntry(relative=f"{namespace}/{rel_ns}",
                                   classification=ENTRY_UNKNOWN)
                )
                continue

            try:
                size = abs_path.stat().st_size
            except OSError:
                size = 0
            finding.total_bytes += size

            classification, target_rel = classify(namespace, rel_ns)
            if classification == ENTRY_TRANSIENT:
                scan.entries.append(
                    MigrationEntry(relative=f"{namespace}/{rel_ns}",
                                   classification=ENTRY_TRANSIENT, size=size)
                )
                continue

            digest = _sha256_file(abs_path)
            if classification == ENTRY_OWNED and target_rel:
                target_abs = resolved.workspace_dir / Path(*target_rel.split("/"))
                if target_abs.exists():
                    # Fail closed on any mismatch; identical bytes = already
                    # migrated (skipped by 7d, not re-copied).
                    classification = (
                        ENTRY_OWNED if _sha256_file(target_abs) == digest
                        else ENTRY_CONFLICT
                    )
            scan.entries.append(
                MigrationEntry(relative=f"{namespace}/{rel_ns}",
                               classification=classification,
                               sha256=digest, size=size, target=target_rel)
            )


def _count_tree(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for fname in filenames:
            files += 1
            try:
                total += (Path(dirpath) / fname).stat().st_size
            except OSError:
                pass
    return files, total
