"""Unit tests for container_registry adapter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisc.adapters.container_registry import (
    register,
    unregister,
    list_containers,
    resolve_target,
    gc,
)
from aisc.adapters.docker_ import FakeDockerExecutor
from aisc.domain.models import CliError, ProcessResult


class TestRegisterAndList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.reg_path = self.aisc_dir / "containers.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_register_sets_default(self):
        register(self.tmpdir, "test-123", {
            "image": "img:v1", "workspace": "/ws",
            "network": "direct", "label": "app",
        })
        data = json.loads(self.reg_path.read_text())
        self.assertEqual(data["default"], "test-123")
        self.assertIn("test-123", data["containers"])
        self.assertEqual(data["containers"]["test-123"]["label"], "app")

    def test_register_overwrites_same_name(self):
        register(self.tmpdir, "test-123", {"image": "old", "workspace": "/w",
                                            "network": "d", "label": ""})
        register(self.tmpdir, "test-123", {"image": "new", "workspace": "/w",
                                            "network": "d", "label": "x"})
        data = json.loads(self.reg_path.read_text())
        self.assertEqual(data["containers"]["test-123"]["image"], "new")
        self.assertEqual(data["containers"]["test-123"]["label"], "x")

    def test_unregister_removes_and_repoints_default(self):
        register(self.tmpdir, "a", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        register(self.tmpdir, "b", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        self.assertEqual(json.loads(self.reg_path.read_text())["default"], "b")
        unregister(self.tmpdir, "b")
        data = json.loads(self.reg_path.read_text())
        self.assertEqual(data["default"], "a")
        self.assertNotIn("b", data["containers"])

    def test_unregister_last_clears_default(self):
        register(self.tmpdir, "sole", {"image": "i", "workspace": "/w",
                                        "network": "d", "label": ""})
        unregister(self.tmpdir, "sole")
        data = json.loads(self.reg_path.read_text())
        self.assertEqual(data["default"], "")
        self.assertEqual(data["containers"], {})

    def test_unregister_nonexistent_noop(self):
        register(self.tmpdir, "a", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        unregister(self.tmpdir, "bogus")
        data = json.loads(self.reg_path.read_text())
        self.assertEqual(data["default"], "a")

    def test_list_containers_empty(self):
        self.assertEqual(list_containers(self.tmpdir), {})

    def test_list_containers_multi(self):
        register(self.tmpdir, "a", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        register(self.tmpdir, "b", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        self.assertEqual(len(list_containers(self.tmpdir)), 2)


class TestResolveTarget(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _register(self, name, **kw):
        defaults = {"image": "i", "workspace": "/w", "network": "d", "label": ""}
        defaults.update(kw)
        register(self.tmpdir, name, defaults)

    def test_name_override(self):
        self.assertEqual(
            resolve_target(root=self.tmpdir, name_override="x", executor=self.executor),
            "x",
        )

    def test_label_override_unique(self):
        self._register("a", label="app")
        self._register("b", label="db")
        self.assertEqual(
            resolve_target(root=self.tmpdir, label_override="app",
                           executor=self.executor),
            "a",
        )

    def test_label_override_multi_raises(self):
        self._register("a", label="app")
        self._register("b", label="app")
        with self.assertRaises(CliError) as ctx:
            resolve_target(root=self.tmpdir, label_override="app",
                           executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_MULTIPLE_CONTAINERS")

    def test_label_override_not_found_raises(self):
        self._register("a", label="app")
        with self.assertRaises(CliError) as ctx:
            resolve_target(root=self.tmpdir, label_override="nope",
                           executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_default_pointer(self):
        self._register("a")
        self._register("b")
        self.assertEqual(
            resolve_target(root=self.tmpdir, executor=self.executor),
            "b",
        )

    def test_single_container(self):
        self._register("lonely")
        # No default set — still resolves because only one
        data = json.loads((self.tmpdir / ".aisc" / "containers.json").read_text())
        data["default"] = ""
        (self.tmpdir / ".aisc" / "containers.json").write_text(json.dumps(data))
        self.assertEqual(
            resolve_target(root=self.tmpdir, executor=self.executor),
            "lonely",
        )

    def test_multiple_no_hint_raises(self):
        self._register("a")
        self._register("b")
        # Clear default
        data = json.loads((self.tmpdir / ".aisc" / "containers.json").read_text())
        data["default"] = ""
        (self.tmpdir / ".aisc" / "containers.json").write_text(json.dumps(data))
        with self.assertRaises(CliError) as ctx:
            resolve_target(root=self.tmpdir, executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_MULTIPLE_CONTAINERS")

    def test_empty_registry_raises(self):
        with self.assertRaises(CliError) as ctx:
            resolve_target(root=self.tmpdir, executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_name_override_bypasses_registry(self):
        # Name not in registry but still returned (caller's cmd_status verifies)
        self.assertEqual(
            resolve_target(root=self.tmpdir, name_override="outside",
                           executor=self.executor),
            "outside",
        )


class TestGC(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gc_prunes_dead_container(self):
        register(self.tmpdir, "alive", {"image": "i", "workspace": "/w",
                                         "network": "d", "label": ""})
        register(self.tmpdir, "dead", {"image": "i", "workspace": "/w",
                                        "network": "d", "label": ""})
        exec_ = FakeDockerExecutor()
        exec_.set_captured("inspect", ProcessResult(
            stdout="/alive\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        # Override for "dead" container specifically
        def _captured(argv, timeout=None):
            if "dead" in argv:
                return ProcessResult(stdout="", stderr="No such object: dead\n", exit_code=1)
            return ProcessResult(stdout="/alive\ttrue\trunning\timg\tid\n",
                                 stderr="", exit_code=0)
        exec_.run_captured = _captured  # type: ignore
        pruned = gc(self.tmpdir, exec_)
        self.assertEqual(pruned, ["dead"])
        data = json.loads((self.tmpdir / ".aisc" / "containers.json").read_text())
        self.assertNotIn("dead", data["containers"])
        self.assertIn("alive", data["containers"])

    def test_gc_daemon_unreachable_skips(self):
        register(self.tmpdir, "a", {"image": "i", "workspace": "/w",
                                     "network": "d", "label": ""})
        exec_ = FakeDockerExecutor()
        exec_.set_captured("inspect", ProcessResult(
            stdout="", stderr="Cannot connect to the Docker daemon\n", exit_code=1,
        ))
        pruned = gc(self.tmpdir, exec_)
        self.assertEqual(pruned, [])
        data = json.loads((self.tmpdir / ".aisc" / "containers.json").read_text())
        self.assertIn("a", data["containers"])

    def test_gc_empty_registry_noop(self):
        exec_ = FakeDockerExecutor()
        self.assertEqual(gc(self.tmpdir, exec_), [])