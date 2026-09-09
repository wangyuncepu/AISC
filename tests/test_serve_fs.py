"""2.1.10 R3 (D-9): serve fs.* ops — containment, ignore parity, pagination,
write atomicity, watch events (registry level; watchdog present on dev/CI
Linux, skipped cleanly elsewhere)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from aisc.cli.commands import serve_fs
from aisc.domain.models import CliError


class FsResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_relative_resolution(self) -> None:
        self.assertEqual(serve_fs._resolve(self.root, ""), self.root)
        # fs.* paths are POSIX-joined (forward slashes ride through on every
        # host); compare component-wise so the assertion is not a Windows
        # separator ping-pong (pre-existing Linux-only green — fixed 2026-09-09).
        self.assertEqual(
            Path(serve_fs._resolve(self.root, "a/b.txt")).parts,
            Path(os.path.join(self.root, "a", "b.txt")).parts,
        )

    def test_dotdot_escape_rejected(self) -> None:
        with self.assertRaises(CliError) as ctx:
            serve_fs._resolve(self.root, "../outside")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_FS_CONTAINMENT")

    def test_absolute_input_rejected(self) -> None:
        with self.assertRaises(CliError) as ctx:
            serve_fs._resolve(self.root, "/etc/passwd")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_FS_PATH")


class FsOpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "sub").mkdir()
        (self.root / "a.txt").write_text("hello-r3", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "x.js").write_text("x", encoding="utf-8")
        (self.root / "b.tmp").write_text("t", encoding="utf-8")
        self.rt = None  # fs ops that need runtime get it from these tests

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _list(self, path="", offset=None):
        args = {"root": str(self.root), "path": path}
        if offset is not None:
            args["offset"] = offset
        data, code, errs = serve_fs.op_fs_list(None, args, None)
        self.assertEqual(code, 0, errs)
        return data

    def test_list_ignores_match_explorer(self) -> None:
        data = self._list()
        names = [e["name"] for e in data["entries"]]
        self.assertIn("a.txt", names)
        self.assertIn("sub", names)
        self.assertNotIn("node_modules", names, "ignore parity with DEFAULT_IGNORE")
        self.assertNotIn("b.tmp", names, "temp files never surface")

    def test_list_pagination(self) -> None:
        for i in range(serve_fs.LIST_PAGE + 5):
            (self.root / f"f{i:04}.txt").write_text(str(i), encoding="utf-8")
        page1 = self._list()
        self.assertIn("nextOffset", page1)
        page2 = self._list(offset=page1["nextOffset"])
        self.assertGreater(len(page2["entries"]), 0)
        total = len(page1["entries"]) + len(page2["entries"])
        # 4 pre-existing + 205 new − 2 ignored (node_modules, b.tmp)
        self.assertEqual(total, 4 + serve_fs.LIST_PAGE + 5 - 2)
        self.assertNotIn("nextOffset", page2)

    def test_read_roundtrip_and_budget(self) -> None:
        data, code, errs = serve_fs.op_fs_read(
            None, {"root": str(self.root), "path": "a.txt"}, None)
        self.assertEqual(code, 0, errs)
        import base64

        self.assertEqual(base64.b64decode(data["base64"]), b"hello-r3")
        self.assertFalse(data["truncated"])
        small = serve_fs.op_fs_read(
            None, {"root": str(self.root), "path": "a.txt", "maxBytes": 3}, None)[0]
        self.assertTrue(small["truncated"])
        self.assertEqual(small["size"], 8)

    def test_write_then_read_back(self) -> None:
        import base64

        blob = base64.b64encode("写入内容".encode("utf-8")).decode()
        data, code, errs = serve_fs.op_fs_write(
            None, {"root": str(self.root), "path": "sub/new.txt", "base64": blob}, None)
        self.assertEqual(code, 0, errs)
        self.assertEqual(data["bytes"], len("写入内容".encode()))
        self.assertTrue((self.root / "sub" / "new.txt").exists())
        # atomic residue never survives
        self.assertFalse(any(p.name.endswith(".aisc-tmp")
                             for p in self.root.rglob("*")))

    def test_mkdir_rename_delete(self) -> None:
        serve_fs.op_fs_mkdir(None, {"root": str(self.root), "path": "d1/d2"}, None)
        self.assertTrue((self.root / "d1" / "d2").is_dir())
        serve_fs.op_fs_rename(
            None, {"root": str(self.root), "from": "a.txt", "to": "d1/moved.txt"}, None)
        self.assertFalse((self.root / "a.txt").exists())
        self.assertTrue((self.root / "d1" / "moved.txt").exists())
        serve_fs.op_fs_delete(None, {"root": str(self.root), "path": "d1"}, None)
        self.assertFalse((self.root / "d1").exists())

    def test_delete_root_refused(self) -> None:
        with self.assertRaises(CliError) as ctx:
            serve_fs.op_fs_delete(None, {"root": str(self.root), "path": ""}, None)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_FS_CONTAINMENT")

    def test_rename_escape_rejected(self) -> None:
        with self.assertRaises(CliError):
            serve_fs.op_fs_rename(
                None, {"root": str(self.root),
                       "from": "a.txt", "to": "../stolen.txt"}, None)


class WatchRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.events: list = []
        from aisc.cli.commands.serve_fs import WatchRegistry

        self.reg = WatchRegistry(lambda f: self.events.append(f))

    def tearDown(self) -> None:
        self.reg.shutdown()
        self._tmp.cleanup()

    def test_watch_emits_batched_fs_change(self) -> None:
        if not self.reg.available():
            self.skipTest("watchdog unavailable")
        self.reg.watch(self.root)
        time.sleep(0.2)
        with open(os.path.join(self.root, "w1.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(os.path.join(self.root, "wdir"), exist_ok=True)
        time.sleep(0.5)
        self.reg.shutdown()
        frames = [e for e in self.events if e["event"] == "fs.change"]
        self.assertTrue(frames, "no fs.change frame")
        paths = {p["path"].split("/")[-1] for fr in frames for p in fr["data"]["paths"]}
        self.assertIn("w1.txt", paths)
        self.assertIn("wdir", paths)
        # atomic-write residue never surfaces
        self.assertNotIn("w1.txt.aisc-tmp", paths)

    def test_watch_op_requires_absolute_root(self) -> None:
        with self.assertRaises(CliError) as ctx:
            serve_fs.op_fs_watch(None, {"root": "relative/path"}, None)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_FS_PATH")


if __name__ == "__main__":
    unittest.main()
