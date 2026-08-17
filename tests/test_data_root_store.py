"""Stage 7 (7b): unified data-root storage adapter tests.

Covers (04-observability-testing, filesystem/migration rows):
- prepare creates the exact contract skeleton, idempotently;
- validated rel paths (no ``..``/absolute/backslash escape);
- atomic JSON round-trip leaves no temp files, replaces cleanly;
- corrupt JSON is isolated to ``*.corrupt`` and reads fail closed;
- locks: cross-process exclusion with bounded timeout and a stable code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aisc.adapters.data_root_store import (
    SCOPE_SHARED,
    SCOPE_WORKSPACE,
    DataRootStore,
    file_lock,
)
from aisc.application.data_root import DataRootResolver
from aisc.domain.data_root import (
    ERR_LOCK_TIMEOUT,
    SHARED_SUBDIRS,
    WORKSPACE_SUBDIRS,
    workspace_dir_name,
)
from aisc.domain.models import CliError


def _store(ws_tmp: str, root_tmp: str) -> tuple[DataRootStore, Path, Path]:
    resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(Path(ws_tmp))
    return DataRootStore(resolved), Path(root_tmp), Path(ws_tmp)


class PrepareTests(unittest.TestCase):
    def test_prepare_creates_contract_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, ws = _store(ws_tmp, root_tmp)
            store.prepare()
            for name in SHARED_SUBDIRS:
                self.assertTrue((root / name).is_dir(), name)
            # The real workspace dir (from the resolver, not a fake hash).
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(ws)
            ws_dir = resolved.workspace_dir
            self.assertTrue(ws_dir.is_dir())
            for name in WORKSPACE_SUBDIRS:
                self.assertTrue((ws_dir / name).is_dir(), name)
            self.assertTrue((root / "state" / "locks").is_dir())

    def test_prepare_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, _, _ = _store(ws_tmp, root_tmp)
            store.prepare()
            store.prepare()  # no error, no duplication
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(Path(ws_tmp))
            self.assertTrue(resolved.workspace_dir.is_dir())


class PathValidationTests(unittest.TestCase):
    def test_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, _, _ = _store(ws_tmp, root_tmp)
            for bad in ("../escape.json", "..", "a/../../b", "/abs", "C:\\abs", "back\\slash"):
                with self.subTest(bad):
                    with self.assertRaises(ValueError):
                        store.path_for(SCOPE_SHARED, bad)

    def test_unknown_scope_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, _, _ = _store(ws_tmp, root_tmp)
            with self.assertRaises(ValueError):
                store.path_for("elsewhere", "x.json")


class AtomicWriteTests(unittest.TestCase):
    def test_json_round_trip_both_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, ws = _store(ws_tmp, root_tmp)
            store.write_json(SCOPE_SHARED, "config/settings.json", {"v": 1})
            store.write_json(SCOPE_WORKSPACE, "runtime/probe.json", {"ok": True})
            self.assertEqual(
                json.loads((root / "config" / "settings.json").read_text("utf-8")), {"v": 1}
            )
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp}).resolve(ws)
            self.assertEqual(
                json.loads(
                    (resolved.workspace_dir / "runtime" / "probe.json").read_text("utf-8")
                ),
                {"ok": True},
            )

    def test_no_temp_files_and_overwrite_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, _ = _store(ws_tmp, root_tmp)
            store.write_json(SCOPE_SHARED, "state/x.json", {"a": 1})
            store.write_json(SCOPE_SHARED, "state/x.json", {"a": 2})
            leftovers = [p.name for p in (root / "state").iterdir() if p.name.startswith(".")]
            self.assertEqual(leftovers, [])
            self.assertEqual(store.read_json(SCOPE_SHARED, "state/x.json"), {"a": 2})

    def test_missing_read_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, _, _ = _store(ws_tmp, root_tmp)
            self.assertIsNone(store.read_json(SCOPE_SHARED, "state/absent.json"))
            self.assertIsNone(store.read_text(SCOPE_SHARED, "state/absent.json"))

    def test_corrupt_json_isolated_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, _ = _store(ws_tmp, root_tmp)
            target = root / "state" / "broken.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{not json", encoding="utf-8")
            self.assertIsNone(store.read_json(SCOPE_SHARED, "state/broken.json"))
            self.assertFalse(target.exists())  # moved, not truncated
            corrupt = root / "state" / "broken.json.corrupt"
            self.assertTrue(corrupt.is_file())
            self.assertEqual(corrupt.read_text("utf-8"), "{not json")


class LockTests(unittest.TestCase):
    def test_lock_file_lives_under_state_locks(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, _ = _store(ws_tmp, root_tmp)
            with store.lock("containers"):
                lock_file = root / "state" / "locks" / "containers.lock"
                self.assertTrue(lock_file.is_file())
            # Released: another acquire succeeds immediately.
            with store.lock("containers"):
                pass

    def test_workspace_scoped_lock_name(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, root, _ = _store(ws_tmp, root_tmp)
            path = store.lock_path_for("containers", scope=SCOPE_WORKSPACE)
            name = path.name
            self.assertTrue(name.startswith("sha256-v1-"))
            self.assertTrue(name.endswith("-containers.lock"))
            self.assertEqual(path.parent, root / "state" / "locks")

    def test_cross_process_timeout_then_release(self) -> None:
        """A subprocess holds the lock; this process fails closed with the
        stable code, then acquires once the holder exits."""
        with tempfile.TemporaryDirectory() as root_tmp:
            lock_file = Path(root_tmp) / "hold.lock"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time\n"
                        "from aisc.adapters.data_root_store import file_lock\n"
                        f"lock = file_lock({str(lock_file)!r}, 5.0)\n"
                        "lock.__enter__()\n"
                        "print('held', flush=True)\n"
                        "time.sleep(2)\n"
                    ),
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "held")
                with self.assertRaises(CliError) as ctx:
                    with file_lock(lock_file, 0.5):
                        pass
                self.assertEqual(ctx.exception.error_code, ERR_LOCK_TIMEOUT)
                # After the holder exits, acquisition succeeds.
                self.assertEqual(holder.wait(timeout=10), 0)
                with file_lock(lock_file, 5.0):
                    pass
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=10)

    def test_write_with_lock_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            store, _, _ = _store(ws_tmp, root_tmp)
            store.write_json(SCOPE_SHARED, "state/idx.json", {"n": 1}, lock="index")
            self.assertEqual(store.read_json(SCOPE_SHARED, "state/idx.json"), {"n": 1})


if __name__ == "__main__":
    unittest.main()
