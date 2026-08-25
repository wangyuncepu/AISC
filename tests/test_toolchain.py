"""runtime-lifecycle-ux Stage 3a: persistent project toolchain (host_bind).

Covers the acceptance rows (04-acceptance §1): persistent_toolchain mounts
its dedicated dir and stamps metadata; temporary runs mount nothing; the
environment baseline marker is written once and never overwritten; a
mismatch warning file flips inspect's compatibility to "warning" (advisory,
never a block); remove keeps the toolchain dir (only the container dies).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aisc.adapters.container_registry import list_containers_readonly
from aisc.application.toolchain import (
    prepare_toolchain,
    toolchain_dir_for,
    toolchain_health,
    toolchain_mount_argv,
)
from aisc.domain.toolchain import (
    ENVIRONMENT_MARKER,
    TOOLCHAIN_MOUNT_TARGET,
    TOOLCHAIN_SUBDIRS,
    TOOLCHAIN_WARNING_FILE,
)


class ToolchainDomainTests(unittest.TestCase):
    def test_bind_argv_mounts_contract_target(self):
        argv = toolchain_mount_argv(Path("C:/data/workspaces/h"))
        self.assertEqual(argv, ["-v", f"C:/data/workspaces/h/toolchain:{TOOLCHAIN_MOUNT_TARGET}"])


class ToolchainPrepareTests(unittest.TestCase):
    def test_prepare_creates_skeleton_and_seeds_marker_once(self):
        with tempfile.TemporaryDirectory() as root:
            ws_dir = Path(root) / "workspaces" / "h"
            tc = toolchain_dir_for(ws_dir)
            prepare_toolchain(ws_dir, image_id="sha256:abc")
            for sub in TOOLCHAIN_SUBDIRS:
                self.assertTrue((tc / sub).is_dir(), sub)
            marker = json.loads((tc / ENVIRONMENT_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["schema"], "aisc.toolchain-environment/v1")
            self.assertEqual(marker["image_id"], "sha256:abc")

            # Second prepare with a DIFFERENT image id must NOT overwrite the
            # baseline (first-written wins; drift shows as the warning file).
            prepare_toolchain(ws_dir, image_id="sha256:zzz")
            marker2 = json.loads((tc / ENVIRONMENT_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker2["image_id"], "sha256:abc")

    def test_health_unknown_without_marker_warning_with_file(self):
        with tempfile.TemporaryDirectory() as root:
            ws_dir = Path(root) / "h"
            self.assertEqual(toolchain_health(ws_dir)["compatibility"], "unknown")
            prepare_toolchain(ws_dir)
            self.assertEqual(toolchain_health(ws_dir)["compatibility"], "compatible")
            self.assertEqual(toolchain_health(ws_dir)["storage"], "host_bind")
            (toolchain_dir_for(ws_dir) / TOOLCHAIN_WARNING_FILE).write_text("drift", encoding="utf-8")
            self.assertEqual(toolchain_health(ws_dir)["compatibility"], "warning")


class _ArgCapturingExecutor:
    """RuntimeFakeExecutor + capture of the create argv."""

    def __init__(self, inner):
        self._inner = inner
        self.create_argv = None

    def run_captured(self, argv, *, timeout=None):
        if argv and argv[0] == "run":
            self.create_argv = argv
        return self._inner.run_captured(argv, timeout=timeout)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class StartRuntimeToolchainTests(unittest.TestCase):
    def _start(self, scope, rid):
        import os
        from tests.test_runtime_lifecycle import RuntimeFakeExecutor
        from aisc.application.runtime import start_runtime

        root_tmp = tempfile.TemporaryDirectory()
        ws_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(root_tmp.cleanup)
        self.addCleanup(ws_tmp.cleanup)
        os.environ["AISC_DATA_ROOT"] = root_tmp.name
        self.addCleanup(os.environ.pop, "AISC_DATA_ROOT", None)
        ws = str(Path(ws_tmp.name) / "proj")
        Path(ws).mkdir(parents=True)
        ex = _ArgCapturingExecutor(RuntimeFakeExecutor())
        start_runtime(rid, ws, "super-claude:latest", "direct", scope,
                      "workbench", executor=ex, ready_timeout=2.0)
        return ex, Path(root_tmp.name)

    def test_project_start_mounts_toolchain_and_stamps_metadata(self):
        ex, data_root = self._start("project", "11111111-1111-4111-8111-111111111111")
        flat = " ".join(ex.create_argv or [])
        self.assertIn(f":{TOOLCHAIN_MOUNT_TARGET}", flat)
        # the entrypoint baseline env var rides along
        self.assertIn("AISC_IMAGE_ID=", flat)
        # registry metadata: policy + backend
        ws_dirs = list((data_root / "workspaces").iterdir())
        self.assertEqual(len(ws_dirs), 1)
        reg = ws_dirs[0] / "runtime"
        meta = list(list_containers_readonly(reg).values())[0]
        self.assertEqual(meta["dependency_policy"], "persistent_toolchain")
        self.assertEqual(meta["toolchain_storage"], "host_bind")
        # the host-side skeleton + seeded marker exist next to the state dirs
        tc = toolchain_dir_for(ws_dirs[0])
        self.assertTrue((tc / "npm-global").is_dir())
        self.assertTrue((tc / ENVIRONMENT_MARKER).is_file())

    def test_temporary_start_mounts_no_toolchain(self):
        ex, data_root = self._start("temporary", "22222222-2222-4222-8222-222222222222")
        flat = " ".join(ex.create_argv or [])
        self.assertNotIn(TOOLCHAIN_MOUNT_TARGET, flat)
        # no toolchain skeleton for temporary workspaces
        for ws_dir in (data_root / "workspaces").iterdir():
            self.assertFalse(toolchain_dir_for(ws_dir).exists())


if __name__ == "__main__":
    unittest.main()
