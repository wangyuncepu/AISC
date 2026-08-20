"""Concurrency regression tests for the container registry."""

import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from aisc.adapters.container_registry import (
    _registry_lock,
    list_containers,
    register,
    workspace_lock,
)
from aisc.domain.models import CliError, RuntimeErrorCode, RuntimeExitCode


def _register_after_start(root: str, name: str, start) -> None:
    start.wait()
    register(
        Path(root) / ".aisc",  # Stage 7: registry root = state dir itself
        name,
        {
            "image": "super-claude:test",
            "workspace": f"/workspace/{name}",
            "network": "direct",
            "label": name,
        },
    )


@unittest.skipUnless(os.name == "posix", "registry flock requires POSIX")
class ContainerRegistryConcurrencyTests(unittest.TestCase):
    def test_concurrent_registration_does_not_lose_entries(self):
        process_count = 16
        context = multiprocessing.get_context("fork")
        start = context.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            processes = [
                context.Process(
                    target=_register_after_start,
                    args=(temp_dir, f"container-{index}", start),
                )
                for index in range(process_count)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(timeout=10)

            exit_codes = [process.exitcode for process in processes]
            registered = list_containers(Path(temp_dir) / ".aisc")

        self.assertEqual(exit_codes, [0] * process_count)
        self.assertEqual(set(registered), {f"container-{i}" for i in range(process_count)})

    def test_registry_lock_timeout_maps_to_cli_error(self):
        """A registry lock timeout raises CliError(STATE_LOCK_TIMEOUT), not a
        bare TimeoutError/stack trace."""
        import fcntl

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".aisc").mkdir(parents=True, exist_ok=True)
            lock_path = root / ".aisc" / ".containers.lock"
            # Hold the lock on a separate fd so _registry_lock cannot acquire.
            holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(holder_fd, fcntl.LOCK_EX)
            try:
                with self.assertRaises(CliError) as cm:
                    with _registry_lock(root / ".aisc", timeout=1.0):
                        pass
                self.assertEqual(cm.exception.exit_code, RuntimeExitCode.STATE_LOCK_TIMEOUT)
                self.assertEqual(cm.exception.error_code, RuntimeErrorCode.STATE_LOCK_TIMEOUT)
            finally:
                fcntl.flock(holder_fd, fcntl.LOCK_UN)
                os.close(holder_fd)

    def test_workspace_lock_timeout_maps_to_cli_error(self):
        """A workspace lock timeout raises CliError(STATE_LOCK_TIMEOUT)."""
        import fcntl

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".aisc" / "workspace-locks").mkdir(parents=True, exist_ok=True)
            lock_path = root / ".aisc" / "workspace-locks" / "k.lock"
            holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(holder_fd, fcntl.LOCK_EX)
            try:
                with self.assertRaises(CliError) as cm:
                    with workspace_lock(root / ".aisc", "k", timeout=1.0):
                        pass
                self.assertEqual(cm.exception.exit_code, RuntimeExitCode.STATE_LOCK_TIMEOUT)
            finally:
                fcntl.flock(holder_fd, fcntl.LOCK_UN)
                os.close(holder_fd)


class RegisterDefaultAndImageIdTests(unittest.TestCase):
    """容器随镜像同步更新 (KI-4 挂账): the image_id whitelist key and the
    set_default=False heal mode (a metadata back-fill must not steal the
    registry's default target)."""

    def test_register_persists_image_id_and_set_default_false_keeps_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            register(root, "aisc-a", {
                "image": "super-claude:latest", "workspace": "/w", "network": "direct",
                "image_id": "sha256:v1",
            })
            register(root, "aisc-b", {
                "image": "super-claude:latest", "workspace": "/w", "network": "direct",
                "image_id": "sha256:v1",
            }, set_default=False)

            entries = list_containers(root)
            self.assertEqual(entries["aisc-a"]["image_id"], "sha256:v1")
            self.assertEqual(entries["aisc-b"]["image_id"], "sha256:v1")

            from aisc.adapters.container_registry import get_default
            self.assertEqual(get_default(root), "aisc-a")


if __name__ == "__main__":
    unittest.main()
