"""Stage 0 (S0.2): shared `aisc.cli/v1` contract fixtures, Python consumer.

B-A03: Python/Rust/TS all consume the same files under tests/fixtures/cli/.
This module validates the fixture set itself (golden structure, unknown-field
round-trip, unsupported-protocol negative) and that Python's
``build_envelope`` / ``build_error`` produce a compatible shape.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "cli"

REQUIRED_META = {"protocol", "command", "exit_code", "timestamp", "version", "run_id"}


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CliEnvelopeFixturesTests(unittest.TestCase):
    def test_version_envelope_structure(self):
        env = _load("envelope-version.json")
        self.assertEqual(env["meta"]["protocol"], "aisc.cli/v1")
        self.assertEqual(env["meta"]["command"], "version")
        self.assertEqual(env["meta"]["exit_code"], 0)
        self.assertEqual(set(env.keys()), {"meta", "data", "errors"})
        self.assertTrue(REQUIRED_META.issubset(env["meta"].keys()))
        self.assertEqual(env["errors"], [])

    def test_version_data_carries_capabilities(self):
        env = _load("envelope-version.json")
        caps = env["data"]["capabilities"]
        self.assertEqual(
            caps,
            {
                "runtime": "aisc.runtime/v1",
                "session": "aisc.session/v1",
                "providerStatus": "aisc.provider-status/v1",
                "buildEvents": "aisc.build-events/v1",
            },
        )

    def test_error_envelopes_have_stable_codes(self):
        for name, expected_code in (
            ("envelope-error-invalid-runtime-id.json", "AISC_ERR_INVALID_RUNTIME_ID"),
            ("envelope-error-usage.json", "AISC_ERR_USAGE"),
        ):
            with self.subTest(name=name):
                env = _load(name)
                self.assertEqual(env["meta"]["protocol"], "aisc.cli/v1")
                self.assertEqual(len(env["errors"]), 1)
                self.assertEqual(env["errors"][0]["code"], expected_code)
                self.assertEqual(env["meta"]["exit_code"] in (2, 15), True)

    def test_unknown_fields_survive_round_trip(self):
        env = _load("envelope-unknown-field.json")
        self.assertIn("x_future_top_level", env)
        self.assertEqual(env["x_future_top_level"], {"kept": True})
        self.assertIn("x_data_future_note", env)
        # Re-serialize and re-parse: unknown fields must not be dropped.
        again = json.loads(json.dumps(env, ensure_ascii=True))
        self.assertIn("x_future_top_level", again)
        self.assertIn("x_data_future_note", again)

    def test_unsupported_protocol_is_negative_fixture(self):
        env = _load("envelope-unsupported-protocol.json")
        self.assertNotEqual(env["meta"]["protocol"], "aisc.cli/v1")
        self.assertEqual(env["meta"]["protocol"], "aisc.cli/v2")

    def test_python_envelope_shape_matches_fixture(self):
        from aisc.cli.output import build_envelope, build_error

        env = build_envelope(
            command="version",
            exit_code=0,
            version="2.1.5-dev",
            data={"cli_version": "2.1.5-dev"},
        )
        self.assertEqual(set(env.keys()), {"meta", "data", "errors"})
        self.assertTrue(REQUIRED_META.issubset(env["meta"].keys()))
        err = build_error("AISC_ERR_USAGE", "bad input")
        self.assertEqual(set(err.keys()), {"code", "message", "hint"})


class ErrorCodesFixtureTests(unittest.TestCase):
    REQUIRED_CODES = {
        "AISC_ERR_USAGE",
        "AISC_ERR_INVALID_RUNTIME_ID",
        "AISC_ERR_CLI_NOT_FOUND",
        "AISC_ERR_DOCKER_UNAVAILABLE",
        "AISC_ERR_IMAGE_MISSING",
        "AISC_ERR_BUILD_FAILED",
    }

    def test_error_codes_manifest_has_required_codes(self):
        codes = _load("error-codes.json")
        self.assertTrue(self.REQUIRED_CODES.issubset(codes.keys()))

    def test_every_code_defines_exit_and_action(self):
        codes = _load("error-codes.json")
        for code, spec in codes.items():
            if code.startswith("$"):
                continue
            with self.subTest(code=code):
                self.assertIn("exit_code", spec)
                self.assertIsInstance(spec["exit_code"], int)
                self.assertIn("retryable", spec)
                self.assertIn("action", spec)


class RedactionSmokeTests(unittest.TestCase):
    def test_version_envelope_has_no_secret_shapes(self):
        """B-A08: the CLI's public JSON output must not carry secret shapes."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "aisc", "version", "--format", "json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lowered = result.stdout.lower()
        for bad in ("sk-", "api_key", "authorization", "bearer "):
            self.assertNotIn(bad, lowered, f"version output leaked {bad!r}")


if __name__ == "__main__":
    unittest.main()
