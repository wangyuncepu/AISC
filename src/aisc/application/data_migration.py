"""Migration executor (Stage 7, 7d, DATA-02/03) — prepare/copy/commit/
rollback/quarantine over the 7c scan, plus the doctor payload.

Two-phase per the domain contract: copy every owned entry into a staging
tree INSIDE the data root (same volume), verify SHA-256, then atomically
``os.replace`` into the final layout. Crash/cancel semantics:

- the manifest (``<root>/migrations/<ws-dir-name>.json``, state=prepared)
  is the migration boundary — it is persisted BEFORE copying and updated
  as entries complete, so ``migrate`` re-run = resume (already-copied
  entries verified and skipped), never a partial overwrite;
- sources are never modified, moved or deleted (rollback only removes
  target writes this manifest made; unknown files move to quarantine only
  with explicit consent); a fully-migrated namespace gets a read-only
  ``.aisc-migrated`` redirect marker (old entries find it via doctor);
- conflicts (target exists with different bytes) and changed sources fail
  closed with stable ``AISC_ERR_DATA_MIGRATION_*`` codes — non-interactive
  callers exit non-zero, never guess.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from aisc.adapters.data_root_store import SCOPE_SHARED, SCOPE_WORKSPACE, DataRootStore
from aisc.application.legacy_scan import LegacyScan, scan_legacy_workspace
from aisc.domain.data_migration import (
    ENTRY_CONFLICT,
    ENTRY_OWNED,
    ENTRY_TRANSIENT,
    ENTRY_UNKNOWN,
    ERR_CONFLICT,
    ERR_CORRUPT_COPY,
    ERR_INSUFFICIENT_SPACE,
    ERR_SOURCE_CHANGED,
    ERR_UNKNOWN_PENDING,
    MARKER_NAME,
    MIGRATION_PROTOCOL,
    MIGRATION_SCHEMA_VERSION,
    STATE_COMMITTED,
    STATE_PREPARED,
    STATE_ROLLED_BACK,
    STATUS_COPIED,
    STATUS_PENDING,
    STATUS_QUARANTINED,
    MigrationEntry,
    MigrationManifest,
)
from aisc.domain.data_root import ResolvedDataRoot, workspace_dir_name
from aisc.domain.models import CliError

MIGRATION_LOCK = "migration"
_SPACE_MARGIN_BYTES = 64 * 1024 * 1024
_SPACE_FACTOR = 1.1

ProgressFn = Callable[[int, int, str], None]
ContinueFn = Callable[[], bool]


@dataclass
class MigrationResult:
    """Machine-readable outcome for the CLI envelope / Workbench."""

    outcome: str                 # "committed" | "cancelled" | "rolled_back"
    manifest: str                # manifest path
    copied: int = 0
    skipped: int = 0             # already in place (resume / re-migrate)
    quarantined: int = 0
    removed: int = 0             # rollback: target files removed
    kept: int = 0                # rollback: user-modified targets KEPT
    restored: int = 0            # rollback: quarantined files restored
    markers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "outcome": self.outcome,
            "manifest": self.manifest,
            "copied": self.copied,
            "skipped": self.skipped,
            "quarantined": self.quarantined,
            "removed": self.removed,
            "kept": self.kept,
            "restored": self.restored,
            "markers": list(self.markers),
        }


def _sha256_or_none(path: Path) -> Optional[str]:
    import hashlib

    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, tmp)
    # "r+b": fsync (FlushFileBuffers) needs a write handle on Windows.
    with open(tmp, "r+b") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dst)


class MigrationExecutor:
    """Executes one workspace's legacy→data-root migration."""

    def __init__(self, workspace: Path, resolved: ResolvedDataRoot,
                 store: Optional[DataRootStore] = None) -> None:
        self.workspace = Path(workspace)
        self.resolved = resolved
        self.store = store or DataRootStore(resolved)
        self._ws_dir_name = workspace_dir_name(resolved.workspace_hash)

    # -- locations -----------------------------------------------------------

    def manifest_path(self) -> Path:
        return self.resolved.root / "migrations" / f"{self._ws_dir_name}.json"

    def staging_dir(self) -> Path:
        return self.resolved.root / "migrations" / "staging" / self._ws_dir_name

    def quarantine_dir(self) -> Path:
        return self.resolved.root / "migrations" / "quarantine" / self._ws_dir_name

    # -- read-only surfaces (doctor / dry-run) --------------------------------

    def doctor(self) -> Dict[str, object]:
        """Resolver facts + legacy findings + pending-manifest state."""
        scan = scan_legacy_workspace(self.workspace, self.resolved)
        pending = None
        if self.manifest_path().is_file():
            try:
                manifest = MigrationManifest.from_dict(
                    json.loads(self.manifest_path().read_text(encoding="utf-8"))
                )
                pending = {"state": manifest.state, "entries": len(manifest.entries)}
            except (ValueError, json.JSONDecodeError, OSError):
                pending = {"state": "unreadable"}
        return {
            "data_root": self.resolved.to_dict(),
            "legacy": scan.summary(),
            "pending_manifest": pending,
        }

    def dry_run(self) -> Dict[str, object]:
        """Planned actions without touching anything."""
        scan = scan_legacy_workspace(self.workspace, self.resolved)
        return {
            "schema": MIGRATION_PROTOCOL,
            "workspace_hash": self.resolved.workspace_hash,
            "target": str(self.resolved.workspace_dir),
            "summary": scan.summary(),
            "conflicts": [e.relative for e in scan.entries
                          if e.classification == ENTRY_CONFLICT],
            "unknowns": [e.relative for e in scan.entries
                         if e.classification == ENTRY_UNKNOWN],
            "plan": {
                "copy_count": scan.counts()[ENTRY_OWNED],
                "skip_count": scan.counts()[ENTRY_TRANSIENT],
                "owned_bytes": scan.owned_bytes(),
            },
        }

    # -- execution -------------------------------------------------------------

    def migrate(
        self,
        *,
        quarantine_unknown: bool = False,
        progress: Optional[ProgressFn] = None,
        should_continue: Optional[ContinueFn] = None,
    ) -> MigrationResult:
        scan = scan_legacy_workspace(self.workspace, self.resolved)
        self._gate(scan, quarantine_unknown)

        with self.store.lock(MIGRATION_LOCK, scope=SCOPE_WORKSPACE):
            manifest = self._prepare(scan)
            result = MigrationResult(outcome="cancelled",
                                     manifest=str(self.manifest_path()))
            staged_any = False
            try:
                owned = [e for e in manifest.entries if e.classification == ENTRY_OWNED]
                total = len(owned)
                done = 0
                for entry in owned:
                    if should_continue is not None and not should_continue():
                        # Cancel: keep manifest (state=prepared), sources
                        # untouched; a later run resumes.
                        manifest = self._persist(manifest)
                        return result
                    done += 1
                    if progress is not None:
                        progress(done, total, entry.relative)
                    self._stage_entry(entry, manifest)
                    staged_any = True
                    # Persist progress every entry: crash-safe resume.
                    manifest = self._persist(manifest)
                self._commit(manifest, result)
                if quarantine_unknown:
                    self._quarantine(manifest, result)
                self._write_markers(manifest, result)
                manifest.state = STATE_COMMITTED
                self._persist(manifest)
                result.outcome = "committed"
                return result
            finally:
                if staged_any:
                    shutil.rmtree(self.staging_dir(), ignore_errors=True)

    def rollback(self, manifest_path: Optional[Path] = None) -> MigrationResult:
        path = Path(manifest_path) if manifest_path else self.manifest_path()
        if not path.is_file():
            raise CliError(f"migration manifest not found: {path}",
                           exit_code=1, error_code=ERR_SOURCE_CHANGED)
        try:
            manifest = MigrationManifest.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise CliError(f"unreadable migration manifest: {path} ({exc})",
                           exit_code=1, error_code=ERR_CORRUPT_COPY) from exc

        result = MigrationResult(outcome="rolled_back", manifest=str(path))
        with self.store.lock(MIGRATION_LOCK, scope=SCOPE_WORKSPACE):
            for entry in manifest.entries:
                if entry.status == STATUS_COPIED and entry.target:
                    target = self.resolved.workspace_dir / Path(*entry.target.split("/"))
                    current = _sha256_or_none(target)
                    if current is None:
                        continue
                    if current == entry.sha256:
                        target.unlink()
                        result.removed += 1
                    else:
                        # User-modified since migration: NEVER delete (fail
                        # closed per entry, continue with the rest).
                        result.kept += 1
                elif entry.status == STATUS_QUARANTINED:
                    self._restore_quarantined(entry, result)
            for ns in manifest.markers:
                marker = self.workspace / ns / MARKER_NAME
                try:
                    marker.unlink()
                except OSError:
                    pass
            manifest.state = STATE_ROLLED_BACK
            self._persist(manifest)
        return result

    # -- internals ---------------------------------------------------------------

    def _gate(self, scan: LegacyScan, quarantine_unknown: bool) -> None:
        conflicts = [e.relative for e in scan.entries
                     if e.classification == ENTRY_CONFLICT]
        if conflicts:
            raise CliError(
                f"migration blocked by {len(conflicts)} conflict(s), e.g. {conflicts[0]!r}",
                exit_code=1, error_code=ERR_CONFLICT,
                hint="Resolve target conflicts (rollback or inspect) before migrating.")
        unknowns = [e.relative for e in scan.entries
                    if e.classification == ENTRY_UNKNOWN]
        if unknowns and not quarantine_unknown:
            raise CliError(
                f"{len(unknowns)} unknown file(s) inside AISC namespaces, "
                f"e.g. {unknowns[0]!r}",
                exit_code=1, error_code=ERR_UNKNOWN_PENDING,
                hint="Pass --quarantine-unknown to move them to the migration "
                     "quarantine (sources are kept until you confirm).")

    def _prepare(self, scan: LegacyScan) -> MigrationManifest:
        manifest = scan.to_manifest()
        self._check_space(manifest)
        self.store.prepare()
        self.staging_dir().mkdir(parents=True, exist_ok=True)
        # Resume: an earlier prepared manifest is the boundary — reuse the
        # statuses of entries that already completed.
        if self.manifest_path().is_file():
            try:
                prior = MigrationManifest.from_dict(
                    json.loads(self.manifest_path().read_text(encoding="utf-8"))
                )
            except (ValueError, json.JSONDecodeError, OSError):
                prior = None
            if prior is not None and prior.state == STATE_PREPARED:
                done = {(e.relative, e.sha256): e.status for e in prior.entries}
                for entry in manifest.entries:
                    entry.status = done.get((entry.relative, entry.sha256),
                                            STATUS_PENDING)
        manifest.state = STATE_PREPARED
        self._persist(manifest)
        return manifest

    def _check_space(self, manifest: MigrationManifest) -> None:
        need = int(sum(e.size for e in manifest.entries
                       if e.classification == ENTRY_OWNED) * _SPACE_FACTOR)
        need += _SPACE_MARGIN_BYTES
        usage = shutil.disk_usage(str(self.resolved.root))
        if usage.free < need:
            raise CliError(
                f"insufficient space: need ~{need} bytes, have {usage.free}",
                exit_code=1, error_code=ERR_INSUFFICIENT_SPACE,
                hint="Free space under the data root drive and retry.")

    def _stage_entry(self, entry: MigrationEntry, manifest: MigrationManifest) -> None:
        if entry.status == STATUS_COPIED:
            return
        src = self.workspace / Path(*entry.relative.split("/"))
        if not src.is_file():
            raise CliError(f"source vanished during migration: {entry.relative}",
                           exit_code=1, error_code=ERR_SOURCE_CHANGED)
        current = _sha256_or_none(src) or ""
        if current != entry.sha256:
            raise CliError(
                f"source changed during migration: {entry.relative}",
                exit_code=1, error_code=ERR_SOURCE_CHANGED,
                hint="Re-run the migration to re-scan the changed files.")

        final = self.resolved.workspace_dir / Path(*entry.target.split("/"))
        final_hash = _sha256_or_none(final)
        if final_hash == entry.sha256:
            entry.status = STATUS_COPIED  # already migrated (resume/re-run)
            return
        if final.exists():
            raise CliError(
                f"target exists with different content: {entry.target}",
                exit_code=1, error_code=ERR_CONFLICT)

        staged = self.staging_dir() / Path(*entry.target.split("/"))
        staged_hash = _sha256_or_none(staged)
        if staged_hash != entry.sha256:
            _copy_file(src, staged)
            staged_hash = _sha256_or_none(staged)
        if staged_hash != entry.sha256:
            raise CliError(f"copy verification failed: {entry.relative}",
                           exit_code=1, error_code=ERR_CORRUPT_COPY)

    def _commit(self, manifest: MigrationManifest, result: MigrationResult) -> None:
        for entry in manifest.entries:
            if entry.classification != ENTRY_OWNED:
                continue
            if entry.status == STATUS_COPIED:
                result.skipped += 1
                continue
            staged = self.staging_dir() / Path(*entry.target.split("/"))
            final = self.resolved.workspace_dir / Path(*entry.target.split("/"))
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, final)  # same volume: atomic
            if _sha256_or_none(final) != entry.sha256:
                raise CliError(f"commit verification failed: {entry.target}",
                               exit_code=1, error_code=ERR_CORRUPT_COPY)
            entry.status = STATUS_COPIED
            result.copied += 1

    def _quarantine(self, manifest: MigrationManifest, result: MigrationResult) -> None:
        for entry in manifest.entries:
            if entry.classification != ENTRY_UNKNOWN:
                continue
            if not entry.sha256:
                # Reparse/symlink entries are never hashed — never follow.
                continue
            src = self.workspace / Path(*entry.relative.split("/"))
            if not src.is_file() or src.is_symlink():
                continue
            dst = self.quarantine_dir() / Path(*entry.relative.split("/"))
            # Copy → verify → remove source: byte-safe move even across
            # volumes; the manifest records the original path for rollback.
            _copy_file(src, dst)
            if _sha256_or_none(dst) == entry.sha256:
                src.unlink()
                entry.status = STATUS_QUARANTINED
                result.quarantined += 1

    def _restore_quarantined(self, entry: MigrationEntry,
                             result: MigrationResult) -> None:
        qpath = self.quarantine_dir() / Path(*entry.relative.split("/"))
        dest = self.workspace / Path(*entry.relative.split("/"))
        if not qpath.is_file():
            return
        if dest.exists():
            result.kept += 1  # never overwrite anything present at the source
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(qpath, dest)
        if _sha256_or_none(dest) == (entry.sha256 or _sha256_or_none(qpath)):
            qpath.unlink()
            result.restored += 1

    def _write_markers(self, manifest: MigrationManifest,
                       result: MigrationResult) -> None:
        """A namespace earns a redirect marker only when every owned file of
        it migrated AND nothing unknown is left there (unknowns either moved
        to quarantine or none existed)."""
        pending_unknown = {e.relative.split("/", 1)[0] for e in manifest.entries
                           if e.classification == ENTRY_UNKNOWN
                           and e.status != STATUS_QUARANTINED}
        for ns in (".aisc", ".claude", ".codex", ".cc-switch"):
            ns_dir = self.workspace / ns
            if not ns_dir.is_dir() or ns in pending_unknown:
                continue
            owned_ns = [e for e in manifest.entries
                        if e.classification == ENTRY_OWNED
                        and e.relative.startswith(ns + "/")]
            if not owned_ns or not all(e.status == STATUS_COPIED for e in owned_ns):
                continue
            marker = ns_dir / MARKER_NAME
            marker.write_text(json.dumps({
                "schema": MIGRATION_PROTOCOL,
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "workspace_hash": manifest.workspace_hash,
                "data_root": str(self.resolved.root),
                "manifest": self.manifest_path().name,
            }, indent=2) + "\n", encoding="utf-8")
            if ns not in manifest.markers:
                manifest.markers.append(ns)
            if ns not in result.markers:
                result.markers.append(ns)

    def _persist(self, manifest: MigrationManifest) -> MigrationManifest:
        # Caller already holds the migration lock (migrate/rollback wrap the
        # whole cycle) — write WITHOUT re-locking (same-process byte locks
        # on a second handle would self-deadlock).
        self.store.write_json(
            SCOPE_SHARED, f"migrations/{self._ws_dir_name}.json", manifest.to_dict()
        )
        return manifest
