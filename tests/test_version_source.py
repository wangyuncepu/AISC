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


class TestWorkbenchCapabilities(unittest.TestCase):
    """Workbench capability negotiation (05-cli-gui-contract.md §四)."""

    def test_version_dict_advertises_implemented_capabilities(self):
        from aisc.domain.models import VersionInfo, WORKBENCH_CAPABILITIES
        info = VersionInfo(cli_version="x", python_version="y")
        caps = info.to_dict()["capabilities"]
        assert caps == WORKBENCH_CAPABILITIES
        # S0.4 ships runtime + session + providerStatus.
        assert caps["runtime"] == "aisc.runtime/v1"
        assert caps["session"] == "aisc.session/v1"
        assert caps["providerStatus"] == "aisc.provider-status/v1"

    def test_version_json_envelope_carries_capabilities(self):
        import contextlib
        import io
        import json
        from aisc.cli.main import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["version", "--format", "json"])
        assert cm.exception.code == 0
        caps = json.loads(buf.getvalue())["data"]["capabilities"]
        assert {"runtime", "session", "providerStatus"} <= set(caps.keys())


if __name__ == "__main__":
    unittest.main()
