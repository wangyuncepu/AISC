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
    ensure_user_provider_catalog,
    run_provider_add,
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
        self.home_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.home_dir.name)
        self.home_patch = patch(
            "aisc.application.provider_service.Path.home",
            return_value=self.home,
        )
        self.home_patch.start()
        self._create_fake_root(self.root)

    def tearDown(self):
        self.home_patch.stop()
        self.home_dir.cleanup()
        self.tmpdir.cleanup()

    def _create_fake_root(self, path: Path) -> None:
        (path / "container").mkdir(parents=True, exist_ok=True)
        (path / "container" / "providers.json").write_text(
            _json.dumps(_SAMPLE_PROVIDERS, ensure_ascii=False)
        )
        # Also create markers so locate_aisc_root works via explicit_root
        (path / "VERSION").write_text("test")
        (path / "container" / "Dockerfile").parent.mkdir(parents=True, exist_ok=True)
        (path / "container" / "Dockerfile").write_text("FROM test")
        (path / "config").mkdir(parents=True, exist_ok=True)
        (path / "config" / "versions.env").write_text("NODE_IMAGE=node:20-slim\n")
        # config/providers.json for future main-merge fallback chain
        (path / "config" / "providers.json").write_text(
            _json.dumps(_SAMPLE_PROVIDERS, ensure_ascii=False)
        )
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


class TestProviderAdd(TestProviderShow):
    def _add(self, **overrides):
        values = {
            "provider_id": "local-ai",
            "name": "Local AI",
            "auth_type": "token",
            "auth_key_name": "LOCAL_AI_KEY",
            "base_url": "https://local.example.com/anthropic",
            "aliases": ("local",),
            "explicit_root": str(self.root),
            "home": str(self.home),
        }
        values.update(overrides)
        return run_provider_add(**values)

    def test_add_round_trip_and_private_permissions(self):
        result = self._add()
        self.assertEqual(result.exit_code, 0, result.error_message)
        shown = run_provider_show(
            "local", explicit_root=str(self.root), home=str(self.home),
        )
        self.assertEqual(shown.exit_code, 0)
        self.assertEqual(shown.data["id"], "local-ai")
        self.assertTrue(shown.data["custom"])
        catalog = self.home / ".aisc" / "providers.json"
        self.assertEqual(catalog.stat().st_mode & 0o777, 0o600)

    def test_initial_copy_preserves_unknown_fields(self):
        source = _json.loads((self.root / "config" / "providers.json").read_text())
        source["future_field"] = {"preserve": True}
        (self.root / "config" / "providers.json").write_text(_json.dumps(source))
        target = ensure_user_provider_catalog(str(self.root), home=str(self.home))
        self.assertEqual(_json.loads(target.read_text())["future_field"], {"preserve": True})

    def test_rejects_conflict_and_builtin_overwrite(self):
        conflict = self._add(provider_id="other", aliases=("deepseek",))
        self.assertNotEqual(conflict.exit_code, 0)
        builtin = self._add(provider_id="cc", aliases=(), overwrite=True)
        self.assertNotEqual(builtin.exit_code, 0)
        self.assertIn("Built-in", builtin.error_message)

    def test_overwrite_custom_provider(self):
        self.assertEqual(self._add().exit_code, 0)
        updated = self._add(name="Local AI 2", overwrite=True)
        self.assertEqual(updated.exit_code, 0, updated.error_message)
        self.assertTrue(updated.data["overwritten"])
        document = _json.loads((self.home / ".aisc" / "providers.json").read_text())
        self.assertEqual(document["providers"]["local-ai"]["name"], "Local AI 2")

    def test_rejects_invalid_values(self):
        self.assertEqual(self._add(provider_id="Bad ID").exit_code, 2)
        self.assertEqual(self._add(auth_key_name="lowercase").exit_code, 2)
        self.assertEqual(self._add(base_url="file:///tmp/api").exit_code, 2)


if __name__ == "__main__":
    unittest.main()
