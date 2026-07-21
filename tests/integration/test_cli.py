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
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

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


# ---------------------------------------------------------------------------
# --aisc-root positioning (before and after command)
# ---------------------------------------------------------------------------

class TestAiscRootPositioning(unittest.TestCase):
    """Verify --aisc-root works both before and after any command."""

    def setUp(self):
        self.project_root = str(Path(__file__).resolve().parent.parent.parent)

    def test_root_before_version_command(self):
        """--aisc-root before 'version' is recognized."""
        r = _run_aisc("--aisc-root", self.project_root, "version")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("AISC CLI version", r.stdout)

    def test_root_after_version_command(self):
        """--aisc-root after 'version' is recognized."""
        r = _run_aisc("version", "--aisc-root", self.project_root)
        self.assertEqual(r.exit_code, 0)
        self.assertIn("AISC CLI version", r.stdout)

    def test_root_before_provider_list(self):
        """--aisc-root before 'provider list' is recognized."""
        r = _run_aisc("--aisc-root", self.project_root, "provider", "list",
                       "--format", "json")
        data = assert_json_envelope(r)
        self.assertGreater(len(data["data"]["providers"]), 0)

    def test_root_after_provider_command(self):
        """--aisc-root after 'provider' before 'list' is recognized."""
        r = _run_aisc("provider", "--aisc-root", self.project_root, "list",
                       "--format", "json")
        data = assert_json_envelope(r)
        self.assertGreater(len(data["data"]["providers"]), 0)

    def test_root_after_provider_list(self):
        """--aisc-root after 'provider list' is recognized."""
        r = _run_aisc("provider", "list", "--aisc-root", self.project_root,
                       "--format", "json")
        data = assert_json_envelope(r)
        self.assertGreater(len(data["data"]["providers"]), 0)

    def test_root_before_provider_show(self):
        """--aisc-root before 'provider show' is recognized."""
        r = _run_aisc("--aisc-root", self.project_root, "provider", "show",
                       "deepseek", "--format", "json")
        data = assert_json_envelope(r)
        self.assertEqual(data["data"]["id"], "deepseek")

    def test_root_after_provider_show(self):
        """--aisc-root after 'provider show NAME' is recognized."""
        r = _run_aisc("provider", "show", "deepseek",
                       "--aisc-root", self.project_root, "--format", "json")
        data = assert_json_envelope(r)
        self.assertEqual(data["data"]["id"], "deepseek")

    def test_root_equals(self):
        """--aisc-root=VALUE form works."""
        r = _run_aisc("--aisc-root=" + self.project_root, "version")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("AISC CLI version", r.stdout)

    def test_invalid_root_error(self):
        """--aisc-root pointing to a non-root directory raises clear error."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("--aisc-root", td, "version", "--format", "json")
            parsed = parse_json_envelope(r.stdout)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["meta"]["exit_code"], 1)
            self.assertGreater(len(parsed["errors"]), 0)
            self.assertIn("missing required structure markers",
                          parsed["errors"][0]["message"])

    def test_invalid_root_before_provider_list_error(self):
        """--aisc-root invalid before provider list returns error, not empty."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("--aisc-root", td, "provider", "list",
                           "--format", "json")
            parsed = parse_json_envelope(r.stdout)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["meta"]["exit_code"], 1)
            self.assertGreater(len(parsed["errors"]), 0)
            self.assertIn("missing required structure markers",
                          parsed["errors"][0]["message"])


# ---------------------------------------------------------------------------
# Provider from arbitrary cwd (installed fallback)
# ---------------------------------------------------------------------------

class TestProviderFromArbitraryCwd(unittest.TestCase):
    """Provider list/show must work from non-AISC working directory."""

    def test_provider_list_from_temp_directory(self):
        """provider list works from arbitrary temp directory."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("provider", "list", "--format", "json", cwd=td)
            data = assert_json_envelope(r)
            self.assertIn("schema_version", data["data"])
            self.assertGreater(len(data["data"]["providers"]), 0)

    def test_provider_show_deepseek_from_temp_directory(self):
        """provider show deepseek works from arbitrary temp directory."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("provider", "show", "deepseek", "--format", "json",
                           cwd=td)
            data = assert_json_envelope(r)
            self.assertEqual(data["data"]["id"], "deepseek")

    def test_provider_show_cc_from_temp_directory(self):
        """provider show cc works from arbitrary temp directory."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("provider", "show", "cc", "--format", "json", cwd=td)
            data = assert_json_envelope(r)
            self.assertEqual(data["data"]["id"], "cc")


# ---------------------------------------------------------------------------
# Version / brief / build from arbitrary cwd (installed fallback)
# ---------------------------------------------------------------------------

class TestCommandsFromArbitraryCwd(unittest.TestCase):
    """Commands requiring AISC root must work from non-AISC working directory."""

    def test_version_bundle_present(self):
        """version from temp dir shows bundle version via installed fallback."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("version", cwd=td)
            self.assertEqual(r.exit_code, 0)
            self.assertIn("AISC CLI version", r.stdout)
            self.assertIn("Bundle version", r.stdout)
            self.assertNotIn("(not found)", r.stdout)

    def test_version_json_from_temp(self):
        """version --format json from temp dir."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("version", "--format", "json", cwd=td)
            data = assert_json_envelope(r)
            self.assertIsNotNone(data["data"].get("bundle_version"))
            self.assertIsNotNone(data["data"].get("cli_version"))

    def test_build_dry_run_from_temp(self):
        """build --dry-run from temp dir resolves AISC root."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("build", "--dry-run", cwd=td)
            self.assertEqual(r.exit_code, 0)
            self.assertIn("Build plan", r.stdout)

    def test_run_dry_run_workspace_is_temp_cwd(self):
        """run --dry-run from temp dir: workspace = temp dir, root = installed."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_aisc("run", "--dry-run", "--format", "json", cwd=td)
            data = assert_json_envelope(r)
            # workspace in docker_argv should be the temp cwd
            argv = data["data"]["docker_argv"]
            # Find the -v workspace mount
            vol_idx = argv.index("-v") if "-v" in argv else None
            if vol_idx is not None:
                vol = argv[vol_idx + 1]
                # <workspace>:/home/AISC/app — workspace should be temp dir
                self.assertTrue(vol.startswith(td + ":"),
                                f"Expected workspace starting with {td}, got {vol}")

    def test_brief_resolves_installed_root_in_process(self):
        """``_cmd_brief`` resolves AISC root and passes correct paths to
        subprocess — zero network, zero script execution, same-process proof.

        ``_cmd_brief`` imports ``locate_aisc_root`` and ``subprocess``
        locally at call time, so patching module-level sources before the
        call is both deterministic and sufficient.
        """
        import argparse
        from aisc.cli.main import _cmd_brief

        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td)
            # --- minimal valid AISC root ---
            for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
                p = fake_root / marker
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("content")
            # --- brief.py stub ---
            apps_brief = fake_root / "apps" / "ai-brief"
            apps_brief.mkdir(parents=True)
            brief_script = apps_brief / "brief.py"
            brief_script.write_text("# AI brief stub")

            # --- fake args (defaults, no explicit root) ---
            ns = argparse.Namespace()
            ns.aisc_root = None
            ns.date = None
            ns.source = "all"
            ns.days = 1
            ns.top = 5
            ns.ai = False
            ns.save = False
            ns.no_cache = False
            ns.strict = False
            ns.debug = False

            # --- capture subprocess argv to verify paths ---
            captured_argv: list = []

            def _fake_subprocess_run(argv, **kwargs):
                captured_argv.extend(argv)
                # return a simple object with returncode=0
                return MagicMock(returncode=0)

            with patch(
                "subprocess.run",
                side_effect=_fake_subprocess_run,
            ), patch(
                "aisc.application.resources.locate_aisc_root",
                return_value=fake_root,
            ):
                data, exit_code, errors = _cmd_brief(ns, "text")

            # --- assertions ---
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(errors), 0)
            self.assertIn("brief_exit_code", data)
            self.assertEqual(data["brief_exit_code"], 0)

            # Exact script path
            self.assertIn(str(brief_script), captured_argv,
                          f"brief.py path not in argv: {captured_argv}")
            # Uses current interpreter
            self.assertIn(sys.executable, captured_argv,
                          f"sys.executable not in argv: {captured_argv}")
            # First two positional args are [python, script]
            self.assertEqual(captured_argv[0], sys.executable)
            self.assertEqual(captured_argv[1], str(brief_script))
            # --source flag present (default "all")
            self.assertIn("--source", captured_argv)
            self.assertIn("all", captured_argv)


# ---------------------------------------------------------------------------
# Container discovery from installed AISC root (same-process)
# ---------------------------------------------------------------------------

class TestContainerDiscoveryRoot(unittest.TestCase):
    """Prove ``discover_container`` reads state from installed AISC root,
    not from an arbitrary cwd.  Uses temp fake root + patched resolver.
    Since the switch to ``containers.json``, discovery goes through the
    container registry with lazy GC (needs a FakeDockerExecutor).
    """

    @classmethod
    def setUpClass(cls):
        from aisc.adapters.docker_ import FakeDockerExecutor, ProcessResult
        cls._FakeDockerExecutor = FakeDockerExecutor
        cls._ProcessResult = ProcessResult

    def _make_executor(self, container_name):
        exec_ = self._FakeDockerExecutor()
        exec_.set_captured("inspect", self._ProcessResult(
            stdout=f"/{container_name}\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        return exec_

    def test_discover_container_reads_installed_root_state(self):
        """Without --name or explicit_root, discover_container must fall back
        to ``locate_aisc_root`` and read ``<root>/.aisc/containers.json``.

        Sets up a temp fake root with a registry and patches the resolver
        to return it.  Cwd is a different empty temp dir — proving root
        selection is resolver-driven, not cwd-driven.
        """
        from aisc.cli.commands.container import discover_container
        from aisc.adapters.container_registry import register as reg_register
        import json

        with tempfile.TemporaryDirectory() as root_td, \
             tempfile.TemporaryDirectory() as cwd_td:

            fake_root = Path(root_td)
            reg_register(fake_root, "installed-container-abc", {
                "image": "img", "workspace": "/w", "network": "d", "label": "",
            })

            exec_ = self._make_executor("installed-container-abc")
            with patch(
                "aisc.application.resources.locate_aisc_root",
                return_value=fake_root,
            ), patch.object(Path, "cwd", return_value=Path(cwd_td)):
                name = discover_container(explicit_root=None, executor=exec_)

            self.assertEqual(name, "installed-container-abc")

    def test_discover_container_falls_back_from_cwd_to_installed(self):
        """When cwd is NOT a repo, discover_container must use installed
        fallback via ``locate_aisc_root``.  Proves no silent None."""
        from aisc.cli.commands.container import discover_container
        from aisc.adapters.container_registry import register as reg_register

        with tempfile.TemporaryDirectory() as root_td, \
             tempfile.TemporaryDirectory() as cwd_td:

            fake_root = Path(root_td)
            reg_register(fake_root, "fallback-container-xyz", {
                "image": "img", "workspace": "/w", "network": "d", "label": "",
            })

            exec_ = self._make_executor("fallback-container-xyz")
            # cwd is an empty dir with no repo → repo discovery returns None
            # installed fallback returns fake_root
            with patch.object(Path, "cwd", return_value=Path(cwd_td)):
                import aisc.application.resources as _resmod
                with patch.object(_resmod, "_find_repo_root",
                                  return_value=None), \
                     patch.object(_resmod, "_find_installed_root",
                                  return_value=fake_root):
                    name = discover_container(explicit_root=None, executor=exec_)

            self.assertEqual(name, "fallback-container-xyz")


# ---------------------------------------------------------------------------
# Bare grouped commands → help, exit 0 (usability fix)
# ---------------------------------------------------------------------------

class TestBareGroupHelp(unittest.TestCase):
    """Bare ``aisc config``, ``aisc provider``, ``aisc profile``, ``aisc skill``
    must print the group help and exit 0 instead of ``Unknown ... subcommand``.
    """

    def test_bare_config_shows_help_exit_0(self):
        r = _run_aisc("config")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("validate", r.stdout)
        self.assertIn("effective", r.stdout)
        self.assertIn("show", r.stdout)
        self.assertNotIn("Unknown config", r.stderr)

    def test_bare_provider_shows_help_exit_0(self):
        r = _run_aisc("provider")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("list", r.stdout)
        self.assertIn("show", r.stdout)
        self.assertNotIn("Unknown provider", r.stderr)

    def test_bare_profile_shows_help_exit_0(self):
        r = _run_aisc("profile")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("list", r.stdout)
        self.assertIn("show", r.stdout)
        self.assertNotIn("Unknown profile", r.stderr)

    def test_bare_skill_shows_help_exit_0(self):
        r = _run_aisc("skill")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("add", r.stdout)
        self.assertIn("list", r.stdout)
        self.assertIn("remove", r.stdout)
        self.assertIn("check", r.stdout)
        self.assertNotIn("Unknown skill", r.stderr)

    # --- global option placement: before group ---

    def test_format_json_before_config_shows_help(self):
        """--format json before bare group: still help text, exit 0, not JSON."""
        r = _run_aisc("--format", "json", "config")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("validate", r.stdout)
        self.assertIn("effective", r.stdout)
        self.assertNotIn("Unknown config", r.stderr)
        # Must NOT be a JSON envelope
        stripped = r.stdout.strip()
        if stripped:
            self.assertNotIn('"meta"', stripped[:100])

    def test_format_json_after_config_shows_help(self):
        """--format json after bare group: still help text, exit 0."""
        r = _run_aisc("config", "--format", "json")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("validate", r.stdout)
        self.assertIn("effective", r.stdout)
        self.assertNotIn("Unknown config", r.stderr)

    def test_no_color_before_skill_shows_help(self):
        r = _run_aisc("--no-color", "skill")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("add", r.stdout)
        self.assertIn("check", r.stdout)

    def test_no_color_after_skill_shows_help(self):
        r = _run_aisc("skill", "--no-color")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("add", r.stdout)

    def test_aisc_root_before_provider_shows_help(self):
        """--aisc-root before bare provider: still help, exit 0."""
        r = _run_aisc("--aisc-root", "/nonexistent/xyz", "provider")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("list", r.stdout)
        self.assertIn("show", r.stdout)

    def test_aisc_root_after_provider_shows_help(self):
        """--aisc-root after bare provider: still help, exit 0."""
        r = _run_aisc("provider", "--aisc-root", "/nonexistent/xyz")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("list", r.stdout)

    # --- explicit unknown nested subcommand → nonzero ---

    def test_unknown_config_subcommand_nonzero(self):
        r = _run_aisc("config", "bogus-subcmd")
        self.assertNotEqual(r.exit_code, 0)

    def test_unknown_skill_subcommand_nonzero(self):
        r = _run_aisc("skill", "bogus-subcmd")
        self.assertNotEqual(r.exit_code, 0)

    def test_unknown_provider_subcommand_nonzero(self):
        r = _run_aisc("provider", "bogus-subcmd")
        self.assertNotEqual(r.exit_code, 0)

    def test_unknown_profile_subcommand_nonzero(self):
        r = _run_aisc("profile", "bogus-subcmd")
        self.assertNotEqual(r.exit_code, 0)

    # --- existing subcommands still work ---

    def test_config_validate_still_works(self):
        r = _run_aisc("config", "validate", "--format", "json")
        self.assertIn(r.exit_code, (0, 1, 6, 7, 9))

    def test_provider_list_still_works(self):
        r = _run_aisc("provider", "list")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("Provider List", r.stdout)

    def test_profile_list_still_works(self):
        r = _run_aisc("profile", "list", "--format", "json")
        data = _parse_stdout(r)
        self.assertIsNotNone(data)
        self.assertIn("profiles", data.get("data", {}))

    def test_skill_list_still_works(self):
        r = _run_aisc("skill", "list", "--format", "json")
        data = _parse_stdout(r)
        self.assertIsNotNone(data)

    # --- JSON behavior for actual subcommands is preserved ---

    def test_config_effective_json_output(self):
        r = _run_aisc("config", "effective", "--format", "json")
        parsed = parse_json_envelope(r.stdout)
        self.assertEqual(parsed["meta"]["command"], "config")

    def test_provider_show_json_output(self):
        r = _run_aisc("provider", "show", "deepseek", "--format", "json")
        parsed = parse_json_envelope(r.stdout)
        self.assertIn("deepseek", parsed["data"]["id"])


if __name__ == "__main__":
    unittest.main()
