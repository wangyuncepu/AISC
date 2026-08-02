"""Concurrency regression tests for the container registry."""

import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from aisc.adapters.container_registry import list_containers, register


def _register_after_start(root: str, name: str, start) -> None:
    start.wait()
    register(
        Path(root),
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
            registered = list_containers(Path(temp_dir))

        self.assertEqual(exit_codes, [0] * process_count)
        self.assertEqual(set(registered), {f"container-{i}" for i in range(process_count)})


if __name__ == "__main__":
    unittest.main()
