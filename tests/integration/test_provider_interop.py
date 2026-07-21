"""Host/container provider catalog interoperability tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SWITCH_SCRIPT = PROJECT_ROOT / "container" / "claude-switch"
BASE_CATALOG = PROJECT_ROOT / "config" / "providers.json"


@unittest.skipUnless(shutil.which("bash") and shutil.which("node"), "bash and node required")
class TestProviderInterop(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name) / "home"
        self.aisc_dir = self.home / ".aisc"
        self.claude_dir = self.home / ".claude"
        self.cc_dir = self.home / ".cc-config"
        self.aisc_dir.mkdir(parents=True)
        self.claude_dir.mkdir()
        self.cc_dir.mkdir()
        shutil.copyfile(BASE_CATALOG, self.aisc_dir / "providers.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "HOME": str(self.home),
            "AISC_DIR": str(self.aisc_dir),
            "CLAUDE_CONFIG_DIR": str(self.claude_dir),
            "CC_CONFIG_DIR": str(self.cc_dir),
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
        })
        return env

    def _cs(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SWITCH_SCRIPT), *args],
            cwd=PROJECT_ROOT,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=15,
        )

    def _aisc(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "aisc", *args],
            cwd=PROJECT_ROOT,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_cs_add_is_visible_to_host_aisc(self) -> None:
        added = self._cs(
            "add", "--id", "shell-ai", "--name", "Shell AI",
            "--auth-type", "token", "--auth-key-name", "SHELL_AI_KEY",
            "--base-url", "https://shell.example.com/anthropic",
            "--alias", "sai",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        shown = self._aisc(
            "provider", "show", "sai", "--format", "json",
            "--aisc-root", str(PROJECT_ROOT),
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        data = json.loads(shown.stdout)["data"]
        self.assertEqual(data["id"], "shell-ai")
        self.assertTrue(data["custom"])
        self.assertEqual((self.aisc_dir / "providers.json").stat().st_mode & 0o777, 0o600)

    def test_host_aisc_add_is_visible_to_cs(self) -> None:
        added = self._aisc(
            "provider", "add", "--id", "host-ai", "--name", "Host AI",
            "--auth-type", "api_key", "--auth-key-name", "HOST_AI_KEY",
            "--base-url", "https://host.example.com/v1",
            "--aisc-root", str(PROJECT_ROOT),
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        help_result = self._cs("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("host-ai", help_result.stdout)
        self.assertIn("https://host.example.com/v1", help_result.stdout)

    def test_cs_cannot_overwrite_builtin_provider(self) -> None:
        result = self._cs(
            "add", "--id", "cc", "--name", "Replacement",
            "--auth-type", "api_key", "--auth-key-name", "REPLACEMENT_KEY",
            "--base-url", "https://replacement.example.com", "--overwrite",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("built-in provider cannot be overwritten", result.stderr)

    def test_run_dry_run_does_not_create_provider_catalog(self) -> None:
        (self.aisc_dir / "providers.json").unlink()
        result = self._aisc(
            "run", "--dry-run", "--workspace", str(PROJECT_ROOT),
            "--aisc-root", str(PROJECT_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.aisc_dir / "providers.json").exists())
        self.assertIn(
            f"{self.aisc_dir}:/home/AISC/app/.aisc",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
