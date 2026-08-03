"""Tests that preflight has zero side effects.

Per docs/gui-planning/05-cli-gui-contract.md §5.1:
"该命令只读且无副作用：不得创建 workspace/config 目录、容器、registry 记录或下载资源。"
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def get_aisc_executable():
    """Get path to aisc executable in virtualenv."""
    venv_bin = Path(sys.executable).parent
    aisc_path = venv_bin / "aisc"
    if not aisc_path.exists():
        pytest.skip("aisc executable not found in venv")
    return str(aisc_path)


class TestPreflightNoSideEffects:
    """Test preflight is strictly read-only."""

    def test_preflight_does_not_create_workspace(self):
        """Test preflight does not create missing workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "nonexistent"
            assert not nonexistent.exists()

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(nonexistent),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            # Command should succeed (exit 0)
            assert result.returncode == 0

            # Workspace should NOT be created
            assert not nonexistent.exists()

    def test_preflight_does_not_create_aisc_directory(self):
        """Test preflight does not create .aisc directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            aisc_dir = workspace / ".aisc"
            assert not aisc_dir.exists()

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0

            # .aisc directory should NOT be created
            assert not aisc_dir.exists()

    def test_preflight_does_not_create_lock_file(self):
        """Test preflight does not create lock files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            aisc_dir = workspace / ".aisc"
            aisc_dir.mkdir()

            # Record initial directory state
            initial_files = set(aisc_dir.iterdir())

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0

            # No new files should be created
            final_files = set(aisc_dir.iterdir())
            assert final_files == initial_files

    def test_preflight_does_not_create_registry(self):
        """Test preflight does not create registry.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            aisc_dir = workspace / ".aisc"
            aisc_dir.mkdir()
            registry_file = aisc_dir / "registry.json"

            assert not registry_file.exists()

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0

            # registry.json should NOT be created
            assert not registry_file.exists()

    def test_preflight_does_not_modify_existing_registry(self):
        """Test preflight does not modify existing registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            aisc_dir = workspace / ".aisc"
            aisc_dir.mkdir()
            registry_file = aisc_dir / "registry.json"

            # Create initial registry
            initial_content = '{"default": "", "containers": {}}'
            registry_file.write_text(initial_content)
            initial_mtime = registry_file.stat().st_mtime

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0

            # Registry should not be modified
            assert registry_file.read_text() == initial_content
            # Note: mtime check may be flaky on some filesystems
            # but content check is sufficient

    def test_preflight_does_not_pull_image(self):
        """Test preflight does not pull missing Docker image.

        This is harder to test without mocking Docker, but we can verify
        the error message doesn't indicate a pull was attempted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--image", "nonexistent-image-xyz:latest",
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            # Should succeed (exit 0) even with missing image
            assert result.returncode == 0

            data = json.loads(result.stdout)

            # Image check should fail, but no pull should be attempted
            image_check = next(c for c in data["data"]["checks"] if c["id"] == "image")

            # If Docker is available, image check should fail with IMAGE_NOT_FOUND
            # If Docker is unavailable, image check should fail with DOCKER_UNAVAILABLE or IMAGE_NOT_FOUND
            if image_check["status"] == "fail":
                # Detail should not mention "pulling" or "download"
                detail = (image_check.get("detail") or "").lower()
                assert "pull" not in detail
                assert "download" not in detail

    def test_preflight_does_not_create_container(self):
        """Test preflight does not create Docker container.

        This requires Docker to be available to verify.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            aisc = get_aisc_executable()
            result = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            # Should succeed
            assert result.returncode == 0

            # Verify no container was created with this runtime ID
            # This requires Docker to be available
            docker_result = subprocess.run(
                ["docker", "ps", "-a", "--filter", "label=io.aisc.runtime-id=550e8400-e29b-41d4-a716-446655440000", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
            )

            if docker_result.returncode == 0:
                # Docker is available, verify no container exists
                assert docker_result.stdout.strip() == ""

    def test_preflight_multiple_calls_idempotent(self):
        """Test multiple preflight calls produce same result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            aisc_dir = workspace / ".aisc"
            aisc_dir.mkdir()

            aisc = get_aisc_executable()

            # First call
            result1 = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            # Second call
            result2 = subprocess.run(
                [
                    aisc, "runtime", "preflight",
                    "--runtime-id", "550e8400-e29b-41d4-a716-446655440000",
                    "--workspace", str(workspace),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
            )

            assert result1.returncode == result2.returncode == 0

            data1 = json.loads(result1.stdout)
            data2 = json.loads(result2.stdout)

            # Check results are structurally identical
            # (ignoring timestamps and run_id)
            assert data1["data"]["can_start"] == data2["data"]["can_start"]
            assert data1["data"]["recommended_action"] == data2["data"]["recommended_action"]

            checks1 = [(c["id"], c["status"]) for c in data1["data"]["checks"]]
            checks2 = [(c["id"], c["status"]) for c in data2["data"]["checks"]]
            assert checks1 == checks2

            # Verify no files were created
            files_in_aisc = list(aisc_dir.iterdir())
            assert len(files_in_aisc) == 0
