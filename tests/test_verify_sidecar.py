"""CLI-A07: sidecar manifest / hash / atomic-upgrade rollback logic.

The pure decision logic of scripts/verify-sidecar.py — sha256+size manifest,
arch-from-triple, and the atomic replace-with-rollback — is unit-tested here
without a real CLI binary (run_smoke is monkeypatched for the swap paths).
The real sidecar is exercised by the script itself and by CI.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify-sidecar.py"


def _load_vs():
    spec = importlib.util.spec_from_file_location("verify_sidecar", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_sidecar"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


vs = _load_vs()


class ArchOfTripleTests(unittest.TestCase):
    def test_arm64_from_aarch64(self):
        self.assertEqual(vs.arch_of_triple("aarch64-apple-darwin"), "arm64")
        self.assertEqual(vs.arch_of_triple("aarch64-unknown-linux-gnu"), "arm64")

    def test_x86_64_otherwise(self):
        self.assertEqual(vs.arch_of_triple("x86_64-pc-windows-msvc"), "x86_64")
        self.assertEqual(vs.arch_of_triple("x86_64-unknown-linux-gnu"), "x86_64")


class ManifestTests(unittest.TestCase):
    def _make_file(self, data: bytes) -> Path:
        handle, path = tempfile.mkstemp(suffix=".bin")
        with open(handle, "wb") as f:
            f.write(data)
        return Path(path)

    def test_manifest_round_trip(self):
        data = b"\x00\x01\x02sidecar-bytes" * 1000
        p = self._make_file(data)
        self.addCleanup(p.unlink, missing_ok=True)
        m = vs.make_manifest(p, "2.1.5.dev0", "x86_64-pc-windows-msvc")
        self.assertEqual(m["schema_version"], 1)
        self.assertEqual(m["triple"], "x86_64-pc-windows-msvc")
        self.assertEqual(m["arch"], "x86_64")
        self.assertEqual(m["version"], "2.1.5.dev0")
        self.assertEqual(m["size"], len(data))
        self.assertEqual(m["sha256"], hashlib.sha256(data).hexdigest())
        ok, reason = vs.check_manifest(p, m)
        self.assertTrue(ok, reason)

    def test_check_rejects_corrupted_binary(self):
        p = self._make_file(b"original")
        self.addCleanup(p.unlink, missing_ok=True)
        m = vs.make_manifest(p, "2.1.5.dev0", "x86_64-pc-windows-msvc")
        p.write_bytes(b"corrupted-bytes")
        ok, reason = vs.check_manifest(p, m)
        self.assertFalse(ok)
        self.assertIn("sha256", reason)


class AtomicUpgradeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="aisc-sidecar-test-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _binary(self, name: str, data: bytes) -> Path:
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def _manifest_for(self, binary: Path) -> dict:
        return vs.make_manifest(binary, "2.1.5.dev0", "x86_64-pc-windows-msvc")

    def test_rejects_bad_hash_before_touching_target(self):
        target = self._binary("aisc.exe", b"old-version")
        incoming = self._binary("incoming.exe", b"new-version")
        manifest = self._manifest_for(incoming)
        manifest["sha256"] = "0" * 64  # corrupt the promised hash

        ok, reason = vs.atomic_upgrade(incoming, manifest, target)
        self.assertFalse(ok)
        self.assertIn("reject", reason)
        # target untouched, no backup produced
        self.assertEqual(target.read_bytes(), b"old-version")
        self.assertFalse(target.with_name("aisc.exe.bak").exists())

    def test_success_replaces_target_and_keeps_backup(self, monkeypatch=None):
        target = self._binary("aisc.exe", b"old-version")
        incoming = self._binary("incoming.exe", b"new-version")
        manifest = self._manifest_for(incoming)
        original_smoke = vs.run_smoke
        vs.run_smoke = lambda binary: {"version": "2.1.5.dev0"}  # verify passes
        try:
            ok, reason = vs.atomic_upgrade(incoming, manifest, target)
        finally:
            vs.run_smoke = original_smoke
        self.assertTrue(ok, reason)
        self.assertEqual(target.read_bytes(), b"new-version")
        self.assertEqual(target.with_name("aisc.exe.bak").read_bytes(), b"old-version")

    def test_post_swap_failure_rolls_back_to_previous_version(self):
        target = self._binary("aisc.exe", b"old-version")
        incoming = self._binary("incoming.exe", b"new-version")
        manifest = self._manifest_for(incoming)

        calls = {"n": 0}
        original_smoke = vs.run_smoke

        def flaky_smoke(binary):
            calls["n"] += 1
            if calls["n"] > 1:  # the post-swap re-verification fails
                raise RuntimeError("post-swap run failed")
            return {"version": "2.1.5.dev0"}

        vs.run_smoke = flaky_smoke
        try:
            ok, reason = vs.atomic_upgrade(incoming, manifest, target)
        finally:
            vs.run_smoke = original_smoke

        self.assertFalse(ok)
        self.assertIn("rolled back", reason)
        # the previous version is runnable again at the target path
        self.assertEqual(target.read_bytes(), b"old-version")


if __name__ == "__main__":
    unittest.main()
