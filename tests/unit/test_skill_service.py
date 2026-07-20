"""Unit tests — MVP skill bundle import, Oracle-remediated.

Covers: bundle-root non-following, strict fail-closed lock, complete atomic write,
two-pass preflight limits, destination type checks, post-commit cleanup,
fully non-following check, ref resolution, stage helper ownership.
"""

import json
import os
import stat as stat_module
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisc.domain.skill_models import (
    CheckResult, FetchedTree, SkillFileEntry, SkillLockEntryV2, SkillLockV2,
    TransactionError, deserialize_lock_v2, parse_github_url,
)
from aisc.adapters.lock_serializer import serialize_lock_v2
from aisc.adapters.skill_validator import normalize_skill_name, validate_tree
from aisc.application import skill_service
from aisc.application.skill_service import _LockCorruptedError
from tests.harness.fake_github import (
    FakeGitHubTransport, make_skill_fixture, make_grill_me_fixture,
)


class ServiceTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _lock_path(self) -> Path:
        return self.root / "skills-lock.json"

    def _bundle_dir(self) -> Path:
        return self.root / "container" / "_bundle" / "skills"

    def _setup_bundle_tree(self):
        """Create the full bundle directory tree as real dirs (no symlinks)."""
        # Don't use mkdir with parents on leaf — validate each component
        (self.root / "container").mkdir(exist_ok=True)
        (self.root / "container" / "_bundle").mkdir(exist_ok=True)
        (self.root / "container" / "_bundle" / "skills").mkdir(exist_ok=True)


# ============================================================================
# URL parsing
# ============================================================================

class TestURLParsing(unittest.TestCase):
    def test_tree_ok(self):
        p = parse_github_url("https://github.com/o/r/tree/main/skills/x")
        self.assertEqual(p.directory, "skills/x")

    def test_blob_skill_md(self):
        p = parse_github_url("https://github.com/o/r/blob/main/skills/x/SKILL.md")
        self.assertEqual(p.directory, "skills/x")

    def test_reject_blob_not_skill_md(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://github.com/o/r/blob/main/skills/x/README.md")

    def test_reject_empty_tree(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://github.com/o/r/tree/main")

    def test_reject_root_skill_md(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://github.com/o/r/blob/main/SKILL.md")


# ============================================================================
# Strict name
# ============================================================================

class TestStrictName(unittest.TestCase):
    def test_accept_canonical(self):
        self.assertEqual(normalize_skill_name("my-skill"), "my-skill")

    def test_reject_uppercase(self):
        with self.assertRaises(ValueError):
            normalize_skill_name("My-Skill")

    def test_reject_special(self):
        with self.assertRaises(ValueError):
            normalize_skill_name("my skill")


# ============================================================================
# Lock fail-closed
# ============================================================================

class TestLockFailClosed(unittest.TestCase):
    def test_empty_roundtrip(self):
        data = serialize_lock_v2(SkillLockV2())
        lock = deserialize_lock_v2(data)
        self.assertEqual(lock.version, 2)

    def test_reject_unknown_root_key(self):
        data = b'{"version":2,"skills":{},"extra":1}'
        with self.assertRaises(ValueError) as cm:
            deserialize_lock_v2(data)
        self.assertIn("unknown keys", str(cm.exception))

    def test_reject_unknown_entry_key(self):
        e = SkillLockEntryV2(name="test", source_url="https://github.com/o/r/tree/main/d",
            requested_ref="main", resolved_commit="a"*40, directory="d", owner="o", repo="r",
            files=(SkillFileEntry(path="SKILL.md", sha256="b"*64, size=0),))
        raw = json.loads(serialize_lock_v2(SkillLockV2(skills={"test":e})).decode())
        raw["skills"]["test"]["extra"] = 1
        with self.assertRaises(ValueError) as cm:
            deserialize_lock_v2(json.dumps(raw).encode())
        self.assertIn("unknown keys", str(cm.exception))

    def test_reject_missing_skill_md(self):
        e = SkillLockEntryV2(name="test", source_url="https://github.com/o/r/tree/main/d",
            requested_ref="main", resolved_commit="a"*40, directory="d", owner="o", repo="r",
            files=(SkillFileEntry(path="README.md", sha256="b"*64, size=0),))
        raw = json.loads(serialize_lock_v2(SkillLockV2(skills={"test":e})).decode())
        with self.assertRaises(ValueError) as cm:
            deserialize_lock_v2(json.dumps(raw).encode())
        self.assertIn("SKILL.md", str(cm.exception))

    def test_reject_url_consistency(self):
        raw = json.loads(json.dumps({"version":2,"skills":{"test":{
            "name":"test","source_url":"https://github.com/o/r/tree/main/d",
            "requested_ref":"main","resolved_commit":"a"*40,"directory":"wrong",
            "owner":"o","repo":"r",
            "files":[{"path":"SKILL.md","sha256":"b"*64,"size":0}],
            "dependencies":{"detected_references":[]}}}}))
        with self.assertRaises(ValueError) as cm:
            deserialize_lock_v2(json.dumps(raw).encode())
        self.assertIn("inconsistent", str(cm.exception))


class TestLockTypeGuards(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def _write_valid_lock(self):
        self._lock_path().write_text(json.dumps({"version":2,"skills":{}}))

    def test_symlink_lock_rejected(self):
        self._write_valid_lock()
        real = self._lock_path()
        real.unlink()
        os.symlink("/dev/null", str(real))
        try:
            with self.assertRaises(_LockCorruptedError) as cm:
                skill_service._parse_lock(self._lock_path())
            self.assertIn("symlink", str(cm.exception).lower())
        finally:
            self._lock_path().unlink(missing_ok=True)

    def test_broken_symlink_lock_rejected(self):
        self._write_valid_lock()
        real = self._lock_path()
        real.unlink()
        os.symlink("/nonexistent/path/for/broken/symlink", str(real))
        try:
            with self.assertRaises(_LockCorruptedError):
                skill_service._parse_lock(self._lock_path())
        finally:
            self._lock_path().unlink(missing_ok=True)

    def test_dir_lock_rejected(self):
        self._lock_path().mkdir()
        with self.assertRaises(_LockCorruptedError):
            skill_service._parse_lock(self._lock_path())
        self._lock_path().rmdir()

    def test_missing_returns_empty(self):
        self.assertEqual(len(skill_service._parse_lock(self._lock_path()).skills), 0)

    def test_lstat_permission_error_raises(self):
        """Simulate PermissionError from os.lstat."""
        import aisc.application.skill_service as svc
        def _bad_lstat(p):
            raise PermissionError("Permission denied")
        orig = svc.os.lstat
        svc.os.lstat = _bad_lstat
        try:
            with self.assertRaises(_LockCorruptedError) as cm:
                svc._parse_lock(self._lock_path())
            self.assertIn("Permission denied", str(cm.exception))
        finally:
            svc.os.lstat = orig

    def test_lstat_oserror_raises(self):
        """Simulate OSError from os.lstat."""
        import aisc.application.skill_service as svc
        def _bad_lstat(p):
            raise OSError("I/O error")
        orig = svc.os.lstat
        svc.os.lstat = _bad_lstat
        try:
            with self.assertRaises(_LockCorruptedError) as cm:
                svc._parse_lock(self._lock_path())
            self.assertIn("I/O error", str(cm.exception))
        finally:
            svc.os.lstat = orig

    def test_corrupted_lock_blocks_list(self):
        self._lock_path().write_text("garbage")
        with self.assertRaises(_LockCorruptedError):
            skill_service.skill_list(self.root)

    def test_corrupted_lock_blocks_add(self):
        self._lock_path().write_text("garbage")
        transport, _, _ = make_skill_fixture()
        with self.assertRaises(_LockCorruptedError):
            skill_service.skill_add(
                "https://github.com/test-owner/test-repo/tree/main/skills/test-skill",
                self.root, transport=transport)

    def test_corrupted_lock_blocks_remove(self):
        self._lock_path().write_text("garbage")
        with self.assertRaises(_LockCorruptedError):
            skill_service.skill_remove("anything", self.root)


# ============================================================================
# Bundle root non-following
# ============================================================================

class TestBundleRootGuards(ServiceTestBase):
    def test_container_symlink_rejected(self):
        self._setup_bundle_tree()
        (self.root / "container").rename(self.root / "container-real")
        os.symlink(str(self.root / "container-real"), str(self.root / "container"))
        transport, _, _ = make_skill_fixture(name="test-skill")
        try:
            with self.assertRaises(ValueError) as cm:
                skill_service.skill_add(
                    "https://github.com/test-owner/test-repo/tree/main/skills/test-skill",
                    self.root, transport=transport)
            self.assertIn("symlink", str(cm.exception).lower())
        finally:
            (self.root / "container").unlink()
            (self.root / "container-real").rename(self.root / "container")

    def test_bundle_file_rejected(self):
        (self.root / "container").mkdir(exist_ok=True)
        (self.root / "container" / "_bundle").write_text("not a dir")
        transport, _, _ = make_skill_fixture(name="test-skill")
        with self.assertRaises(ValueError) as cm:
            skill_service.skill_add(
                "https://github.com/test-owner/test-repo/tree/main/skills/test-skill",
                self.root, transport=transport)
        self.assertIn("not a directory", str(cm.exception))
        (self.root / "container" / "_bundle").unlink()


# ============================================================================
# Git object rejection + preflight
# ============================================================================

class TestGitObjectPreflight(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def test_symlink_rejected(self):
        transport, _, _ = make_skill_fixture(name="sym",
            extra_files={"l": b"x"}, entry_modes={"l": "120000"})
        with self.assertRaises(Exception) as cm:
            skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/sym",
                self.root, transport=transport)
        self.assertIn("Symlink", str(cm.exception))

    def test_executable_rejected(self):
        transport, _, _ = make_skill_fixture(name="e",
            extra_files={"s": b"#!/bin/sh\n"}, entry_modes={"s": "100755"})
        with self.assertRaises(Exception) as cm:
            skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/e",
                self.root, transport=transport)
        self.assertIn("100644", str(cm.exception))

    def test_no_blobs_on_preflight_failure(self):
        """Count/size failure must not fetch any blob."""
        transport = FakeGitHubTransport()
        sha = "c"*40
        # 101 files exceeds limit
        files = {"skills/big/SKILL.md": b"---\nname: big\n---\n"}
        for i in range(101):
            files[f"skills/big/f{i}.txt"] = b"x"
        transport.add_repo("o", "r", sha, files)
        transport.add_ref("o", "r", "main", sha)
        blob_calls = []
        orig = transport.get_blob
        def tracking(slf, o, r, bs):
            blob_calls.append(bs)
            return orig(o, r, bs)
        import types
        transport.get_blob = types.MethodType(tracking, transport)
        with self.assertRaises(Exception):
            skill_service.skill_add("https://github.com/o/r/tree/main/skills/big",
                self.root, transport=transport)
        self.assertEqual(len(blob_calls), 0, "No blobs should be fetched on preflight failure")


# ============================================================================
# Skill add / remove — basic
# ============================================================================

class TestSkillAddRemove(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def test_add_simple(self):
        transport, commit, _ = make_skill_fixture(name="test-skill")
        entry, warnings = skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/test-skill",
            self.root, transport=transport)
        self.assertEqual(entry.name, "test-skill")
        self.assertEqual(entry.resolved_commit, commit)
        dest = self._bundle_dir() / "test-skill"
        self.assertTrue(dest.is_dir())
        lock = deserialize_lock_v2(self._lock_path().read_bytes())
        self.assertIn("test-skill", lock.skills)

    def test_add_blob_url(self):
        transport, _, _ = make_skill_fixture(name="blob-skill")
        entry, _ = skill_service.skill_add(
            "https://github.com/test-owner/test-repo/blob/main/skills/blob-skill/SKILL.md",
            self.root, transport=transport)
        self.assertEqual(entry.name, "blob-skill")

    def test_update_existing(self):
        transport, commit, _ = make_skill_fixture(name="up")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/up",
            self.root, transport=transport)
        transport2, commit2, _ = make_skill_fixture(name="up")
        transport2.add_ref("test-owner", "test-repo", "main", commit2)
        entry2, _ = skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/up",
            self.root, transport=transport2)
        self.assertEqual(entry2.resolved_commit, commit2)

    def test_unmanaged_guard(self):
        dest = self._bundle_dir() / "gstack"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("# handmade")
        transport, _, _ = make_skill_fixture(name="gstack")
        with self.assertRaises(ValueError):
            skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/gstack",
                self.root, transport=transport)

    def test_remove(self):
        transport, _, _ = make_skill_fixture(name="rm")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/rm",
            self.root, transport=transport)
        name, info = skill_service.skill_remove("rm", self.root)
        self.assertEqual(name, "rm")
        self.assertFalse((self._bundle_dir() / "rm").exists())

    def test_remove_missing_dir(self):
        transport, _, _ = make_skill_fixture(name="rmd")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/rmd",
            self.root, transport=transport)
        import shutil
        shutil.rmtree(str(self._bundle_dir() / "rmd"))
        name, info = skill_service.skill_remove("rmd", self.root)
        self.assertEqual(name, "rmd")
        self.assertTrue(info.get("directory_missing"))

    def test_gstack_preserved(self):
        transport, _, _ = make_skill_fixture(name="m")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/m",
            self.root, transport=transport)
        g = self._bundle_dir() / "gstack"
        g.mkdir(parents=True, exist_ok=True)
        (g / "SKILL.md").write_bytes(b"# GStack\n")
        skill_service.skill_remove("m", self.root)
        self.assertEqual((g / "SKILL.md").read_bytes(), b"# GStack\n")


# ============================================================================
# Transaction error tests
# ============================================================================

class TestTransactionErrors(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def _inject_write_lock_failure(self, exc: Exception):
        """Monkey-patch _write_lock to raise *exc*."""
        import aisc.application.skill_service as svc
        self._orig_wl = svc._write_lock
        def _fail(*a, **kw):
            raise exc
        svc._write_lock = _fail
        return svc

    def _restore_write_lock(self, svc):
        svc._write_lock = self._orig_wl

    def test_add_lock_failure_restores_exact(self):
        transport, _, _ = make_skill_fixture(name="tx")
        skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/tx",
            self.root, transport=transport)
        dest = self._bundle_dir() / "tx"
        old_content = (dest / "SKILL.md").read_bytes()
        old_lock = self._lock_path().read_bytes()

        primary = OSError("injected lock write failure")
        svc = self._inject_write_lock_failure(primary)

        transport2, _, _ = make_skill_fixture(name="tx",
            skill_md_content="---\nname: tx\n---\n# Updated\n")
        try:
            with self.assertRaises(TransactionError) as cm:
                skill_service.skill_add(
                    "https://github.com/test-owner/test-repo/tree/main/skills/tx",
                    self.root, transport=transport2)
            self.assertIs(cm.exception.primary, primary)
            self.assertFalse(cm.exception.committed)
            self.assertEqual(cm.exception.cleanup_errors, [])
        finally:
            self._restore_write_lock(svc)

        # Old destination and lock unchanged
        self.assertTrue(dest.is_dir())
        self.assertEqual((dest / "SKILL.md").read_bytes(), old_content)
        self.assertEqual(self._lock_path().read_bytes(), old_lock)

    def test_remove_lock_failure_restores_exact(self):
        transport, _, _ = make_skill_fixture(name="rtx")
        skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/rtx",
            self.root, transport=transport)
        dest = self._bundle_dir() / "rtx"
        old_content = (dest / "SKILL.md").read_bytes()
        old_lock = self._lock_path().read_bytes()

        primary = OSError("injected remove lock write failure")
        svc = self._inject_write_lock_failure(primary)

        try:
            with self.assertRaises(TransactionError) as cm:
                skill_service.skill_remove("rtx", self.root)
            self.assertIs(cm.exception.primary, primary)
            self.assertFalse(cm.exception.committed)
            self.assertEqual(cm.exception.cleanup_errors, [])
        finally:
            self._restore_write_lock(svc)

        # Destination and lock unchanged
        self.assertTrue(dest.is_dir())
        self.assertEqual((dest / "SKILL.md").read_bytes(), old_content)
        self.assertEqual(self._lock_path().read_bytes(), old_lock)

    def test_add_lock_failure_cleanup_evidence(self):
        """Inject lock failure AND restore failure to get cleanup_errors."""
        transport, _, _ = make_skill_fixture(name="cx")
        skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/cx",
            self.root, transport=transport)
        dest = self._bundle_dir() / "cx"
        old_content = (dest / "SKILL.md").read_bytes()
        old_lock = self._lock_path().read_bytes()

        primary = OSError("injected lock write failure")
        import aisc.application.skill_service as svc
        orig_wl = svc._write_lock
        orig_os_replace = svc.os.replace

        def _fail_wl(*a, **kw):
            raise primary

        called_restore = False
        def _fail_replace(src, dst):
            nonlocal called_restore
            if "backup" in str(src):
                called_restore = True
                raise OSError("injected restore failure")
            return orig_os_replace(src, dst)

        svc._write_lock = _fail_wl
        svc.os.replace = _fail_replace

        transport2, _, _ = make_skill_fixture(name="cx",
            skill_md_content="---\nname: cx\n---\n# Updated\n")
        try:
            with self.assertRaises(TransactionError) as cm:
                skill_service.skill_add(
                    "https://github.com/test-owner/test-repo/tree/main/skills/cx",
                    self.root, transport=transport2)
            self.assertIs(cm.exception.primary, primary)
            self.assertFalse(cm.exception.committed)
            self.assertTrue(called_restore)
            self.assertEqual(len(cm.exception.cleanup_errors), 1)
            self.assertIn("injected restore failure", cm.exception.cleanup_errors[0])
        finally:
            svc._write_lock = orig_wl
            svc.os.replace = orig_os_replace

        # Rollback failed after removing the newly placed destination. The
        # original remains recoverable in the unique backup and the lock was
        # never committed.
        self.assertFalse(dest.exists())
        backups = list(dest.parent.glob(f".{dest.name}.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "SKILL.md").read_bytes(), old_content)
        self.assertEqual(self._lock_path().read_bytes(), old_lock)

    def test_update_existing_genuine(self):
        """Update must use genuinely different commit and content."""
        # Original commit
        transport, commit1, _ = make_skill_fixture(name="gen-up")
        entry1, _ = skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/gen-up",
            self.root, transport=transport)
        self.assertEqual(entry1.resolved_commit, commit1)

        # Different commit with different content
        transport2 = FakeGitHubTransport()
        commit2 = "b" * 40
        transport2.add_repo("test-owner", "test-repo", commit2, {
            "skills/gen-up/SKILL.md": b"---\nname: gen-up\n---\n# Genuinely Updated\n",
        })
        transport2.add_ref("test-owner", "test-repo", "main", commit2)
        entry2, _ = skill_service.skill_add(
            "https://github.com/test-owner/test-repo/tree/main/skills/gen-up",
            self.root, transport=transport2)
        self.assertEqual(entry2.resolved_commit, commit2)
        self.assertNotEqual(entry2.resolved_commit, commit1)

        dest = self._bundle_dir() / "gen-up"
        content = (dest / "SKILL.md").read_text()
        self.assertIn("Genuinely Updated", content)

        lock_data = deserialize_lock_v2(self._lock_path().read_bytes())
        self.assertEqual(lock_data.skills["gen-up"].resolved_commit, commit2)
        self.assertEqual(len(lock_data.skills), 1)


# ============================================================================
# Check — non-following
# ============================================================================

class TestSkillCheck(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def test_check_valid(self):
        transport, _, _ = make_skill_fixture(name="good")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/good",
            self.root, transport=transport)
        self.assertTrue(skill_service.skill_check(self.root).in_sync)

    def test_check_hash_mismatch(self):
        transport, _, _ = make_skill_fixture(name="ht")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/ht",
            self.root, transport=transport)
        (self._bundle_dir() / "ht" / "SKILL.md").write_text("corrupted")
        self.assertFalse(skill_service.skill_check(self.root).in_sync)

    def test_check_symlink(self):
        transport, _, _ = make_skill_fixture(name="sd",
            extra_files={"real.txt": b"hello"})
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/sd",
            self.root, transport=transport)
        os.symlink("/etc/passwd", str(self._bundle_dir() / "sd" / "evil"))
        result = skill_service.skill_check(self.root)
        self.assertFalse(result.in_sync)

    def test_check_extra_file(self):
        transport, _, _ = make_skill_fixture(name="et")
        skill_service.skill_add("https://github.com/test-owner/test-repo/tree/main/skills/et",
            self.root, transport=transport)
        (self._bundle_dir() / "et" / "unexpected.txt").write_text("x")
        self.assertFalse(skill_service.skill_check(self.root).in_sync)

    def test_check_schema_drift(self):
        self._lock_path().write_text("not json")
        result = skill_service.skill_check(self.root)
        self.assertFalse(result.in_sync)
        self.assertTrue(any("parse" in d.lower() for d in result.drift_items))


# ============================================================================
# Atomic write tests
# ============================================================================

class TestAtomicWrite(unittest.TestCase):
    def test_write_and_read(self):
        d = tempfile.mkdtemp()
        try:
            p = Path(d) / "test.txt"
            skill_service._atomic_write(p, b"hello world")
            self.assertEqual(p.read_bytes(), b"hello world")
        finally:
            import shutil
            shutil.rmtree(d)

    def test_large_write(self):
        d = tempfile.mkdtemp()
        try:
            p = Path(d) / "large.bin"
            data = os.urandom(200000)
            skill_service._atomic_write(p, data)
            self.assertEqual(p.read_bytes(), data)
        finally:
            import shutil
            shutil.rmtree(d)


# ============================================================================
# Stage script helper ownership test
# ============================================================================

class TestStageHelperOwnership(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dst = Path(self._tmp.name)

    def _make_bundle(self):
        d = self.dst
        (d / "plugins" / "cache" / "caveman").mkdir(parents=True)
        (d / "plugins" / "cache" / "caveman" / ".gitignore").write_text("*.log\n")
        (d / "plugins" / "cache" / "caveman" / ".in_use").mkdir()
        (d / "skills" / "gstack" / "sub").mkdir(parents=True)
        (d / "skills" / "gstack" / ".gitignore").write_text("*.swp\n")
        (d / "skills" / "imported").mkdir(parents=True)
        (d / "skills" / "imported" / "SKILL.md").write_bytes(b"# Imported\n")
        (d / "skills" / "imported" / ".gitignore").write_text("local\n")
        (d / "skills" / "imported" / "agents").mkdir(parents=True)
        (d / "skills" / "imported" / "agents" / "openai.yaml").write_text("model: x\n")

    def test_helper_preserves_imported(self):
        self._make_bundle()
        imported = self.dst / "skills" / "imported"
        before = self._hash_dir(imported)
        # Run the actual cleanup helper
        helper = Path(__file__).resolve().parent.parent.parent / "tools" / "stage-skills-cleanup.sh"
        result = subprocess.run(
            ["bash", str(helper)],
            env={**os.environ, "DST": str(self.dst)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Helper failed: {result.stderr}")
        after = self._hash_dir(imported)
        self.assertEqual(before, after, "Imported skill must be byte-for-byte unchanged")
        # Plugin artifacts should be cleaned
        self.assertFalse((self.dst / "plugins" / "cache" / "caveman" / ".gitignore").exists())
        self.assertFalse((self.dst / "plugins" / "cache" / "caveman" / ".in_use").exists())
        self.assertFalse((self.dst / "skills" / "gstack" / ".gitignore").exists())

    def test_static_no_broad_find(self):
        script = Path(__file__).resolve().parent.parent.parent / "tools" / "stage-skills.sh"
        if not script.is_file():
            self.skipTest("stage-skills.sh not found")
        text = script.read_text()
        for i, line in enumerate(text.split("\n"), 1):
            s = line.strip()
            if 'find "$DST"' in s or 'find "${DST}"' in s:
                self.fail(f"Broad find on $DST at line {i}: {s}")
            if 'find "$DST/skills"' in s and 'gstack' not in s:
                self.fail(f"Unbounded find on $DST/skills at line {i}: {s}")

    def _hash_dir(self, d: Path) -> str:
        import hashlib
        h = hashlib.sha256()
        for f in sorted(d.rglob("*")):
            if f.is_file() and not f.is_symlink():
                h.update(f.relative_to(d).as_posix().encode())
                h.update(f.read_bytes())
        return h.hexdigest()


# ============================================================================
# Ref resolution (fake)
# ============================================================================

class TestRefResolution(ServiceTestBase):
    def setUp(self):
        super().setUp()
        self._setup_bundle_tree()

    def test_branch_resolution(self):
        transport = FakeGitHubTransport()
        sha = "b" * 40
        transport.add_repo("o", "r", sha, {"skills/x/SKILL.md": b"---\nname: x\n---\n"})
        transport.add_ref("o", "r", "heads/feature", sha)
        entry, _ = skill_service.skill_add(
            "https://github.com/o/r/tree/feature/skills/x",
            self.root, transport=transport)
        self.assertEqual(entry.resolved_commit, sha)

    def test_tag_resolution(self):
        transport = FakeGitHubTransport()
        sha = "c" * 40
        transport.add_repo("o", "r", sha, {"skills/x/SKILL.md": b"---\nname: x\n---\n"})
        transport.add_ref("o", "r", "tags/v1.0", sha)
        entry, _ = skill_service.skill_add(
            "https://github.com/o/r/tree/v1.0/skills/x",
            self.root, transport=transport)
        self.assertEqual(entry.resolved_commit, sha)

    def test_sha_ref(self):
        transport = FakeGitHubTransport()
        sha = "d" * 40
        transport.add_repo("o", "r", sha, {"skills/x/SKILL.md": b"---\nname: x\n---\n"})
        entry, _ = skill_service.skill_add(
            f"https://github.com/o/r/tree/{sha}/skills/x",
            self.root, transport=transport)
        self.assertEqual(entry.resolved_commit, sha)


# ============================================================================
# CLI integration
# ============================================================================

class TestSkillCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir(parents=True, exist_ok=True)
        (self.root / "VERSION").write_text("2.0.0-dev")
        (self.root / "container").mkdir(parents=True)
        (self.root / "container" / "Dockerfile").write_text("FROM scratch\n")
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "versions.env").write_text("# versions\n")
        (self.root / "container" / "_bundle").mkdir(parents=True)
        (self.root / "container" / "_bundle" / "skills").mkdir(parents=True)
        (self.root / "skills-lock.json").write_text(json.dumps({"version":2,"skills":{}}))

    def _run(self, *args: str) -> tuple:
        import io
        from aisc.cli.main import main
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        exit_code = 0
        try:
            main(list(args) + ["--aisc-root", str(self.root)])
        except SystemExit as e:
            exit_code = e.code or 0
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdout, sys.stderr = old_stdout, old_stderr
        return exit_code, stdout, stderr

    def test_skill_help(self):
        _, stdout, _ = self._run("skill", "--help")
        self.assertIn("add", stdout)

    def test_skill_list_empty(self):
        _, stdout, _ = self._run("skill", "list")
        self.assertIn("No skills managed", stdout)

    def test_skill_list_json(self):
        exit_code, stdout, _ = self._run("skill", "list", "--format", "json")
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout)["data"]["skills"], [])

    def test_skill_check_json(self):
        _, stdout, _ = self._run("skill", "check", "--format", "json")
        self.assertIn("in_sync", json.loads(stdout).get("data", {}))

    def test_skill_remove_nonexistent(self):
        exit_code, _, stderr = self._run("skill", "remove", "no-such")
        self.assertNotEqual(exit_code, 0)

    def test_skill_cwd_resolves_root(self):
        orig = os.getcwd()
        try:
            os.chdir("/tmp")
            exit_code, _, _ = self._run("skill", "list", "--aisc-root", str(self.root))
            self.assertEqual(exit_code, 0)
        finally:
            os.chdir(orig)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# RealGitHubTransport.resolve_ref — network-free tests via subclass
# ============================================================================

class _RecordedTransport:
    """Mixin/subclass helper: intercepts get() calls to return canned responses.

    Subclasses RealGitHubTransport and overrides get() to consult a
    url->response mapping.  The real resolve_ref logic runs unchanged.
    """

    def __init__(self, responses: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._responses = responses
        self._urls_called: list = []

    def get(self, url: str, *, headers=None, timeout=30.0):
        from aisc.adapters.github_client import GitHubResponse
        self._urls_called.append(url)
        if url in self._responses:
            entry = self._responses[url]
            if isinstance(entry, Exception):
                raise entry
            if isinstance(entry, dict):
                return self._response(200, entry)
            if isinstance(entry, int):
                raise self._http_error(entry, url)
            return entry  # must be GitHubResponse
        raise self._http_error(404, url)

    def _response(self, status, body_dict):
        from aisc.adapters.github_client import GitHubResponse
        import json as _json
        return GitHubResponse(
            status=status,
            body=_json.dumps(body_dict).encode("utf-8"),
            url="",
        )

    def _http_error(self, code, url):
        from aisc.adapters.github_client import GitHubError
        raise GitHubError(
            f"HTTP {code} for {url}", status=code,
            error_code="GITHUB_ERR_NOT_FOUND" if code == 404 else "GITHUB_ERR_HTTP",
            url=url,
        )


# Dynamically create test transport classes
import aisc.adapters.github_client as _ghc


def _make_recorded_transport(responses: dict):
    """Return a RealGitHubTransport subclass instance with recorded get()."""
    cls = type("_RT", (_RecordedTransport, _ghc.RealGitHubTransport), {})
    return cls(responses=responses)


def _sha(): return "0" * 40
def _sha2(): return "1" * 40
def _sha3(): return "2" * 40
def _sha4(): return "3" * 40
def _sha_seq(n: int) -> str:
    """Return deterministic valid hex SHA: n as right-padded hex."""
    return format(n, '040x')


class TestRealResolveRef(unittest.TestCase):
    """Exercise RealGitHubTransport.resolve_ref with intercepted get()."""

    def test_full_sha_verified(self):
        sha = _sha()
        t = _make_recorded_transport({
            f"https://api.github.com/repos/o/r/git/commits/{sha}":
                {"sha": sha},
        })
        result = t.resolve_ref("o", "r", sha)
        self.assertEqual(result, sha)

    def test_full_sha_mismatch(self):
        t = _make_recorded_transport({
            f"https://api.github.com/repos/o/r/git/commits/{_sha()}":
                {"sha": _sha2()},
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", _sha())
        self.assertIn("does not match", str(cm.exception))

    def test_full_sha_not_found(self):
        t = _make_recorded_transport({
            f"https://api.github.com/repos/o/r/git/commits/{_sha()}": 404,
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", _sha())
        self.assertEqual(cm.exception.error_code, "GITHUB_ERR_NOT_FOUND")

    def test_full_sha_invalid_response(self):
        t = _make_recorded_transport({
            f"https://api.github.com/repos/o/r/git/commits/{_sha()}": {"sha": "not-a-sha"},
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", _sha())
        self.assertIn("non-SHA", str(cm.exception))

    def test_branch_only(self):
        sha = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/main":
                {"object": {"sha": sha, "type": "commit"}},
            f"https://api.github.com/repos/o/r/git/commits/{sha}":
                {"sha": sha},
            "https://api.github.com/repos/o/r/git/ref/tags/main": 404,
        })
        result = t.resolve_ref("o", "r", "main")
        self.assertEqual(result, sha)

    def test_lightweight_tag(self):
        sha = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/v1": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/v1":
                {"object": {"sha": sha, "type": "commit"}},
            f"https://api.github.com/repos/o/r/git/commits/{sha}": {"sha": sha},
        })
        result = t.resolve_ref("o", "r", "v1")
        self.assertEqual(result, sha)

    def test_annotated_tag_single_level(self):
        sha_commit = _sha()
        sha_tag = _sha2()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/v2": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/v2":
                {"object": {"sha": sha_tag, "type": "tag"}},
            f"https://api.github.com/repos/o/r/git/tags/{sha_tag}":
                {"object": {"sha": sha_commit, "type": "commit"}},
            f"https://api.github.com/repos/o/r/git/commits/{sha_commit}": {"sha": sha_commit},
        })
        result = t.resolve_ref("o", "r", "v2")
        self.assertEqual(result, sha_commit)

    def test_nested_annotated_tag(self):
        sha_commit = _sha()
        sha_tag1 = _sha2()
        sha_tag2 = _sha3()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/v3": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/v3":
                {"object": {"sha": sha_tag1, "type": "tag"}},
            f"https://api.github.com/repos/o/r/git/tags/{sha_tag1}":
                {"object": {"sha": sha_tag2, "type": "tag"}},
            f"https://api.github.com/repos/o/r/git/tags/{sha_tag2}":
                {"object": {"sha": sha_commit, "type": "commit"}},
            f"https://api.github.com/repos/o/r/git/commits/{sha_commit}": {"sha": sha_commit},
        })
        result = t.resolve_ref("o", "r", "v3")
        self.assertEqual(result, sha_commit)

    def test_branch_tag_ambiguity(self):
        sha = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/dup":
                {"object": {"sha": sha, "type": "commit"}},
            "https://api.github.com/repos/o/r/git/ref/tags/dup":
                {"object": {"sha": sha, "type": "commit"}},
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", "dup")
        self.assertEqual(cm.exception.error_code, "GITHUB_ERR_AMBIGUOUS_REF")

    def test_neither_found(self):
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/nope": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/nope": 404,
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", "nope")
        self.assertEqual(cm.exception.error_code, "GITHUB_ERR_NOT_FOUND")

    def test_tag_cycle(self):
        sha_tag = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/cyc": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/cyc":
                {"object": {"sha": sha_tag, "type": "tag"}},
            f"https://api.github.com/repos/o/r/git/tags/{sha_tag}":
                {"object": {"sha": sha_tag, "type": "tag"}},
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", "cyc")
        self.assertIn("cycle", str(cm.exception).lower())

    def test_depth_exceeded(self):
        """10 nested tags should exceed max depth 8."""
        shas = [_sha_seq(i) for i in range(1, 11)]
        responses = {
            "https://api.github.com/repos/o/r/git/ref/heads/deep": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/deep":
                {"object": {"sha": shas[0], "type": "tag"}},
        }
        for i in range(8):
            responses[f"https://api.github.com/repos/o/r/git/tags/{shas[i]}"] = \
                {"object": {"sha": shas[i+1], "type": "tag"}}
        t = _make_recorded_transport(responses)
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", "deep")
        self.assertIn("max peel depth", str(cm.exception).lower())

    def test_tag_ends_non_commit(self):
        sha_tag = _sha()
        sha_blob = _sha2()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/bad": 404,
            "https://api.github.com/repos/o/r/git/ref/tags/bad":
                {"object": {"sha": sha_tag, "type": "tag"}},
            f"https://api.github.com/repos/o/r/git/tags/{sha_tag}":
                {"object": {"sha": sha_blob, "type": "blob"}},
        })
        with self.assertRaises(_ghc.GitHubError) as cm:
            t.resolve_ref("o", "r", "bad")
        self.assertIn("object type", str(cm.exception).lower())

    def test_url_encoding_present(self):
        """URLs should contain %2F for encoded / in ref if ever passed,
        but our parser rejects slash refs. Verify encoding shape for owner/repo."""
        sha = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o/r/git/ref/heads/main":
                {"object": {"sha": sha, "type": "commit"}},
            f"https://api.github.com/repos/o/r/git/commits/{sha}": {"sha": sha},
            "https://api.github.com/repos/o/r/git/ref/tags/main": 404,
        })
        t.resolve_ref("o", "r", "main")
        urls = t._urls_called
        # All URLs must be properly formed (no raw spaces, no unencoded specials)
        for u in urls:
            self.assertNotIn(" ", u)
            self.assertTrue(u.startswith("https://api.github.com/"))


class TestRealResolveRefEncoded(unittest.TestCase):
    """Verify URL encoding of owner/repo/ref path components."""

    def test_encoding_shape(self):
        """Owner/repo/ref with special chars produce %-encoded URLs."""
        sha = _sha()
        t = _make_recorded_transport({
            "https://api.github.com/repos/o-wner/r%2Bpo/git/ref/heads/feat%2Fbar":
                {"object": {"sha": sha, "type": "commit"}},
            f"https://api.github.com/repos/o-wner/r%2Bpo/git/commits/{sha}": {"sha": sha},
            "https://api.github.com/repos/o-wner/r%2Bpo/git/ref/tags/feat%2Fbar": 404,
        })
        # Note: our URL parser rejects slash-refs, but we can test encoding of
        # owner/repo with special chars that are accepted by the parser
        result = t.resolve_ref("o-wner", "r+po", "feat/bar")
        self.assertEqual(result, sha)
        # Verify URLs contain encoded components
        urls = t._urls_called
        self.assertTrue(any("r%2Bpo" in u for u in urls))
        self.assertTrue(any("feat%2Fbar" in u for u in urls))
