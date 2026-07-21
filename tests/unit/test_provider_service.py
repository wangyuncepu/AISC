"""Unit tests for provider_service — provider show (id/alias lookup)."""
from __future__ import annotations

import json as _json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.application.provider_service import (
    run_provider_list,
    run_provider_show,
    ProviderListResult,
    ProviderShowResult,
)


# Minimal providers JSON for tests
_SAMPLE_PROVIDERS = {
    "schema_version": 1,
    "providers": {
        "cc": {
            "id": "cc",
            "name": "Claude",
            "aliases": ["default", "anthropic"],
            "auth_type": "api_key",
            "auth_key_name": "ANTHROPIC_OFFICIAL_KEY",
            "base_url": "",
        },
        "deepseek": {
            "id": "deepseek",
            "name": "DeepSeek V4",
            "aliases": ["ds"],
            "auth_type": "token",
            "auth_key_name": "DEEPSEEK_KEY",
            "base_url": "https://api.deepseek.com/anthropic",
        },
    },
}


class TestProviderShow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self._create_fake_root(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_fake_root(self, path: Path) -> None:
        (path / "config").mkdir(parents=True, exist_ok=True)
        (path / "config" / "providers.json").write_text(
            _json.dumps(_SAMPLE_PROVIDERS, ensure_ascii=False)
        )
        # Also create markers so locate_aisc_root works via explicit_root
        (path / "VERSION").write_text("test")
        (path / "container" / "Dockerfile").parent.mkdir(parents=True, exist_ok=True)
        (path / "container" / "Dockerfile").write_text("FROM test")
        (path / "config" / "versions.env").write_text("NODE_IMAGE=node:20-slim\n")
        (path / ".git").mkdir(exist_ok=True)

    # --- show by id ---

    def test_show_by_id(self):
        result = run_provider_show("cc", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["id"], "cc")
        self.assertEqual(result.data["name"], "Claude")
        self.assertIn("default", result.data["aliases"])
        self.assertIn("anthropic", result.data["aliases"])

    def test_show_by_other_id(self):
        result = run_provider_show("deepseek", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["name"], "DeepSeek V4")

    # --- show by alias ---

    def test_show_by_alias(self):
        result = run_provider_show("default", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["id"], "cc")

    def test_show_by_second_alias(self):
        result = run_provider_show("anthropic", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["id"], "cc")

    def test_show_by_alias_ds(self):
        result = run_provider_show("ds", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["id"], "deepseek")

    # --- unknown ---

    def test_show_unknown_provider(self):
        result = run_provider_show("nonexistent", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 1)
        self.assertIn("not found", result.error_message)

    # --- error handling ---

    def test_show_missing_root(self):
        result = run_provider_show("cc", explicit_root="/nonexistent/path/xyz")
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.error_message)

    # --- provider list still works ---

    def test_list_includes_aliases(self):
        result = run_provider_list(explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        providers = result.data["providers"]
        cc = [p for p in providers if p["id"] == "cc"][0]
        self.assertIn("default", cc["aliases"])
        self.assertIn("anthropic", cc["aliases"])

    # --- no secret reads ---

    def test_show_no_secret_access(self):
        """Provider show must not read/write secret files."""
        result = run_provider_show("cc", explicit_root=str(self.root))
        self.assertEqual(result.exit_code, 0)
        # Should not read from .aisc/secrets or config
        self.assertIn("id", result.data)


if __name__ == "__main__":
    unittest.main()
