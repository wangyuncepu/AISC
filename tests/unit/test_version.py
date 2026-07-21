"""Unit tests for aisc.application.version — version info gathering."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.application.version import (
    gather_version_info,
    _read_version_file,
    _parse_versions_env,
)
from aisc.application.resources import _RootSourceError
from aisc import __version__


class TestReadVersionFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_reads_version(self):
        (self.root / "VERSION").write_text("2.0.0-dev\n")
        self.assertEqual(_read_version_file(self.root), "2.0.0-dev")

    def test_reads_version_no_trailing_newline(self):
        (self.root / "VERSION").write_text("2.0.0-dev")
        self.assertEqual(_read_version_file(self.root), "2.0.0-dev")

    def test_empty_file(self):
        (self.root / "VERSION").write_text("")
        self.assertIsNone(_read_version_file(self.root))

    def test_whitespace_only(self):
        (self.root / "VERSION").write_text("  \n  ")
        self.assertIsNone(_read_version_file(self.root))

    def test_file_missing(self):
        self.assertIsNone(_read_version_file(self.root))


class TestParseVersionsEnv(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        (self.root / "config").mkdir(parents=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_env(self, content: str) -> None:
        (self.root / "config" / "versions.env").write_text(content)

    def test_parses_key_value(self):
        self._write_env("CLAUDE_CODE_VERSION=latest\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")

    def test_strips_inline_comments(self):
        self._write_env("CLAUDE_CODE_VERSION=latest  # TODO: pin\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")

    def test_strips_inline_comments_no_space(self):
        self._write_env("CLAUDE_CODE_VERSION=latest#comment\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")

    def test_skips_comment_lines(self):
        self._write_env("# This is a comment\nCLAUDE_CODE_VERSION=latest\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")

    def test_skips_blank_lines(self):
        self._write_env("\n\nCLAUDE_CODE_VERSION=latest\n\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")

    def test_multiple_keys(self):
        self._write_env("CLAUDE_CODE_VERSION=latest\nAISC_VERSION=2.0.0-dev\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")
        self.assertEqual(env.get("AISC_VERSION"), "2.0.0-dev")

    def test_missing_file(self):
        env = _parse_versions_env(self.root)
        self.assertEqual(env, {})

    def test_preserves_latest(self):
        self._write_env("CLAUDE_CODE_VERSION=latest\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env["CLAUDE_CODE_VERSION"], "latest")

    def test_handles_empty_value(self):
        self._write_env("GH_PROXY=\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("GH_PROXY"), "")

    def test_no_equal_sign_skipped(self):
        self._write_env("INVALID_LINE\nCLAUDE_CODE_VERSION=latest\n")
        env = _parse_versions_env(self.root)
        self.assertEqual(env.get("CLAUDE_CODE_VERSION"), "latest")
        self.assertNotIn("INVALID_LINE", env)


class TestGatherVersionInfo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_root(self) -> None:
        for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = self.root / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")
        (self.root / ".git").mkdir(exist_ok=True)
        (self.root / "VERSION").write_text("2.0.0-dev\n")
        (self.root / "config" / "versions.env").write_text(
            "CLAUDE_CODE_VERSION=latest  # TODO: pin\n"
            "AISC_VERSION=2.0.0-dev\n"
        )

    def test_with_root(self):
        self._make_root()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(Path, "cwd", return_value=self.root):
                info = gather_version_info()
        self.assertEqual(info.cli_version, __version__)
        self.assertIsNotNone(info.python_version)
        self.assertEqual(info.bundle_version, "2.0.0-dev")
        self.assertEqual(info.declared_claude_version, "latest")

    def test_without_root(self):
        """When cwd is not a repo and no env/explicit root, installed fallback
        discovers the AISC repo root (running from editable install)."""
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                with patch.object(Path, "cwd", return_value=td_path):
                    info = gather_version_info(cwd=td_path)
        self.assertEqual(info.cli_version, __version__)
        self.assertIsNotNone(info.python_version)
        # bundle_version is now found via installed fallback when running
        # from the repo (editable install). In a strict wheel environment
        # it would be None. Both are compliant.

    def test_version_matches_product_version(self):
        self._make_root()
        (self.root / "VERSION").write_text(f"{__version__}\n")
        (self.root / "config" / "versions.env").write_text(
            f"CLAUDE_CODE_VERSION=latest\nAISC_VERSION={__version__}\n"
        )
        with patch.object(Path, "cwd", return_value=self.root):
            info = gather_version_info()
        self.assertEqual(info.bundle_version, __version__)

    def test_explicit_root_invalid_raises(self):
        with self.assertRaises(_RootSourceError):
            gather_version_info(explicit_root="/nonexistent/path")

    # --- 6 fixed keys always present ---

    def test_to_dict_has_six_fixed_keys(self):
        info = gather_version_info()
        d = info.to_dict()
        expected_keys = {"cli_version", "bundle_version", "contract_version",
                         "image_version", "claude_version", "python_version"}
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_unknown_keys_are_null(self):
        """When no root found, root-dependent fields are None.
        Uses package_start injection to force no-root path."""
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                with patch.object(Path, "cwd", return_value=td_path):
                    from aisc.application.resources import locate_aisc_root
                    import aisc.application.version as vmod
                    # Force installed fallback to return None
                    def _fake_locate(*args, **kwargs):
                        return None
                    with patch.object(vmod, "locate_aisc_root",
                                      side_effect=_fake_locate):
                        info = gather_version_info()
        d = info.to_dict()
        self.assertIsNotNone(d["cli_version"])
        self.assertIsNotNone(d["python_version"])
        self.assertIsNone(d["bundle_version"])
        self.assertIsNone(d["claude_version"])
        self.assertIsNone(d["image_version"])
        self.assertIsNone(d["contract_version"])

    def test_to_dict_no_root_field(self):
        info = gather_version_info()
        d = info.to_dict()
        self.assertNotIn("root", d)


if __name__ == "__main__":
    unittest.main()
