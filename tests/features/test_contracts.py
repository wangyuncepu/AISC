"""Repository contract tests — static schema / required-key checks.

These are NOT behavioural tests; they verify that key config files exist and
conform to their expected structure so that runtime code does not break on
missing or malformed elements.
"""

from __future__ import annotations

import json
import os
import unittest


class ProvidersJsonTest(unittest.TestCase):
    """Structural contract: container/providers.json."""

    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        path = os.path.join(root, "container", "providers.json")
        if not os.path.isfile(path):
            raise unittest.SkipTest(f"providers.json not found at {path}")
        with open(path) as fh:
            cls.data = json.load(fh)

    # -- top-level schema ---------------------------------------------------

    def test_has_schema_version(self) -> None:
        self.assertIn("schema_version", self.data)
        self.assertIsInstance(self.data["schema_version"], int)

    def test_has_providers_dict(self) -> None:
        self.assertIn("providers", self.data)
        self.assertIsInstance(self.data["providers"], dict)
        self.assertGreater(len(self.data["providers"]), 0,
                           "providers dictionary is empty")

    # -- per-provider required fields ---------------------------------------

    REQUIRED_PROVIDER_KEYS = {
        "id": str,
        "name": str,
        "auth_type": str,
        "auth_key_name": str,
        "base_url": str,
        "model": str,
    }

    def test_every_provider_has_required_keys(self) -> None:
        for pid, pdata in self.data["providers"].items():
            with self.subTest(provider=pid):
                self.assertIsInstance(pdata, dict,
                                      f"provider {pid} is not a dict")
                for key, typ in self.REQUIRED_PROVIDER_KEYS.items():
                    self.assertIn(key, pdata,
                                  f"provider {pid}: missing required key '{key}'")
                    self.assertIsInstance(
                        pdata[key], typ,
                        f"provider {pid}: '{key}' expected {typ.__name__}, "
                        f"got {type(pdata[key]).__name__}",
                    )

    def test_provider_ids_are_unique(self) -> None:
        ids = [p["id"] for p in self.data["providers"].values()]
        self.assertEqual(len(ids), len(set(ids)),
                         f"duplicate provider ids: {ids}")

    def test_auth_type_values(self) -> None:
        valid_types = {"api_key", "token"}
        for pid, pdata in self.data["providers"].items():
            with self.subTest(provider=pid):
                self.assertIn(pdata["auth_type"], valid_types,
                              f"unknown auth_type '{pdata['auth_type']}'")


class VersionsEnvTest(unittest.TestCase):
    """Structural contract: config/versions.env — required keys."""

    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        path = os.path.join(root, "config", "versions.env")
        if not os.path.isfile(path):
            raise unittest.SkipTest(f"versions.env not found at {path}")
        with open(path) as fh:
            cls.raw = fh.read()

    # -- required keys ------------------------------------------------------

    REQUIRED_KEYS = [
        "AISC_VERSION",
        "NODE_IMAGE",
        "MIHOMO_VERSION",
        "CC_SWITCH_VERSION",
        "CLAUDE_CODE_VERSION",
        "GEODATA_VERSION",
        "USE_CN_MIRROR",
    ]

    def test_required_keys_present(self) -> None:
        for key in self.REQUIRED_KEYS:
            with self.subTest(key=key):
                # Simple substring check — the raw text contains "KEY=" lines
                self.assertIn(
                    f"\n{key}=",
                    "\n" + self.raw,
                    msg=f"required key '{key}' not found in versions.env",
                )

    def test_no_empty_required_values(self) -> None:
        """Keys that are structural must have a non-empty value."""
        structural_keys = {"AISC_VERSION", "NODE_IMAGE", "MIHOMO_VERSION",
                           "CC_SWITCH_VERSION"}
        for line in self.raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key in structural_keys:
                with self.subTest(key=key):
                    self.assertNotEqual(
                        val.strip(), "",
                        f"key '{key}' has empty value in versions.env",
                    )


if __name__ == "__main__":
    unittest.main()
