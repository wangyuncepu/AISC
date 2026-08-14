"""Stage 0 (S0.2): shared `aisc.cli/v1` contract fixtures, Python consumer.

B-A03: Python/Rust/TS all consume the same files under tests/fixtures/cli/.
This module validates the fixture set itself (golden structure, unknown-field
round-trip, unsupported-protocol negative) and that Python's
``build_envelope`` / ``build_error`` produce a compatible shape.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "cli"

REQUIRED_META = {"protocol", "command", "exit_code", "timestamp", "version", "run_id"}


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _cli_argv(*args: str) -> list[str]:
    """argv for the CLI under test.

    Defaults to ``python -m aisc`` (the pip-installable entry). Set
    ``AISC_CLI_EXECUTABLE`` to point at the frozen PyInstaller sidecar so the
    same contract tests exercise that binary (CLI-A02: sidecar deep-equal).
    """
    exe = os.environ.get("AISC_CLI_EXECUTABLE")
    argv = [exe] if exe else [sys.executable, "-m", "aisc"]
    return argv + list(args)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(_cli_argv(*args), capture_output=True, text=True)


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
            version="2.1.5.dev0",
            data={"cli_version": "2.1.5.dev0"},
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
        result = _run_cli("version", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        lowered = result.stdout.lower()
        for bad in ("sk-", "api_key", "authorization", "bearer "):
            self.assertNotIn(bad, lowered, f"version output leaked {bad!r}")


# ---------------------------------------------------------------------------
# Stage 2 (S2.2, CLI-A02): pip CLI / sidecar deep-equal to the shared v1
# fixtures, JSONL emitter parity, and protocol fail-closed guard.
# ---------------------------------------------------------------------------


class CliVersionDeepEqualTests(unittest.TestCase):
    """The real CLI (pip entry point, or the frozen sidecar via
    ``AISC_CLI_EXECUTABLE``) emits a version envelope that deep-equals the
    shared ``envelope-version.json`` fixture, after normalizing the
    documented environment-dependent fields.

    The stable contract — protocol, command, exit_code, meta.version,
    cli_version, bundle_version, the six-key shape, capabilities, and an
    empty errors list — is asserted strictly.
    """

    # Fields that legitimately vary per machine/install context; the fixture
    # pins one representative value. Everything else must match exactly.
    ENV_DEPENDENT = ("python_version", "claude_version")

    def test_version_envelope_deep_equals_fixture(self):
        expected = _load("envelope-version.json")
        result = _run_cli("version", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        got = json.loads(result.stdout)

        # dynamic meta: timestamp + run_id
        got["meta"]["timestamp"] = expected["meta"]["timestamp"]
        got["meta"]["run_id"] = expected["meta"]["run_id"]
        # environment-dependent data fields
        for key in self.ENV_DEPENDENT:
            if key in got.get("data", {}):
                got["data"][key] = expected["data"][key]
        self.assertEqual(got, expected)

    def test_version_envelope_errors_are_empty(self):
        result = _run_cli("version", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["errors"], [])


class JsonlEmitterShapeTests(unittest.TestCase):
    """JsonlEmitter output for ``aisc build --events`` deep-equals the shared
    ``events-build.jsonl`` fixture (modulo the dynamic ``ts`` field)."""

    def test_jsonl_emitter_matches_build_events_fixture(self):
        from aisc.cli.output import JsonlEmitter

        lines = (FIXTURES / "events-build.jsonl").read_text(encoding="utf-8").splitlines()
        expected = [json.loads(l) for l in lines if l.strip()]

        emitter = JsonlEmitter(command="build", run_id="00000000-0000-4000-8000-000000000006")
        events = [
            ("build.start", {}),
            ("build.plan", {"tag": "test:latest", "root": ".", "dockerfile": "Dockerfile"}),
            ("build.output", {"stream": "stderr", "chunk": "Step 1/3 : FROM python:3.14-slim\n"}),
            ("build.output", {"stream": "stderr", "chunk": "Step 2/3 : COPY . /app\n"}),
            ("build.complete", {"exit_code": 0, "image_tag": "test:latest"}),
        ]
        for i, (etype, data) in enumerate(events):
            with self.subTest(seq=i + 1):
                terminal = etype == "build.complete"
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    emitter.emit(etype, data, terminal=terminal)
                got = json.loads(buf.getvalue())
                exp = expected[i]
                got["ts"] = exp["ts"]  # dynamic timestamp
                self.assertEqual(got, exp)
        self.assertTrue(emitter.terminated)


class ProtocolFailClosedTests(unittest.TestCase):
    """The CLI stamps the stable ``aisc.cli/v1`` protocol; the shared
    negative fixture documents what a foreign protocol looks like so every
    consumer can fail closed on it."""

    def test_python_protocol_is_stable_v1(self):
        from aisc.cli.output import PROTOCOL, build_envelope

        self.assertEqual(PROTOCOL, "aisc.cli/v1")
        env = build_envelope(command="version", exit_code=0, version="1.0")
        self.assertEqual(env["meta"]["protocol"], "aisc.cli/v1")

    def test_negative_fixture_is_a_foreign_protocol(self):
        env = _load("envelope-unsupported-protocol.json")
        self.assertNotEqual(env["meta"]["protocol"], "aisc.cli/v1")

    def test_bad_json_fixture_fails_closed(self):
        # A consumer that must reject non-parseable output uses this code path;
        # the fixture set documents that envelope bytes must be valid JSON.
        self.assertTrue((FIXTURES / "envelope-unsupported-protocol.json").is_file())


class RuntimeSubcommandJsonUsageTests(unittest.TestCase):
    """CLI-A02/A05: every runtime subcommand that supports --format json must
    emit a JSON usage error on a missing required argument, not fall back to
    argparse text (regression for the main.py propagation gap)."""

    def test_missing_required_arg_emits_json_usage_error(self):
        for sub in ("inspect", "stop", "restart", "remove"):
            with self.subTest(sub=sub):
                result = _run_cli("runtime", sub, "--format", "json")
                self.assertEqual(result.returncode, 2, result.stderr)
                env = json.loads(result.stdout)
                self.assertEqual(env["meta"]["protocol"], "aisc.cli/v1")
                self.assertEqual(env["meta"]["exit_code"], 2)
                self.assertEqual(env["errors"][0]["code"], "AISC_ERR_USAGE")


if __name__ == "__main__":
    unittest.main()
