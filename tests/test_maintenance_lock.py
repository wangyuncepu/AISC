"""docker-ownership-foundation A0: the Docker maintenance lock.

Contract (docker-resource-lifecycle 02-domain-contract.md §4.1):
- one cross-process lock at ``<data-root>/state/locks/docker-maintenance.lock``
  (the plans' ``<data-root>/locks/`` notation, resolved through the frozen
  DataRootStore layout — no invented sibling dirs);
- fail-closed acquisition: timeout raises AISC_ERR_MAINTENANCE_LOCK_TIMEOUT
  and the caller must not proceed;
- frozen order maintenance -> workspace -> registry (documented invariant;
  these tests pin the lock's identity and location so both plans consume
  the same one).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aisc.adapters.data_root_store import DataRootStore, file_lock
from aisc.adapters.maintenance_lock import (
    ERR_MAINTENANCE_LOCK_TIMEOUT,
    MAINTENANCE_LOCK_NAME,
    docker_maintenance_lock,
    maintenance_lock_path,
)
from aisc.application.data_root import DataRootResolver
from aisc.domain.data_root import LOCKS_SUBDIR
from aisc.domain.models import CliError


def _store(ws_tmp: str, root_tmp: str) -> DataRootStore:
    resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(Path(ws_tmp))
    store = DataRootStore(resolved)
    store.prepare()
    return store


class MaintenanceLockTests(unittest.TestCase):
    def test_lock_file_is_the_contract_path(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store = _store(ws_tmp, root_tmp)
            path = maintenance_lock_path(store)
            parts = LOCKS_SUBDIR.split("/")
            self.assertTrue(path.parent == store.locks_dir())
            self.assertEqual(path.name, f"{MAINTENANCE_LOCK_NAME}.lock")
            # Under <data-root>/state/locks/ — no invented top-level locks/ dir.
            self.assertEqual(path.parent.parent.name, parts[0])
            self.assertEqual(path.parent.name, parts[1])

    def test_acquisition_blocks_and_times_out_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store = _store(ws_tmp, root_tmp)
            with docker_maintenance_lock(store):
                # A second acquisition on the same path (as another process
                # would) must time out with the stable code, not proceed.
                with self.assertRaises(CliError) as ctx:
                    with file_lock(
                        maintenance_lock_path(store),
                        timeout=0.3,
                        error_code=ERR_MAINTENANCE_LOCK_TIMEOUT,
                    ):
                        pass
                self.assertEqual(ctx.exception.error_code, ERR_MAINTENANCE_LOCK_TIMEOUT)

    def test_reentrant_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store = _store(ws_tmp, root_tmp)
            with docker_maintenance_lock(store):
                pass
            # Immediately acquirable again after release (idempotent cycles:
            # scan -> cleanup -> rebuild in one installer run).
            with docker_maintenance_lock(store, timeout=2.0):
                pass


if __name__ == "__main__":
    unittest.main()


class StartCriticalSectionTests(unittest.TestCase):
    """C1b (02 §4.1): start_runtime's tag-resolution/create critical section
    holds the maintenance lock — a rebuild in flight blocks a racing start
    (and vice versa); order maintenance -> workspace is never reversed."""

    def test_start_blocks_while_rebuild_holds_the_lock(self):
        import os
        import tempfile
        import threading
        import time as _time
        from tests.test_runtime_lifecycle import RuntimeFakeExecutor
        from aisc.adapters.maintenance_lock import (
            docker_maintenance_lock_at_root,
        )
        from aisc.application.runtime import start_runtime

        with tempfile.TemporaryDirectory() as ws_tmp,                 tempfile.TemporaryDirectory() as root_tmp:
            os.environ["AISC_DATA_ROOT"] = root_tmp
            try:
                ws = str(Path(ws_tmp) / "proj")
                Path(ws).mkdir(parents=True)
                ex = RuntimeFakeExecutor()
                done = threading.Event()
                result = {}

                def run_start():
                    try:
                        start_runtime(
                            "33333333-3333-4333-8333-333333333333", ws,
                            "super-claude:latest", "direct", "project",
                            "workbench", executor=ex, ready_timeout=2.0,
                        )
                        result["ok"] = True
                    except Exception as exc:  # noqa: BLE001
                        result["error"] = exc
                    finally:
                        done.set()

                with docker_maintenance_lock_at_root(Path(root_tmp)):
                    t = threading.Thread(target=run_start)
                    t.start()
                    # While the (simulated) rebuild holds the lock, the start
                    # must NOT proceed — no container created yet.
                    _time.sleep(0.6)
                    self.assertFalse(done.is_set())
                    self.assertEqual(ex.containers, {})

                # Lock released -> the start completes.
                self.assertTrue(done.wait(timeout=10))
                t.join()
                self.assertIn("ok", result), result
                self.assertEqual(len(ex.containers), 1)
            finally:
                os.environ.pop("AISC_DATA_ROOT", None)
