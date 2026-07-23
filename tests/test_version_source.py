"""Version single-source contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import aisc


class VersionSourceTests(unittest.TestCase):
    def test_package_version_matches_version_file(self) -> None:
        expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(aisc.__version__, expected)

    def test_no_duplicate_project_version_in_versions_env(self) -> None:
        versions_env = (PROJECT_ROOT / "config" / "versions.env").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("AISC_VERSION=", versions_env)

    def test_package_init_has_no_hardcoded_release(self) -> None:
        package_init = (SRC / "aisc" / "__init__.py").read_text(encoding="utf-8")
        current = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertNotIn(current, package_init)

    def test_wheel_packages_canonical_version_file(self) -> None:
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('[tool.setuptools.data-files]\naisc = ["VERSION"]', pyproject)


if __name__ == "__main__":
    unittest.main()
