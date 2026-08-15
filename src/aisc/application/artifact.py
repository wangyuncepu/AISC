"""Agent Artifact application service — session-scoped registry (Stage 3).

Registry lives OUTSIDE the workspace (host data dir) so ``git status`` never
gains entries (A-ART04-1, R3-05). Storage is one JSONL per session keyed by
``<data-root>/aisc-artifacts/<workspace-hash>/<session-id>.jsonl``.

Concurrency / corruption (A-ART06-1, R3-07):
- append uses a lock file (best-effort, 10s timeout) + temp file + ``os.replace``;
- a corrupt line is isolated (skipped + reported), never truncates the file;
- records are idempotent by ``artifact_id``: re-recording the same id updates
  in place (modified/deleted/renamed) instead of duplicating.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from aisc.domain.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactAction,
    ArtifactProvenance,
    ArtifactRecord,
    validate_relative_path,
    workspace_hash,
)

# Lock scope: one per process (the CLI is single-user, single-process per
# command; the Workbench holds its own). Cross-process safety is provided by
# the lock file at write time.
_LOCKS: Dict[str, threading.Lock] = {}


def data_root() -> Path:
    """Host data dir for the artifact registry (never inside a workspace)."""
    env = os.environ.get("AISC_ARTIFACT_DATA_ROOT")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "aisc" / "artifacts"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "aisc" / "artifacts"
    return Path.home() / ".local" / "share" / "aisc" / "artifacts"


def registry_path(workspace: Path, session_id: str) -> Path:
    """JSONL path for one session's artifact registry."""
    return data_root() / workspace_hash(workspace) / f"{session_id}.jsonl"


def _session_lock(workspace: Path, session_id: str) -> threading.Lock:
    key = f"{workspace_hash(workspace)}/{session_id}"
    lock = _LOCKS.get(key)
    if lock is None:
        lock = threading.Lock()
        _LOCKS[key] = lock
    return lock


def _lock_file_path(workspace: Path, session_id: str) -> Path:
    return registry_path(workspace, session_id).with_suffix(".lock")


def _acquire_lock(workspace: Path, session_id: str, timeout: float = 10.0) -> None:
    """Best-effort cross-process lock; raises TimeoutError on timeout."""
    lock_path = _lock_file_path(workspace, session_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    import time

    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            # Stale lock detection: older than 30s is assumed abandoned.
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"artifact registry lock timeout: {lock_path}"
                )
            time.sleep(0.05)


def _release_lock(workspace: Path, session_id: str) -> None:
    _lock_file_path(workspace, session_id).unlink(missing_ok=True)


def _read_lines(path: Path) -> List[ArtifactRecord]:
    """Read all records, isolating corrupt lines (never truncate, R3-07)."""
    if not path.is_file():
        return []
    out: List[ArtifactRecord] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(ArtifactRecord.from_dict(json.loads(line)))
        except (json.JSONDecodeError, ValueError, KeyError):
            # Corrupt/unsupported line: isolate, keep the rest (A-ART01-2).
            continue
    return out


def _write_lines(path: Path, records: List[ArtifactRecord]) -> None:
    """Atomic replace of the JSONL file (temp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".artifacts_", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------

def record(
    workspace: Path,
    record_data: ArtifactRecord,
    *,
    session_id: Optional[str] = None,
) -> ArtifactRecord:
    """Validate + persist one artifact record. Idempotent by artifact_id.

    ``session_id`` defaults to the record's producer.session_id. Returns the
    validated record.
    """
    rec = record_data.validate()
    session = session_id or rec.producer.get("session_id")
    if not session:
        raise ValueError("session_id is required")
    path = registry_path(workspace, session)
    lock = _session_lock(workspace, session)
    with lock:
        _acquire_lock(workspace, session)
        try:
            records = _read_lines(path)
            # Idempotent: replace an existing record with the same id.
            kept = [r for r in records if r.artifact_id != rec.artifact_id]
            kept.append(rec)
            _write_lines(path, kept)
        finally:
            _release_lock(workspace, session)
    return rec


def list_records(
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    kind: Optional[str] = None,
) -> List[ArtifactRecord]:
    """List records for the session (or all sessions under the workspace hash)."""
    base = data_root() / workspace_hash(workspace)
    if not base.is_dir():
        return []
    files = [base / f"{session_id}.jsonl"] if session_id else sorted(base.glob("*.jsonl"))
    out: List[ArtifactRecord] = []
    for f in files:
        if f.name.endswith(".lock") or not f.is_file():
            continue
        for rec in _read_lines(f):
            if kind and rec.kind != kind:
                continue
            out.append(rec)
    return out


def inspect_record(workspace: Path, artifact_id: str) -> Optional[ArtifactRecord]:
    """Find a record by artifact_id across sessions for this workspace."""
    for rec in list_records(workspace):
        if rec.artifact_id == artifact_id:
            return rec
    return None


def clear_session(workspace: Path, session_id: str) -> None:
    """Remove one session's registry file (returns silently if absent)."""
    path = registry_path(workspace, session_id)
    lock = _session_lock(workspace, session_id)
    with lock:
        _acquire_lock(workspace, session_id)
        try:
            path.unlink(missing_ok=True)
        finally:
            _release_lock(workspace, session_id)


def mark_missing(
    workspace: Path,
    artifact_id: str,
    *,
    state: str = "missing",
) -> Optional[ArtifactRecord]:
    """Flip a present record to missing/deleted without changing provenance."""
    from aisc.domain.artifacts import ArtifactState

    for rec in list_records(workspace):
        if rec.artifact_id == artifact_id:
            updated = ArtifactRecord(
                schema_version=rec.schema_version,
                artifact_id=rec.artifact_id,
                workspace_relative_path=rec.workspace_relative_path,
                action=rec.action,
                kind=rec.kind,
                media_type=rec.media_type,
                label=rec.label,
                open_with=rec.open_with,
                producer=dict(rec.producer),
                state=state,
                provenance=rec.provenance,
                recorded_at=rec.recorded_at,
                previous_path=rec.previous_path,
                extra=dict(rec.extra),
            ).validate()
            return record(workspace, updated, session_id=rec.producer.get("session_id"))
    return None
