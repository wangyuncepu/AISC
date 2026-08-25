"""runtime-lifecycle-ux Stage 1: workspace lease claim/heartbeat/release.

Contract (02-domain-contract.md §2):
- concurrent claim: only one instance holds a fresh lease (the loser gets
  AISC_ERR_ACTIVE_WORKSPACE_LEASE with holder identity);
- TTL expiry (3 heartbeat periods) allows takeover — but expiry alone is
  never delete authorization (reconcile re-verifies; see reconcile tests);
- heartbeat refreshes only the matching instance+lease; a takeover after
  expiry surfaces RUNTIME_LEASE_CONFLICT to the old holder;
- release removes only the matching lease;
- corrupt/foreign lease files read as absent (fail closed to re-claim).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aisc.adapters.data_root_store import DataRootStore
from aisc.adapters.workspace_lease_store import LEASE_REL, WorkspaceLeaseStore
from aisc.application.data_root import DataRootResolver
from aisc.domain.models import CliError, RuntimeErrorCode
from aisc.domain.workspace_lease import (
    LEASE_TTL_SECONDS,
    WorkspaceLease,
    lease_from_dict,
)

INST_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INST_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _store(ws_tmp: str, root_tmp: str) -> DataRootStore:
    resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(Path(ws_tmp))
    store = DataRootStore(resolved)
    store.prepare()
    return store


def _lease_store(ws_tmp: str, root_tmp: str, key: str = "abcd1234") -> WorkspaceLeaseStore:
    return WorkspaceLeaseStore(_store(ws_tmp, root_tmp), key)


def _iso_ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class ClaimTests(unittest.TestCase):
    def test_first_claim_then_other_instance_blocked(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            lease, outcome = ls.claim(INST_A)
            self.assertEqual(outcome, "claimed")
            self.assertEqual(lease.workbench_instance_id, INST_A)

            with self.assertRaises(CliError) as ctx:
                ls.claim(INST_B)
            self.assertEqual(ctx.exception.error_code, RuntimeErrorCode.ACTIVE_WORKSPACE_LEASE)
            data = ctx.exception.data
            self.assertEqual(data["holder_instance_id"], INST_A)
            self.assertTrue(data["expires_at"])  # caller can show remaining time

    def test_same_instance_reclaim_is_idempotent(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            first, _ = ls.claim(INST_A)
            second, outcome = ls.claim(INST_A)
            self.assertEqual(outcome, "reclaimed")
            self.assertEqual(second.lease_id, first.lease_id)  # identity kept
            # ...and the same instance still blocks the other one.
            with self.assertRaises(CliError):
                ls.claim(INST_B)

    def test_expired_lease_is_taken_over(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            store = _store(ws, root)
            ls = WorkspaceLeaseStore(store, "abcd1234")
            # Pre-seed an expired lease (last seen TTL + margin ago).
            stale = WorkspaceLease(
                workspace_key="abcd1234", lease_id="old-lease",
                workbench_instance_id=INST_A,
                claimed_at=_iso_ago(LEASE_TTL_SECONDS + 60),
                lease_last_seen_at=_iso_ago(LEASE_TTL_SECONDS + 60),
            )
            store.write_json("workspace", LEASE_REL, stale.to_dict())
            lease, outcome = ls.claim(INST_B)
            self.assertEqual(outcome, "claimed_stale")
            self.assertEqual(lease.workbench_instance_id, INST_B)
            self.assertNotEqual(lease.lease_id, "old-lease")

    def test_claim_requires_instance_id(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            with self.assertRaises(CliError):
                ls.claim("")


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_refreshes_matching_lease(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            lease, _ = ls.claim(INST_A)
            aged = WorkspaceLease(
                workspace_key=lease.workspace_key, lease_id=lease.lease_id,
                workbench_instance_id=INST_A,
                claimed_at=lease.claimed_at,
                lease_last_seen_at=_iso_ago(LEASE_TTL_SECONDS / 2),
            )
            ls._write(aged)
            refreshed = ls.heartbeat(INST_A, lease.lease_id)
            self.assertIsNotNone(refreshed)
            self.assertLess(refreshed.age_seconds(), 5)

    def test_heartbeat_after_takeover_conflicts(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            lease, _ = ls.claim(INST_A)
            # Lease expires while A sleeps; B takes over.
            ls._write(WorkspaceLease(
                workspace_key="abcd1234", lease_id="old",
                workbench_instance_id=INST_A,
                claimed_at=_iso_ago(999), lease_last_seen_at=_iso_ago(999),
            ))
            ls.claim(INST_B)
            with self.assertRaises(CliError) as ctx:
                ls.heartbeat(INST_A, lease.lease_id)
            self.assertEqual(ctx.exception.error_code, RuntimeErrorCode.RUNTIME_LEASE_CONFLICT)

    def test_heartbeat_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            self.assertIsNone(ls.heartbeat(INST_A, "whatever"))


class ReleaseTests(unittest.TestCase):
    def test_release_only_matching_lease(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            ls = _lease_store(ws, root)
            lease, _ = ls.claim(INST_A)
            # Wrong instance / wrong lease id: no-op.
            self.assertFalse(ls.release(INST_B, lease.lease_id))
            self.assertFalse(ls.release(INST_A, "not-the-lease"))
            self.assertTrue(ls.release(INST_A, lease.lease_id))
            self.assertIsNone(ls.inspect())
            # Idempotent second release.
            self.assertFalse(ls.release(INST_A, lease.lease_id))


class DecodeTests(unittest.TestCase):
    def test_corrupt_and_foreign_files_read_as_absent(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as root:
            store = _store(ws, root)
            store.write_text("workspace", LEASE_REL, "{not json")
            ls = WorkspaceLeaseStore(store, "k")
            self.assertIsNone(ls.inspect())
            # ...and a fresh claim overwrites cleanly (the isolated file was
            # unreadable, so from claim's view the slot was empty).
            lease, outcome = ls.claim(INST_A)
            self.assertEqual(outcome, "claimed")
            self.assertEqual(ls.inspect().lease_id, lease.lease_id)

    def test_foreign_schema_fails_closed(self):
        self.assertIsNone(lease_from_dict({"schema": "something-else/v9"}))
        self.assertIsNone(lease_from_dict({"schema_version": 99}))
        self.assertIsNone(lease_from_dict("nope"))
        round_trip = lease_from_dict(
            WorkspaceLease("k", "l1", INST_A, "t1", "t2").to_dict()
        )
        self.assertEqual(
            (round_trip.workspace_key, round_trip.lease_id, round_trip.workbench_instance_id),
            ("k", "l1", INST_A),
        )

    def test_unparseable_last_seen_is_not_fresh(self):
        garbage_clock = WorkspaceLease("k", "l", INST_A, "", "not-a-timestamp")
        self.assertTrue(garbage_clock.is_expired())


if __name__ == "__main__":
    unittest.main()
