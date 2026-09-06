"""PERF P5a (D-13): lock interop — Python-side negative control.

The full CROSS-RUNTIME matrix (Python's file_lock primitive vs Rust fs4,
both directions) lives in ``workbench/src-tauri/tests/lock_interop.rs`` —
the cargo lane spawns python for the other half, which the pytest lane
cannot assume. This file pins the python primitive's self-exclusion (the
baseline that makes the cross-runtime experiment meaningful) and documents
the fact chain:

- Python Windows: ``msvcrt.locking(LK_NBLCK, 1)`` — byte range [0,1)
- Python POSIX: ``fcntl.flock(fd, LOCK_EX)`` — BSD flock
- Rust fs4 Windows: LockFileEx over [0, u64::MAX) — overlapping range
- Rust fs4 POSIX: BSD flock (same syscall as fcntl.flock)

P5b (lease heartbeat direct write) is gated on the cargo-side experiment.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_CHILD = r"""
import os, sys, time
lock_path, hold_marker, release_wait = sys.argv[1], sys.argv[2], sys.argv[3]
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
if sys.platform == "win32":
    import msvcrt
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)
open(hold_marker, "w").close()
deadline = time.time() + 30
while not os.path.exists(release_wait) and time.time() < deadline:
    time.sleep(0.05)
"""


def _try_lock(lock_path: Path) -> bool:
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # noqa: F841 — raises when held
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Acquired: release immediately (unlock byte / close unlocks flock).
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


class PythonLockSelfExclusionTests(unittest.TestCase):
    def test_child_held_lock_blocks_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "self.lock"
            lock.touch()
            hold = Path(tmp) / "held"
            release = Path(tmp) / "release"
            child = subprocess.Popen(
                [sys.executable, "-c", _CHILD, str(lock), str(hold), str(release)],
                stdin=subprocess.DEVNULL,
            )
            try:
                for _ in range(200):
                    if hold.exists():
                        break
                    import time as _t

                    _t.sleep(0.025)
                self.assertTrue(hold.exists(), "child never took the lock")
                self.assertFalse(
                    _try_lock(lock),
                    "parent must be blocked while the child holds the lock",
                )
            finally:
                release.write_text("1")
                child.wait(timeout=30)
            self.assertTrue(_try_lock(lock), "lock must be free after release")


if __name__ == "__main__":
    unittest.main()
