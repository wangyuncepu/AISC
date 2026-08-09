"""Contract tests for runtime JSON output.

Tests that aisc runtime commands produce correct JSON envelopes per
docs/rfc/aisc-cli-v1.md and docs/gui-planning/05-cli-gui-contract.md.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def get_aisc_executable():
    """Get path to aisc executable in virtualenv."""
    venv_bin = Path(sys.executable).parent
    aisc_path = venv_bin / "aisc"
    if not aisc_path.exists():
        raise unittest.SkipTest("aisc executable not found in venv")
    return str(aisc_path)


class TestPreflightJsonContract(unittest.TestCase):
    """Test preflight JSON contract per §5.1."""

    def test_preflight_json_envelope_structure(self):
        """Test JSON envelope has required meta/data/errors fields."""
        aisc = get_aisc_executable()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"stderr: {result.stderr}"

            data = json.loads(result.stdout)

            # Check meta fields
            assert "meta" in data
            assert data["meta"]["protocol"] == "aisc.cli/v1"
            assert data["meta"]["command"] == "runtime"
            assert data["meta"]["exit_code"] == 0
            assert "timestamp" in data["meta"]
            assert "version" in data["meta"]
            assert "run_id" in data["meta"]

            # Check data fields
            assert "data" in data
            assert "spec" in data["data"]
            assert "checks" in data["data"]
            assert "can_start" in data["data"]
            assert "recommended_action" in data["data"]
            assert "matching_runtime_id" in data["data"]
            assert "conflicts" in data["data"]
            assert "observed_at" in data["data"]

            # Check errors field
            assert "errors" in data
            assert isinstance(data["errors"], list)

    def test_preflight_spec_contains_all_params(self):
        """Test spec field contains all input parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--image", "custom:tag",
                    "--network", "proxy",
                    "--scope", "temporary",
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            spec = data["data"]["spec"]

            assert spec["runtime_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert spec["workspace"] == str(Path(tmpdir).resolve())
            assert spec["image"] == "custom:tag"
            assert spec["network"] == "proxy"
            assert spec["scope"] == "temporary"

    def test_preflight_checks_array_structure(self):
        """Test checks array has correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            checks = data["data"]["checks"]

            assert isinstance(checks, list)
            assert len(checks) == 5

            # Check fixed IDs
            check_ids = [c["id"] for c in checks]
            assert check_ids == ["docker", "workspace", "image", "network", "runtime_conflict"]

            # Check each check has required fields
            for check in checks:
                assert "id" in check
                assert "status" in check
                assert check["status"] in ["pass", "warn", "fail"]
                assert "error_code" in check  # may be null
                assert "detail" in check  # may be null

    def test_preflight_invalid_uuid_returns_error(self):
        """Test invalid UUID returns error envelope with exit code 15."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "preflight",
                "--runtime-id", "not-a-uuid",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 15

        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 15
        assert data["data"] is None
        assert len(data["errors"]) == 1
        assert data["errors"][0]["code"] == "AISC_ERR_INVALID_RUNTIME_ID"

    def test_preflight_invalid_scope_returns_usage_error(self):
        """Test invalid scope returns usage error with exit code 2."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "preflight",
                "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                "--scope", "invalid",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        # argparse should reject invalid choice before reaching cmd
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 2

    def test_preflight_missing_required_arg_returns_usage_error(self):
        """Test missing --runtime-id returns usage error in JSON."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "preflight",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 2
        assert data["meta"]["protocol"] == "aisc.cli/v1"

    def test_preflight_can_start_logic(self):
        """Test can_start is false when any check fails."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "preflight",
                "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                "--workspace", "/nonexistent/workspace",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout)

        # Workspace check should fail
        workspace_check = next(c for c in data["data"]["checks"] if c["id"] == "workspace")
        assert workspace_check["status"] == "fail"

        # can_start should be false
        assert data["data"]["can_start"] is False
        # Non-conflict gates keep action="start"; resolve_conflict is
        # reserved for actual runtime conflicts (S4.1.b regression).
        assert data["data"]["recommended_action"] == "start"

    def test_preflight_recommended_action_values(self):
        """Test recommended_action is one of the allowed values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            action = data["data"]["recommended_action"]

            # Per contract §5.1: start, reuse, restart, resolve_conflict
            assert action in ["start", "reuse", "restart", "resolve_conflict"]

    def test_preflight_conflicts_is_array(self):
        """Test conflicts field is always an array."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            assert isinstance(data["data"]["conflicts"], list)

    def test_preflight_observed_at_iso8601(self):
        """Test observed_at is ISO 8601 timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", tmpdir,
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            observed_at = data["data"]["observed_at"]

            # Should match ISO 8601 format with Z suffix
            assert observed_at.endswith("Z")
            assert "T" in observed_at

    def test_preflight_success_exit_code_zero(self):
        """Test preflight returns exit code 0 even when checks fail.

        Per contract §5.1: command success means 'completed the checks',
        not 'config can start'. Check failures are reported in payload.
        """
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "preflight",
                "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                "--workspace", "/nonexistent",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        # preflight should succeed (exit 0) even when workspace check fails
        assert result.returncode == 0

        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 0

        # But can_start should be false
        assert data["data"]["can_start"] is False


class TestRuntimeSubcommandErrors(unittest.TestCase):
    """Test runtime subcommand error handling."""

    def test_unknown_runtime_subcommand_json(self):
        """Test unknown runtime subcommand returns JSON error."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "unknown",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 2
        assert "errors" in data

    def test_bare_runtime_command_shows_help(self):
        """Test bare 'aisc runtime' shows help (not JSON)."""
        result = subprocess.run(
            [get_aisc_executable(), "runtime"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "preflight" in result.stdout


def _docker_available() -> bool:
    """Return True if a Docker daemon is reachable."""
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=8)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # No docker binary (Windows runners) or it hangs without a daemon.
        return False
    return r.returncode == 0


VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


class TestRuntimeLifecycleJsonContract(unittest.TestCase):
    """Contract tests for runtime start/list/inspect/stop/restart/remove §5.2-5.5."""

    def test_invalid_runtime_id_returns_exit_15(self):
        """Every runtime subcommand rejecting a bad UUID returns exit 15."""
        for sub in ("inspect", "stop", "restart", "remove"):
            with self.subTest(sub=sub):
                result = subprocess.run(
                    [get_aisc_executable(), "runtime", sub,
                     "--runtime-id", "not-a-uuid", "--format", "json"],
                    capture_output=True, text=True,
                )
                assert result.returncode == 15, f"{sub}: {result.stderr}"
                data = json.loads(result.stdout)
                assert data["meta"]["exit_code"] == 15
                assert data["errors"][0]["code"] == "AISC_ERR_INVALID_RUNTIME_ID"

    def test_start_invalid_runtime_id_returns_exit_15(self):
        result = subprocess.run(
            [get_aisc_executable(), "runtime", "start",
             "--runtime-id", "nope", "--format", "json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 15
        data = json.loads(result.stdout)
        assert data["meta"]["exit_code"] == 15

    def test_list_envelope_structure(self):
        """runtime list returns a JSON envelope with data.runtimes list."""
        if not _docker_available():
            self.skipTest("Docker daemon not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "list",
                 "--workspace", tmpdir, "--format", "json"],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            data = json.loads(result.stdout)
            assert data["meta"]["command"] == "runtime"
            assert data["meta"]["exit_code"] == 0
            assert isinstance(data["data"]["runtimes"], list)
            assert "observed_at" in data["data"]

    def test_inspect_not_found_envelope(self):
        """runtime inspect of an absent runtime returns not_found, exit 0."""
        if not _docker_available():
            self.skipTest("Docker daemon not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "inspect",
                 "--runtime-id", VALID_UUID, "--workspace", tmpdir,
                 "--format", "json"],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            data = json.loads(result.stdout)
            assert data["data"]["state"] == "not_found"
            assert data["data"]["registry_state"] == "not_found"
            assert data["data"]["runtime_id"] == VALID_UUID

    def test_start_missing_image_returns_error_envelope(self):
        """runtime start with a missing image returns a non-zero error envelope."""
        if not _docker_available():
            self.skipTest("Docker daemon not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [get_aisc_executable(), "runtime", "start",
                 "--runtime-id", VALID_UUID, "--workspace", tmpdir,
                 "--image", "aisc-nonexistent:latest", "--format", "json"],
                capture_output=True, text=True,
            )
            assert result.returncode != 0
            data = json.loads(result.stdout)
            assert data["meta"]["exit_code"] != 0
            assert len(data["errors"]) >= 1
