"""runtime-lifecycle-ux Stage 1: workspace reconcile classification matrix.

One test per 02-domain-contract.md §3 classification + the acceptance rows
(04-acceptance.md §1): auto-recycle only owner=workbench ephemeral/legacy
runtimes after lease verification; unknown owners and non-workbench owners
fail closed; Docker unavailable never concludes "not_found"; stale-registry
pruning is idempotent (second pass sees clean).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aisc.adapters.container_registry import list_containers_readonly, register
from aisc.application.runtime import workspace_key_for
from aisc.application.workspace_reconcile import reconcile_workspace
from aisc.domain.models import ProcessResult, RuntimeErrorCode
from aisc.domain.workspace_lease import LEASE_TTL_SECONDS, WorkspaceLease

INST_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INST_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RID = "11111111-1111-4111-8111-111111111111"


def _iso_ago(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class ReconcileFakeExecutor:
    """Duck-typed executor: preflight + ps label query + stop/remove/inspect."""

    def __init__(self, containers=None, available=True):
        # containers: {name: {"status": "Up 2 hours", "runtime_id": RID,
        #                     "owner": "workbench"}}
        self.containers = dict(containers or {})
        self.available = available
        self.stopped = []
        self.removed = []
        self.fail_remove = False

    # -- probes -------------------------------------------------------------

    def preflight(self):
        class R:
            pass
        r = R()
        r.available = self.available
        return r

    def run_captured(self, argv, timeout=None):
        if argv[0] == "ps":
            lines = []
            for name, c in self.containers.items():
                lines.append(
                    f"cid-{name[:6]}\t{name}\t{c['status']}\t"
                    f"{c.get('runtime_id', '')}\t{c.get('owner', '')}"
                )
            return ProcessResult(exit_code=0, stdout="\n".join(lines))
        raise AssertionError(f"unexpected argv {argv}")

    def inspect_container(self, name):
        if name not in self.containers:
            return ProcessResult(exit_code=1, stderr="Error: No such object: " + name)
        return ProcessResult(exit_code=0, stdout="[]")

    # -- mutations ------------------------------------------------------------

    def stop_container(self, name, timeout=10):
        self.stopped.append(name)
        self.containers[name]["status"] = "Exited (0) 1 second ago"
        return ProcessResult(exit_code=0)

    def remove_container(self, name, force=False):
        if self.fail_remove:
            return ProcessResult(exit_code=1, stderr="docker: driver refuses")
        self.removed.append(name)
        self.containers.pop(name, None)
        return ProcessResult(exit_code=0)


class ReconcileTestBase(unittest.TestCase):
    def setUp(self):
        self._ws = tempfile.TemporaryDirectory()
        self._root = tempfile.TemporaryDirectory()
        self.ws = str(Path(self._ws.name) / "proj")
        Path(self.ws).mkdir(parents=True)
        self.data_root = self._root.name
        self.ws_key = workspace_key_for(self.ws)
        # Registry root mirrors the production default (data-root
        # workspaces/<hash>/runtime) — reconcile resolves it itself; we
        # seed entries through the same resolver.
        from aisc.application.data_root import DataRootResolver
        from aisc.adapters.data_root_store import DataRootStore

        resolved = DataRootResolver(env={"AISC_DATA_ROOT": self.data_root}).resolve(Path(self.ws))
        store = DataRootStore(resolved)
        store.prepare()
        self.reg_root = resolved.workspace_dir / "runtime"
        self.reg_root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._ws.cleanup)
        self.addCleanup(self._root.cleanup)

    def reconcile(self, executor, instance_id=INST_A):
        return reconcile_workspace(
            self.ws, instance_id, executor,
            registry_root=self.reg_root,
            env={"AISC_DATA_ROOT": self.data_root},
        )

    def seed_registry(self, name, *, owner="workbench", lifecycle="ephemeral",
                      retention="remove_on_close", runtime_id=RID, workspace_key=None):
        register(self.reg_root, name, {
            "image": "super-claude:latest",
            "workspace": self.ws,
            "runtime_id": runtime_id,
            "owner": owner,
            "scope": "project",
            "config_fingerprint": "f" * 64,
            "container_id": "cid",
            "workspace_key": workspace_key or self.ws_key,
            **({"lifecycle": lifecycle} if lifecycle is not None else {}),
            **({"retention": retention} if retention is not None else {}),
        })

    def seed_lease(self, instance_id, *, age_seconds=0.0):
        from aisc.adapters.data_root_store import DataRootStore
        from aisc.adapters.workspace_lease_store import LEASE_REL, WorkspaceLeaseStore
        from aisc.application.data_root import DataRootResolver

        resolved = DataRootResolver(env={"AISC_DATA_ROOT": self.data_root}).resolve(Path(self.ws))
        store = DataRootStore(resolved)
        store.prepare()
        WorkspaceLeaseStore(store, self.ws_key)._write(WorkspaceLease(
            workspace_key=self.ws_key, lease_id="lease-x",
            workbench_instance_id=instance_id,
            claimed_at=_iso_ago(max(age_seconds, 0.01)),
            lease_last_seen_at=_iso_ago(max(age_seconds, 0.01)),
        ))


class ClassificationTests(ReconcileTestBase):
    def test_clean_workspace(self):
        r = self.reconcile(ReconcileFakeExecutor())
        self.assertEqual(r["classification"], "clean")
        self.assertTrue(r["can_proceed"])
        self.assertEqual(r["cleanup"], {"attempted": False, "stopped": False,
                                        "removed": False, "registry_pruned": False})

    def test_stale_ephemeral_running_is_recycled(self):
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Up 3 hours", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "stale_ephemeral")
        self.assertTrue(r["can_proceed"])
        self.assertTrue(r["cleanup"]["stopped"])
        self.assertTrue(r["cleanup"]["removed"])
        self.assertTrue(r["cleanup"]["registry_pruned"])
        self.assertEqual(ex.stopped, ["aisc-wb-11111111"])
        self.assertEqual(list_containers_readonly(self.reg_root), {})

    def test_stale_ephemeral_stopped_removed_without_stop(self):
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Exited (0) 2 minutes ago", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "stale_ephemeral")
        self.assertEqual(ex.stopped, [])
        self.assertEqual(ex.removed, ["aisc-wb-11111111"])

    def test_legacy_record_without_lifecycle_is_recycled(self):
        # Product table row 3: old-version record, owner provable → stale.
        self.seed_registry("aisc-wb-11111111", lifecycle=None, retention=None)
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Exited (0)", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "stale_ephemeral")
        self.assertEqual(ex.removed, ["aisc-wb-11111111"])

    def test_stale_registry_prune_is_idempotent(self):
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor()  # no container in Docker at all
        first = self.reconcile(ex)
        self.assertEqual(first["classification"], "stale_registry")
        self.assertTrue(first["cleanup"]["registry_pruned"])
        self.assertEqual(first["can_proceed"], True)
        self.assertEqual(ex.removed, [])
        # Second pass: registry empty now → clean.
        second = self.reconcile(ex)
        self.assertEqual(second["classification"], "clean")

    def test_non_workbench_owner_blocks_and_is_kept(self):
        self.seed_registry("aisc-wb-22222222", owner="cli")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-22222222": {"status": "Up", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "unknown_owner")
        self.assertFalse(r["can_proceed"])
        self.assertEqual(r["error_code"], RuntimeErrorCode.RUNTIME_OWNER_UNKNOWN)
        self.assertEqual(ex.removed, [])
        self.assertEqual(ex.stopped, [])
        # registry untouched
        self.assertIn("aisc-wb-22222222", list_containers_readonly(self.reg_root))

    def test_missing_owner_blocks(self):
        self.seed_registry("aisc-wb-33333333", owner="")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-33333333": {"status": "Exited (0)", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "unknown_owner")
        self.assertEqual(ex.removed, [])

    def test_keep_retention_is_kept_but_not_blocking(self):
        self.seed_registry("aisc-wb-44444444", retention="keep_stopped")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-44444444": {"status": "Exited (0)", "runtime_id": RID},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "clean")
        self.assertEqual(ex.removed, [])

    def test_docker_only_labeled_container_is_removed(self):
        # No registry entry, but the container carries the workspace-key
        # label with owner=workbench — labels prove ownership (lease expired).
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-55555555": {"status": "Up", "runtime_id": RID, "owner": "workbench"},
        })
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "stale_ephemeral")
        self.assertEqual(ex.removed, ["aisc-wb-55555555"])

    def test_docker_unavailable_does_nothing(self):
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(
            containers={"aisc-wb-11111111": {"status": "Up", "runtime_id": RID}},
            available=False,
        )
        r = self.reconcile(ex)
        self.assertEqual(r["classification"], "docker_unavailable")
        self.assertFalse(r["can_proceed"])
        self.assertEqual(r["error_code"], RuntimeErrorCode.DOCKER_UNAVAILABLE)
        self.assertEqual(ex.removed, [])
        self.assertIn("aisc-wb-11111111", list_containers_readonly(self.reg_root))

    def test_remove_failure_fails_closed(self):
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Exited (0)", "runtime_id": RID},
        })
        ex.fail_remove = True
        r = self.reconcile(ex)
        self.assertFalse(r["can_proceed"])
        self.assertEqual(r["error_code"], RuntimeErrorCode.RUNTIME_RECONCILE_FAILED)
        # registry NOT pruned on failure
        self.assertIn("aisc-wb-11111111", list_containers_readonly(self.reg_root))


class LeaseInteractionTests(ReconcileTestBase):
    def test_fresh_lease_same_instance_short_circuits(self):
        self.seed_lease(INST_A)
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Up", "runtime_id": RID},
        })
        r = self.reconcile(ex, instance_id=INST_A)
        self.assertEqual(r["classification"], "active_same_instance")
        self.assertFalse(r["can_proceed"])
        self.assertEqual(ex.removed, [])

    def test_fresh_lease_other_instance_blocks(self):
        self.seed_lease(INST_B)
        ex = ReconcileFakeExecutor()
        r = self.reconcile(ex, instance_id=INST_A)
        self.assertEqual(r["classification"], "active_other_instance")
        self.assertFalse(r["can_proceed"])
        self.assertEqual(r["error_code"], RuntimeErrorCode.ACTIVE_WORKSPACE_LEASE)

    def test_expired_lease_does_not_block_and_takes_over_recycling(self):
        self.seed_lease(INST_B, age_seconds=LEASE_TTL_SECONDS + 120)
        self.seed_registry("aisc-wb-11111111")
        ex = ReconcileFakeExecutor(containers={
            "aisc-wb-11111111": {"status": "Exited (0)", "runtime_id": RID},
        })
        r = self.reconcile(ex, instance_id=INST_A)
        self.assertEqual(r["classification"], "stale_ephemeral")
        self.assertTrue(r["can_proceed"])
        self.assertEqual(ex.removed, ["aisc-wb-11111111"])


if __name__ == "__main__":
    unittest.main()
