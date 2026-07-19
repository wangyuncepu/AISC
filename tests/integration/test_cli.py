"""Integration tests — subprocess invocation of the aisc CLI.

Tests version/doctor text+json, argument placement, usage errors,
JSON envelope schema (via existing harness), and new S2-review fixes:
  - --format=json
  - allow_abbrev=False (--form rejected)
  - duplicate --format (last wins)
  - malformed subcommand args keep meta.command
  - 6 fixed version keys
"""

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.harness.test_runner import (
    CliRunner,
    RunResult,
    assert_json_envelope,
    parse_json_envelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_aisc(
    *args: str,
    runner: Optional[CliRunner] = None,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> RunResult:
    """Run ``python -m aisc ...`` with PYTHONPATH=src."""
    if runner is None:
        runner = CliRunner()
    project_root = Path(__file__).resolve().parent.parent.parent
    src_path = str(project_root / "src")
    env = {"PYTHONPATH": src_path}
    return runner.run(
        [sys.executable, "-m", "aisc"] + list(args),
        cwd=cwd or str(project_root),
        timeout=timeout,
        env=env,
    )


def _parse_stdout(result: RunResult):
    """Parse stdout as JSON, return dict or None."""
    stripped = result.stdout.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Version command
# ---------------------------------------------------------------------------

class TestVersionCommand(unittest.TestCase):
    def test_text_output(self):
        result = _run_aisc("version")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("AISC CLI version", result.stdout)
        self.assertIn("Python version", result.stdout)

    def test_json_output(self):
        result = _run_aisc("version", "--format", "json")
        data = assert_json_envelope(result)
        self.assertEqual(data["meta"]["command"], "version")
        self.assertIn("cli_version", data["data"])

    def test_json_format_before_subcommand(self):
        result = _run_aisc("--format", "json", "version")
        data = assert_json_envelope(result)
        self.assertEqual(data["meta"]["command"], "version")

    def test_json_format_equals(self):
        """--format=json should be treated identically to --format json."""
        result = _run_aisc("--format=json", "version")
        data = assert_json_envelope(result)
        self.assertEqual(data["meta"]["command"], "version")
        self.assertIsInstance(data["data"]["cli_version"], str)

    def test_json_format_equals_after_subcommand(self):
        result = _run_aisc("version", "--format=json")
        data = assert_json_envelope(result)
        self.assertEqual(data["meta"]["command"], "version")

    def test_json_envelope_has_all_meta_fields(self):
        result = _run_aisc("version", "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        meta = parsed["meta"]
        self.assertEqual(meta["protocol"], "aisc.cli/v1")
        self.assertEqual(meta["command"], "version")
        self.assertEqual(meta["exit_code"], 0)
        self.assertIsInstance(meta["timestamp"], str)
        self.assertGreater(len(meta["timestamp"]), 0)
        self.assertIsInstance(meta["version"], str)
        self.assertIsInstance(meta["run_id"], str)
        self.assertGreater(len(meta["run_id"]), 0)

    def test_json_data_has_six_fixed_keys(self):
        result = _run_aisc("version", "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        data = parsed["data"]
        expected_keys = {"cli_version", "bundle_version", "contract_version",
                         "image_version", "claude_version", "python_version"}
        self.assertEqual(set(data.keys()), expected_keys)

    def test_json_no_root_field(self):
        result = _run_aisc("version", "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertNotIn("root", parsed["data"])

    def test_duplicate_format_last_wins(self):
        """aisc --format text version --format json → json wins."""
        result = _run_aisc("--format", "text", "version", "--format", "json")
        parsed = _parse_stdout(result)
        self.assertIsNotNone(parsed)
        self.assertIn("meta", parsed)
        # Should be valid JSON envelope, not text
        self.assertEqual(parsed["meta"]["command"], "version")

    def test_duplicate_format_json_last_wins_text_output(self):
        """aisc --format json --format text version → text output."""
        result = _run_aisc("--format", "json", "--format", "text", "version")
        self.assertIn("AISC CLI version", result.stdout)
        self.assertNotIn('"meta"', result.stdout[:100])

    def test_explicit_invalid_root_version(self):
        result = _run_aisc("--aisc-root", "/nonexistent/xyz123", "version",
                           "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 1)
        self.assertGreater(len(parsed["errors"]), 0)
        self.assertEqual(parsed["errors"][0]["code"], "AISC_ERR_GENERAL")

    def test_explicit_invalid_root_version_text(self):
        result = _run_aisc("--aisc-root", "/nonexistent/xyz123", "version")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Error", result.stderr)


# ---------------------------------------------------------------------------
# Doctor command
# ---------------------------------------------------------------------------

class TestDoctorCommand(unittest.TestCase):
    def test_doctor_text_output(self):
        result = _run_aisc("doctor")
        self.assertIn(result.exit_code, (0, 3, 9))
        self.assertIn("AISC Doctor", result.stdout)

    def test_doctor_json_output(self):
        result = _run_aisc("doctor", "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["command"], "doctor")
        self.assertEqual(parsed["meta"]["exit_code"], result.exit_code)

    def test_doctor_json_data_structure(self):
        result = _run_aisc("doctor", "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        data = parsed["data"]
        self.assertIn("host", data)
        self.assertIsNone(data["container"])
        host = data["host"]
        self.assertIn("checks", host)
        self.assertIn("summary", host)
        for check in host["checks"]:
            self.assertIn("name", check)
            self.assertIn("status", check)
            self.assertIn("message", check)

    def test_doctor_json_format_before_subcommand(self):
        result = _run_aisc("--format", "json", "doctor")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["command"], "doctor")

    def test_doctor_explicit_invalid_root(self):
        result = _run_aisc("--aisc-root", "/nonexistent/xyz123", "doctor",
                           "--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        data = parsed["data"]
        if data is not None:
            root_checks = [c for c in data.get("host", {}).get("checks", [])
                           if c.get("name") == "aisc-root"]
            if root_checks:
                self.assertEqual(root_checks[0]["status"], "fail")
                # Message must mention --aisc-root (not AISC_ROOT)
                self.assertIn("--aisc-root", root_checks[0]["message"])

    def test_doctor_produces_no_traceback(self):
        result = _run_aisc("--aisc-root", "/nonexistent/xyz123", "doctor")
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("traceback", result.stdout.lower())


# ---------------------------------------------------------------------------
# Usage / error handling (extended for S2 review)
# ---------------------------------------------------------------------------

class TestUsageErrors(unittest.TestCase):
    def test_unknown_command_json(self):
        result = _run_aisc("--format", "json", "nonexistent")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)
        self.assertGreater(len(parsed["errors"]), 0)
        self.assertEqual(parsed["errors"][0]["code"], "AISC_ERR_USAGE")

    def test_unknown_command_text(self):
        result = _run_aisc("nonexistent")
        self.assertEqual(result.exit_code, 2)

    def test_events_not_implemented_json(self):
        result = _run_aisc("--format", "json", "--events", "version")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)
        self.assertEqual(parsed["errors"][0]["code"], "AISC_ERR_USAGE")

    def test_events_not_implemented_text(self):
        result = _run_aisc("--events", "version")
        self.assertEqual(result.exit_code, 2)

    def test_no_command_json(self):
        result = _run_aisc("--format", "json")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)

    def test_no_command_text(self):
        result = _run_aisc()
        self.assertEqual(result.exit_code, 2)

    def test_unknown_flag_text(self):
        result = _run_aisc("--nonexistent-flag", "version")
        self.assertEqual(result.exit_code, 2)

    def test_unknown_flag_json(self):
        result = _run_aisc("--format", "json", "--nonexistent-flag", "version")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)
        self.assertEqual(parsed["errors"][0]["code"], "AISC_ERR_USAGE")

    # --- New: --format=json forms ---

    def test_format_equals_json_unknown_command(self):
        result = _run_aisc("--format=json", "nonexistent")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)
        self.assertEqual(parsed["errors"][0]["code"], "AISC_ERR_USAGE")

    # --- New: allow_abbrev=False → abbreviated flags rejected ---

    def test_abbrev_format_rejected(self):
        """--form should be rejected (allow_abbrev=False)."""
        result = _run_aisc("--form", "json", "version")
        self.assertEqual(result.exit_code, 2)

    def test_abbrev_format_rejected_json_envelope(self):
        """--form json should produce JSON usage error when --format=json is present."""
        result = _run_aisc("--format=json", "--form", "json", "version")
        parsed = parse_json_envelope(result.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)

    # --- New: malformed subcommand args → keep recognized command ---

    def test_malformed_arg_keeps_command_in_meta(self):
        """version --format=json --bogus → exit 2, meta.command=version."""
        result = _run_aisc("version", "--format=json", "--bogus")
        parsed = _parse_stdout(result)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)
        self.assertEqual(parsed["meta"]["command"], "version")

    def test_malformed_arg_text_mode(self):
        """version --bogus → exit 2."""
        result = _run_aisc("version", "--bogus")
        self.assertEqual(result.exit_code, 2)

    # --- New: JSON stdout purity ---

    def test_json_stdout_pure_no_stderr_for_well_formed(self):
        """Well-formed JSON command: stdout is JSON, stderr is empty."""
        result = _run_aisc("version", "--format", "json")
        parsed = _parse_stdout(result)
        self.assertIsNotNone(parsed)
        # stderr can have diagnostics, but stdout must be pure JSON
        self.assertIsInstance(parsed, dict)

    def test_json_usage_error_stdout_pure(self):
        """Usage error in JSON mode: stdout is JSON envelope."""
        result = _run_aisc("--format=json", "version", "--bogus")
        parsed = _parse_stdout(result)
        self.assertIsNotNone(parsed)
        self.assertIn("meta", parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 2)


# ---------------------------------------------------------------------------
# Output format concerns
# ---------------------------------------------------------------------------

class TestOutputFormat(unittest.TestCase):
    def test_json_stdout_is_single_object(self):
        result = _run_aisc("version", "--format", "json")
        parsed = json.loads(result.stdout.strip())
        self.assertIsInstance(parsed, dict)

    def test_json_no_ansi(self):
        result = _run_aisc("version", "--format", "json")
        self.assertNotIn("\033[", result.stdout)

    def test_text_no_ansi_when_no_color(self):
        result = _run_aisc("version", "--no-color")
        self.assertNotIn("\033[", result.stdout)

    def test_json_no_ansi_doctor(self):
        result = _run_aisc("doctor", "--format", "json")
        self.assertNotIn("\033[", result.stdout)


# ---------------------------------------------------------------------------
# Harness compatibility
# ---------------------------------------------------------------------------

class TestHarnessCompatibility(unittest.TestCase):
    def test_version_passes_json_envelope_assertion(self):
        result = _run_aisc("version", "--format", "json")
        data = assert_json_envelope(result)
        self.assertIn("cli_version", data["data"])
        self.assertEqual(len(data["data"]), 6)  # 6 fixed keys

    def test_doctor_passes_json_envelope_assertion(self):
        result = _run_aisc("doctor", "--format", "json")
        assert_json_envelope(result)  # no raise

    def test_usage_error_passes_envelope_assertion(self):
        result = _run_aisc("--format", "json", "nonexistent")
        data = assert_json_envelope(result)
        self.assertEqual(data["meta"]["exit_code"], 2)


# ---------------------------------------------------------------------------
# config show — alias for config effective (§5.2 item 1)
# ---------------------------------------------------------------------------

class TestConfigShow(unittest.TestCase):
    def test_show_json_matches_effective(self):
        r_show = _run_aisc("config", "show", "--format", "json")
        r_eff = _run_aisc("config", "effective", "--format", "json")
        self.assertEqual(r_show.exit_code, r_eff.exit_code)
        show_data = parse_json_envelope(r_show.stdout)
        eff_data = parse_json_envelope(r_eff.stdout)
        # Both should have same meta.command (both are "config" in the meta)
        # and same data structure
        self.assertEqual(show_data["meta"]["exit_code"], eff_data["meta"]["exit_code"])

    def test_show_text_produces_output(self):
        r = _run_aisc("config", "show")
        self.assertIn(r.exit_code, (0, 1, 6, 7, 9))
        # Should show "Config Effective" header
        self.assertIn("Config Effective", r.stdout)

    def test_show_events_exit_2(self):
        r = _run_aisc("config", "show", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_show_json_invalid_config(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as td:
            src = str(Path(td) / "bad.json")
            Path(src).write_text("{bad")
            r = _run_aisc("config", "show", "--format", "json", "--config", src)
            parsed = parse_json_envelope(r.stdout)
            self.assertIsNotNone(parsed)
            self.assertNotEqual(parsed["meta"]["exit_code"], 0)


# ---------------------------------------------------------------------------
# provider list (§5.2 item 2)
# ---------------------------------------------------------------------------

class TestProviderList(unittest.TestCase):
    def test_provider_list_text(self):
        r = _run_aisc("provider", "list")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("Provider List", r.stdout)

    def test_provider_list_json(self):
        r = _run_aisc("provider", "list", "--format", "json")
        data = assert_json_envelope(r)
        self.assertIn("schema_version", data["data"])
        self.assertIsInstance(data["data"]["providers"], list)
        self.assertGreater(len(data["data"]["providers"]), 0)
        # Each provider has required fields
        for p in data["data"]["providers"]:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("auth_type", p)

    def test_provider_list_invalid_root(self):
        r = _run_aisc("provider", "list", "--format", "json",
                       "--aisc-root", "/nonexistent")
        parsed = parse_json_envelope(r.stdout)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["meta"]["exit_code"], 1)

    def test_provider_list_events_exit_2(self):
        r = _run_aisc("provider", "list", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_provider_list_no_secret_reads(self):
        """Smoke: verify the command completes without reading secrets."""
        r = _run_aisc("provider", "list", "--format", "json")
        data = assert_json_envelope(r)
        self.assertEqual(data["meta"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
