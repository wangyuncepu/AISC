"""Workspace lease storage (runtime-lifecycle-ux Stage 1, 02 §2.3).

The lease file rides the frozen DataRootStore layout:

- record: ``<data-root>/workspaces/<hash>/runtime-lease.json``
  (workspace scope, atomic temp+replace via ``DataRootStore.write_json``);
- cross-process lock: ``state/locks/<hash>-runtime-lease.lock``
  (``DataRootStore.lock`` — msvcrt/fcntl, fail-closed timeout);
- release deletes the record — an absent file IS "no lease".

No secrets: ids and timestamps only. Claim/heartbeat/release/inspect are
the whole API; the Rust heartbeat task (D-RUNTIME-12) calls ``heartbeat``
through the CLI on its interval — never via frontend timers.
"""

from __future__ import annotations

import uuid
from typing import Optional, Tuple

from aisc.adapters.data_root_store import DataRootStore
from aisc.domain.models import CliError, RuntimeErrorCode, RuntimeExitCode
from aisc.domain.workspace_lease import (
    WorkspaceLease,
    lease_from_dict,
    now_iso,
)

#: Lease record path (workspace scope) and its lock name.
LEASE_REL = "runtime-lease.json"
LEASE_LOCK_NAME = "runtime-lease"

#: Lock acquisition timeout — lease ops are tiny; contention means another
#: process is mid-claim, which resolves in milliseconds.
LEASE_LOCK_TIMEOUT = 10.0


class WorkspaceLeaseStore:
    """Claim/heartbeat/release/inspect over one workspace's lease file."""

    def __init__(self, store: DataRootStore, workspace_key: str) -> None:
        self._store = store
        self._workspace_key = workspace_key

    # -- read -------------------------------------------------------------

    def inspect(self) -> Optional[WorkspaceLease]:
        """Current lease, or ``None`` when absent/corrupt (read-only).

        Corrupt JSON is isolated by ``DataRootStore.read_json`` (renamed
        ``.corrupt``) and reads as absent — the next claim overwrites.
        """
        data = self._store.read_json("workspace", LEASE_REL)
        return lease_from_dict(data)

    # -- claim ------------------------------------------------------------

    def claim(
        self,
        instance_id: str,
        *,
        lease_id: Optional[str] = None,
        now: Optional[str] = None,
    ) -> Tuple[WorkspaceLease, str]:
        """Claim the workspace lease.

        Returns ``(lease, outcome)`` where outcome is one of:

        - ``"claimed"``            — no prior lease; fresh claim written;
        - ``"claimed_stale"``      — prior lease expired/garbage; taken over;
        - ``"reclaimed"``          — fresh lease already held by this
                                     instance; heartbeat folded in, lease_id
                                     preserved (idempotent re-materialize).

        Raises ``CliError(AISC_ERR_ACTIVE_WORKSPACE_LEASE)`` when a fresh
        lease belongs to another instance — the caller must NOT touch that
        workspace's runtime resources.
        """
        if not instance_id:
            raise CliError(
                "workspace lease claim requires an instance id",
                exit_code=2,
                error_code=RuntimeErrorCode.RUNTIME_LEASE_CONFLICT,
            )
        stamp = now or now_iso()
        with self._store.lock(LEASE_LOCK_NAME, LEASE_LOCK_TIMEOUT, scope="workspace"):
            existing = self.inspect()
            if existing is not None and not existing.is_expired():
                if existing.held_by(instance_id):
                    refreshed = WorkspaceLease(
                        workspace_key=existing.workspace_key or self._workspace_key,
                        lease_id=existing.lease_id,
                        workbench_instance_id=instance_id,
                        claimed_at=existing.claimed_at,
                        lease_last_seen_at=stamp,
                    )
                    self._write(refreshed)
                    return refreshed, "reclaimed"
                raise CliError(
                    "workspace is leased by another Workbench instance",
                    exit_code=RuntimeExitCode.ACTIVE_WORKSPACE_LEASE,
                    error_code=RuntimeErrorCode.ACTIVE_WORKSPACE_LEASE,
                    data={
                        "workspace_key": self._workspace_key,
                        "holder_instance_id": existing.workbench_instance_id,
                        "lease_id": existing.lease_id,
                        "expires_at": existing.expires_at_iso(),
                    },
                )
            # Absent, expired or unparseable → take over.
            lease = WorkspaceLease(
                workspace_key=self._workspace_key,
                lease_id=lease_id or str(uuid.uuid4()),
                workbench_instance_id=instance_id,
                claimed_at=stamp,
                lease_last_seen_at=stamp,
            )
            self._write(lease)
            return lease, ("claimed_stale" if existing is not None else "claimed")

    # -- heartbeat ----------------------------------------------------------

    def heartbeat(
        self,
        instance_id: str,
        lease_id: str,
        *,
        now: Optional[str] = None,
    ) -> Optional[WorkspaceLease]:
        """Refresh ``lease_last_seen_at`` for the matching lease.

        Returns the refreshed lease, or ``None`` when the record is absent
        (released/never claimed — the caller re-claims via :meth:`claim`).
        Raises ``AISC_ERR_RUNTIME_LEASE_CONFLICT`` when a DIFFERENT instance
        or lease now owns the file (taken over after expiry) — the caller
        must stop heartbeating and re-run reconcile.
        """
        stamp = now or now_iso()
        with self._store.lock(LEASE_LOCK_NAME, LEASE_LOCK_TIMEOUT, scope="workspace"):
            existing = self.inspect()
            if existing is None:
                return None
            if existing.workbench_instance_id != instance_id or (
                lease_id and existing.lease_id != lease_id
            ):
                raise CliError(
                    "workspace lease now belongs to another instance",
                    exit_code=RuntimeExitCode.ACTIVE_WORKSPACE_LEASE,
                    error_code=RuntimeErrorCode.RUNTIME_LEASE_CONFLICT,
                    data={
                        "workspace_key": self._workspace_key,
                        "holder_instance_id": existing.workbench_instance_id,
                        "lease_id": existing.lease_id,
                    },
                )
            refreshed = WorkspaceLease(
                workspace_key=existing.workspace_key,
                lease_id=existing.lease_id,
                workbench_instance_id=existing.workbench_instance_id,
                claimed_at=existing.claimed_at,
                lease_last_seen_at=stamp,
            )
            self._write(refreshed)
            return refreshed

    # -- release ------------------------------------------------------------

    def release(self, instance_id: str, lease_id: str) -> bool:
        """Release the lease — only when both ids match (never another
        instance's). Returns whether a matching lease was removed."""
        with self._store.lock(LEASE_LOCK_NAME, LEASE_LOCK_TIMEOUT, scope="workspace"):
            existing = self.inspect()
            if existing is None:
                return False
            if existing.workbench_instance_id != instance_id or existing.lease_id != lease_id:
                return False
            path = self._store.path_for("workspace", LEASE_REL)
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            return True

    # -- internals ----------------------------------------------------------

    def _write(self, lease: WorkspaceLease) -> None:
        self._store.write_json(
            "workspace", LEASE_REL, lease.to_dict(), lock=None,
        )
