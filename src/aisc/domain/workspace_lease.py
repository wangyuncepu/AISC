"""Workspace lease contract (runtime-lifecycle-ux Stage 1, 02 §2).

A cross-process, expiring workspace lease distinguishes "a Workbench
instance is still using this workspace" from "left over from a crash" —
Docker running/stopped alone cannot. The lease is an anti-mistaken-delete
mechanism, NOT a session-attach mechanism.

Timing contract (02 §2.2, frozen):
- heartbeat every ``LEASE_HEARTBEAT_INTERVAL_SECONDS`` (10-15s band);
- lease expires after ``LEASE_TTL_SECONDS`` = 3 heartbeat periods;
- expiry alone NEVER authorizes deletion — the holder must re-verify via
  registry/Docker-label reconciliation first (safety invariant 2; covers
  system sleep/hibernate where wall-clock time jumps past the TTL while
  the owning instance is merely suspended).

Heartbeats are written by the Tauri/Rust backend (D-RUNTIME-12) — never
by frontend JS timers, which throttle when the window hides to tray.

Storage lives in adapters/workspace_lease_store.py (the lease file rides
the DataRootStore layout: ``workspaces/<hash>/runtime-lease.json`` under
the workspace-scoped lock). Pure data + freshness math only here; no I/O,
no secrets (ids and timestamps only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

#: Lease JSON schema marker.
LEASE_SCHEMA = "aisc.workspace-lease/v1"
LEASE_SCHEMA_VERSION = 1

#: Heartbeat cadence every Workbench instance maintains per active workspace.
LEASE_HEARTBEAT_INTERVAL_SECONDS = 15.0

#: A lease is fresh while ``now - lease_last_seen_at <= TTL``; 3 heartbeat
#: periods of grace absorb transient heartbeat hiccups.
LEASE_TTL_SECONDS = 45.0


def now_iso() -> str:
    """RFC3339 UTC timestamp (the only clock representation in the file)."""
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value: str) -> Optional[datetime]:
    """Parse an RFC3339 timestamp; ``None`` for absent/garbage input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class WorkspaceLease:
    """One workspace lease record (the parsed lease file)."""

    workspace_key: str = ""        # sha256 hex of the canonical workspace path
    lease_id: str = ""
    workbench_instance_id: str = ""
    claimed_at: str = ""
    lease_last_seen_at: str = ""

    # -- freshness ----------------------------------------------------------

    def _last_seen(self) -> Optional[datetime]:
        return parse_ts(self.lease_last_seen_at)

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds since the last heartbeat; ``None`` when unparseable."""
        seen = self._last_seen()
        if seen is None:
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        return max(0.0, (now - seen).total_seconds())

    def expires_at_iso(self) -> str:
        seen = self._last_seen()
        if seen is None:
            return ""
        return datetime.fromtimestamp(
            seen.timestamp() + LEASE_TTL_SECONDS, tz=timezone.utc
        ).isoformat()

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Expired by wall-clock TTL.

        Callers MUST NOT treat ``False`` as "actively used" beyond this
        process's own heartbeat, nor ``True`` as delete authorization —
        post-expiry, reconcile against registry/Docker labels first.
        A lease whose ``lease_last_seen_at`` is unparseable is NOT fresh
        (fail closed toward re-claim, which overwrites the garbage).
        """
        age = self.age_seconds(now)
        if age is None:
            return True
        return age > LEASE_TTL_SECONDS

    def held_by(self, instance_id: str) -> bool:
        return bool(instance_id) and self.workbench_instance_id == instance_id

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": LEASE_SCHEMA,
            "schema_version": LEASE_SCHEMA_VERSION,
            "workspace_key": self.workspace_key,
            "lease_id": self.lease_id,
            "workbench_instance_id": self.workbench_instance_id,
            "claimed_at": self.claimed_at,
            "lease_last_seen_at": self.lease_last_seen_at,
        }


def lease_from_dict(data: Any) -> Optional[WorkspaceLease]:
    """Decode a lease record; ``None`` for foreign/garbage shapes.

    Unknown ``schema``/``schema_version`` fail closed to ``None`` (treated
    as no lease → a fresh claim overwrites the unrecognized file).
    """
    if not isinstance(data, dict):
        return None
    if data.get("schema") not in (None, LEASE_SCHEMA):
        return None
    if data.get("schema_version", LEASE_SCHEMA_VERSION) != LEASE_SCHEMA_VERSION:
        return None
    return WorkspaceLease(
        workspace_key=str(data.get("workspace_key") or ""),
        lease_id=str(data.get("lease_id") or ""),
        workbench_instance_id=str(data.get("workbench_instance_id") or ""),
        claimed_at=str(data.get("claimed_at") or ""),
        lease_last_seen_at=str(data.get("lease_last_seen_at") or ""),
    )
