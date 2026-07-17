"""Tests for aisc.application.resources — locate_aisc_root."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.application.resources import (
    locate_aisc_root,
    _is_root,
    _has_git,
    _RootSourceError,
)


class TestIsRoot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_valid_root_with_all_markers(self):
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = self.root / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")
        self.assertTrue(_is_root(self.root))

    def test_missing_marker(self):
        (self.root / "VERSION").write_text("content")
        (self.root / "container").mkdir(parents=True, exist_ok=True)
        self.assertFalse(_is_root(self.root))

    def test_no_markers(self):
        self.assertFalse(_is_root(self.root))


class TestHasGit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_git_dir_exists(self):
        (self.root / ".git").mkdir()
        self.assertTrue(_has_git(self.root))

    def test_git_file_worktree(self):
        (self.root / ".git").write_text("gitdir: /some/other/path")
        self.assertTrue(_has_git(self.root))

    def test_no_git(self):
        self.assertFalse(_has_git(self.root))


class TestLocateAiscRoot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self._create_valid_root(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_valid_root(self, path: Path) -> None:
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = path / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")
        (path / ".git").mkdir(exist_ok=True)

    # --- explicit root ---

    def test_explicit_root_valid(self):
        result = locate_aisc_root(explicit_root=str(self.root))
        self.assertEqual(result, self.root.resolve())

    def test_explicit_root_not_dir_raises(self):
        with self.assertRaises(_RootSourceError) as ctx:
            locate_aisc_root(explicit_root="/nonexistent/path/xyz123")
        self.assertEqual(ctx.exception.source, "--aisc-root")
        self.assertIn("not a directory", str(ctx.exception))

    def test_explicit_root_missing_markers_raises(self):
        empty = Path(self.tmpdir.name) / "empty"
        empty.mkdir()
        with self.assertRaises(_RootSourceError) as ctx:
            locate_aisc_root(explicit_root=str(empty))
        self.assertEqual(ctx.exception.source, "--aisc-root")
        self.assertIn("missing required structure markers", str(ctx.exception))

    # --- env var ---

    def test_aisc_root_env_valid(self):
        with patch.dict(os.environ, {"AISC_ROOT": str(self.root)}):
            result = locate_aisc_root()
            self.assertEqual(result, self.root.resolve())

    def test_aisc_root_env_invalid_raises(self):
        with patch.dict(os.environ, {"AISC_ROOT": "/nonexistent/xyz"}):
            with self.assertRaises(_RootSourceError) as ctx:
                locate_aisc_root()
            self.assertEqual(ctx.exception.source, "AISC_ROOT")
            self.assertIn("not a directory", str(ctx.exception))

    def test_aisc_root_env_missing_markers_raises(self):
        empty = Path(self.tmpdir.name) / "empty2"
        empty.mkdir()
        with patch.dict(os.environ, {"AISC_ROOT": str(empty)}):
            with self.assertRaises(_RootSourceError) as ctx:
                locate_aisc_root()
            self.assertEqual(ctx.exception.source, "AISC_ROOT")
            self.assertIn("missing required structure markers", str(ctx.exception))

    def test_explicit_priority_over_env(self):
        with patch.dict(os.environ, {"AISC_ROOT": "/nonexistent"}):
            result = locate_aisc_root(explicit_root=str(self.root))
            self.assertEqual(result, self.root.resolve())

    # --- repo discovery ---

    def test_repo_discovery_with_git_and_markers(self):
        repo = self.root
        with patch.object(Path, "cwd", return_value=repo):
            result = locate_aisc_root()
            self.assertEqual(result, repo.resolve())

    def test_repo_discovery_walks_up(self):
        repo = self.root
        subdir = repo / "deeply" / "nested" / "dir"
        subdir.mkdir(parents=True)
        with patch.object(Path, "cwd", return_value=subdir):
            result = locate_aisc_root()
            self.assertEqual(result, repo.resolve())

    def test_repo_discovery_no_git_returns_none(self):
        import shutil
        git_dir = self.root / ".git"
        if git_dir.is_dir():
            shutil.rmtree(git_dir)
        elif git_dir.is_file():
            git_dir.unlink()
        with patch.object(Path, "cwd", return_value=self.root):
            result = locate_aisc_root()
            self.assertIsNone(result)

    def test_repo_discovery_missing_markers_returns_none(self):
        (self.root / "config" / "versions.env").unlink()
        with patch.object(Path, "cwd", return_value=self.root):
            result = locate_aisc_root()
            self.assertIsNone(result)

    def test_repo_git_worktree_file(self):
        import shutil
        git_dir = self.root / ".git"
        if git_dir.is_dir():
            shutil.rmtree(git_dir)
        (self.root / ".git").write_text("gitdir: /some/other/path\n")
        with patch.object(Path, "cwd", return_value=self.root):
            result = locate_aisc_root()
            self.assertEqual(result, self.root.resolve())

    def test_no_env_no_root_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as td:
                with patch.object(Path, "cwd", return_value=Path(td)):
                    result = locate_aisc_root()
                    self.assertIsNone(result)

    # --- frozen bundle ---

    def test_frozen_no_bundle_falls_through(self):
        """When frozen but no aisc-bundle, fall through to cwd discovery."""
        with tempfile.TemporaryDirectory() as td:
            with patch.object(Path, "cwd", return_value=Path(td)):
                result = locate_aisc_root(
                    is_frozen=lambda: True,
                    executable_path="/usr/bin/aisc",
                )
                self.assertIsNone(result)  # no repo

    def test_frozen_bundle_corrupt_raises(self):
        exe_dir = self.root / "bin"
        exe_dir.mkdir(parents=True, exist_ok=True)
        bundle = exe_dir / "aisc-bundle"
        bundle.mkdir()  # no markers
        with self.assertRaises(_RootSourceError) as ctx:
            locate_aisc_root(
                is_frozen=lambda: True,
                executable_path=str(exe_dir / "aisc"),
            )
        self.assertEqual(ctx.exception.source, "frozen-bundle")
        self.assertIn("corrupt", str(ctx.exception))

    def test_frozen_bundle_valid(self):
        exe_dir = self.root / "bin"
        exe_dir.mkdir(parents=True, exist_ok=True)
        bundle = exe_dir / "aisc-bundle"
        bundle.mkdir()
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = bundle / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")
        result = locate_aisc_root(
            is_frozen=lambda: True,
            executable_path=str(exe_dir / "aisc"),
        )
        self.assertEqual(result, bundle.resolve())

    def test_not_frozen_ignores_executable_dir(self):
        """Dev/source mode should NOT look at executable for a bundle."""
        with tempfile.TemporaryDirectory() as td:
            clean_dir = Path(td)
            exe_dir = clean_dir / "bin"
            exe_dir.mkdir(parents=True, exist_ok=True)
            bundle = exe_dir / "aisc-bundle"
            bundle.mkdir()
            for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
                p = bundle / marker
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("content")
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(Path, "cwd", return_value=clean_dir):
                    result = locate_aisc_root(
                        is_frozen=lambda: False,
                        executable_path=str(exe_dir / "aisc"),
                    )
                    self.assertIsNone(result)

    def test_frozen_no_executable_present(self):
        """is_frozen=True but no executable_path → falls through to cwd."""
        with tempfile.TemporaryDirectory() as td:
            with patch.object(Path, "cwd", return_value=Path(td)):
                result = locate_aisc_root(is_frozen=lambda: True)
                self.assertIsNone(result)

    # --- error source distinction ---

    def test_explicit_root_error_has_correct_source(self):
        try:
            locate_aisc_root(explicit_root="/nonexistent")
        except _RootSourceError as e:
            self.assertEqual(e.source, "--aisc-root")

    def test_env_root_error_has_correct_source(self):
        with patch.dict(os.environ, {"AISC_ROOT": "/nonexistent"}):
            try:
                locate_aisc_root()
            except _RootSourceError as e:
                self.assertEqual(e.source, "AISC_ROOT")

    # --- production defaults (sys.frozen / sys.executable) ---

    def test_production_default_frozen_uses_sys_frozen(self):
        """When is_frozen not injected, reads getattr(sys, 'frozen', False)."""
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "/usr/bin/aisc"):
                with tempfile.TemporaryDirectory() as td:
                    with patch.object(Path, "cwd", return_value=Path(td)):
                        result = locate_aisc_root()
                        # No bundle, no repo → None
                        self.assertIsNone(result)

    def test_production_default_source_mode_no_bundle(self):
        """Non-frozen mode must NOT check sys.executable for a bundle."""
        exe_dir = self.root / "bin"
        exe_dir.mkdir(parents=True, exist_ok=True)
        bundle = exe_dir / "aisc-bundle"
        bundle.mkdir()
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = bundle / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")

        # frozen=False but there's a bundle near the fake executable —
        # source mode must NOT find it via the executable path
        with patch.object(sys, "frozen", False, create=True):
            with patch.object(sys, "executable", str(exe_dir / "aisc")):
                with tempfile.TemporaryDirectory() as td:
                    with patch.object(Path, "cwd", return_value=Path(td)):
                        with patch.dict(os.environ, {}, clear=True):
                            result = locate_aisc_root()
                            self.assertIsNone(result)

    def test_production_default_frozen_validates_bundle(self):
        """Frozen mode (via sys.frozen) with sys.executable finds bundle."""
        exe_dir = self.root / "bin"
        exe_dir.mkdir(parents=True, exist_ok=True)
        bundle = exe_dir / "aisc-bundle"
        bundle.mkdir()
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = bundle / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")

        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", str(exe_dir / "aisc")):
                result = locate_aisc_root()
                self.assertEqual(result, bundle.resolve())


if __name__ == "__main__":
    unittest.main()
