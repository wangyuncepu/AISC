"""Unit tests for runtime commands.

Tests preflight_runtime() logic with mocked Docker executor.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from aisc.application.runtime import (
    compute_config_fingerprint,
    preflight_runtime,
    validate_uuid_v4,
)
from aisc.domain.models import (
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
    RuntimeErrorCode,
)


class TestUuidValidation(unittest.TestCase):
    """Test UUID v4 validation."""

    def test_valid_uuid_v4(self):
        assert validate_uuid_v4("550e8400-e29b-41d4-a716-446655440000")
        assert validate_uuid_v4("f47ac10b-58cc-4372-a567-0e02b2c3d479")
        assert validate_uuid_v4("6ba7b810-9dad-11d1-80b4-00c04fd430c8") is False  # v1
        assert validate_uuid_v4("not-a-uuid") is False
        assert validate_uuid_v4("550e8400-e29b-41d4-3716-446655440000") is False  # v3
        assert validate_uuid_v4("550e8400-e29b-41d4-5716-446655440000") is False  # v5

    def test_uuid_case_insensitive(self):
        assert validate_uuid_v4("550E8400-E29B-41D4-A716-446655440000")
        assert validate_uuid_v4("550e8400-E29B-41d4-a716-446655440000")


class TestPreflightDockerCheck(unittest.TestCase):
    """Test Docker availability check."""

    def test_docker_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            docker_check = next(c for c in result.checks if c.id == "docker")
            assert docker_check.status == "pass"
            assert docker_check.error_code is None

    def test_docker_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            docker_check = next(c for c in result.checks if c.id == "docker")
            assert docker_check.status == "fail"
            assert docker_check.error_code == RuntimeErrorCode.DOCKER_UNAVAILABLE


class TestPreflightWorkspaceCheck(unittest.TestCase):
    """Test workspace validity check."""

    def test_workspace_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=tmpdir,
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            workspace_check = next(c for c in result.checks if c.id == "workspace")
            assert workspace_check.status == "pass"

    def test_workspace_not_exists(self):
        executor = Mock()
        executor.preflight.side_effect = Exception("Docker not found")

        result = preflight_runtime(
            runtime_id="550e8400-e29b-41d4-a716-446655440000",
            workspace="/nonexistent/workspace",
            image="test:latest",
            network="direct",
            scope="project",
            owner="workbench",
            executor=executor,
            registry_root=None,
        )

        workspace_check = next(c for c in result.checks if c.id == "workspace")
        assert workspace_check.status == "fail"
        assert workspace_check.error_code == RuntimeErrorCode.WORKSPACE_INVALID


class TestPreflightImageCheck(unittest.TestCase):
    """Test image existence check."""

    def test_image_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.EXISTS,
                image="test:latest",
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            image_check = next(c for c in result.checks if c.id == "image")
            assert image_check.status == "pass"

    def test_image_not_found_when_docker_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.MISSING,
                image="test:latest",
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            image_check = next(c for c in result.checks if c.id == "image")
            assert image_check.status == "fail"
            assert image_check.error_code == RuntimeErrorCode.IMAGE_NOT_FOUND

    def test_image_check_skipped_when_docker_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=False, reason="daemon_unreachable"
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            docker_check = next(c for c in result.checks if c.id == "docker")
            assert docker_check.status == "fail"

            image_check = next(c for c in result.checks if c.id == "image")
            # Image check should fail with DOCKER_UNAVAILABLE when Docker is down
            assert image_check.status == "fail"
            assert image_check.error_code == RuntimeErrorCode.DOCKER_UNAVAILABLE


class TestPreflightNetworkCheck(unittest.TestCase):
    """Test network mode validation."""

    def test_network_direct_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=tmpdir,
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            network_check = next(c for c in result.checks if c.id == "network")
            assert network_check.status == "pass"

    def test_network_proxy_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=tmpdir,
                image="test:latest",
                network="proxy",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            network_check = next(c for c in result.checks if c.id == "network")
            assert network_check.status == "pass"

    def test_network_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=tmpdir,
                image="test:latest",
                network="invalid",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            network_check = next(c for c in result.checks if c.id == "network")
            assert network_check.status == "fail"
            assert network_check.error_code == RuntimeErrorCode.NETWORK_INVALID


class TestPreflightConflictCheck(unittest.TestCase):
    """Test runtime conflict detection."""

    def test_no_conflict_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)

            # Create empty registry
            (registry_root / "containers.json").write_text('{"default": "", "containers": {}}')

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            assert conflict_check.status == "pass"
            assert result.matching_runtime_id is None
            assert result.conflicts == []

    def test_registry_unreadable_fails_closed(self):
        """When registry exists but is corrupted/unreadable, must fail-closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir()

            # Create corrupted registry file
            (registry_root / "containers.json").write_text("not valid json {{{")

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            # Must fail-closed when registry is corrupted
            assert conflict_check.status == "fail"
            assert conflict_check.error_code == RuntimeErrorCode.RUNTIME_CONFLICT

    def test_registry_missing_means_empty(self):
        """When registry doesn't exist, treat as empty (no conflicts)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            # Do NOT create registry - fresh workspace

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            # Fresh workspace means no conflicts
            assert conflict_check.status == "pass"

    def _stale_registry(
        self,
        tmpdir: str,
        runtime_id: str,
        container_name: str = "aisc-wb-stale",
    ) -> Path:
        """Registry with one matching-fingerprint record for the given runtime.

        Built via json.dumps: a raw Windows tempdir path contains backslashes,
        and a hand-written JSON string would be invalid (the fail-closed read
        path would mask the branch under test).
        """
        workspace = Path(tmpdir)
        workspace.mkdir(exist_ok=True)
        registry_root = workspace / ".aisc"
        registry_root.mkdir(exist_ok=True)
        fingerprint = compute_config_fingerprint(
            "test:latest", "direct", "project", str(workspace)
        )
        data = {
            "default": container_name,
            "containers": {
                container_name: {
                    "runtime_id": runtime_id,
                    "workspace": str(workspace),
                    "scope": "project",
                    "owner": "workbench",
                    "config_fingerprint": fingerprint,
                }
            },
        }
        (registry_root / "containers.json").write_text(json.dumps(data))
        return registry_root

    def test_stale_record_missing_container_is_conflict(self):
        """A registry record matching the fingerprint whose container was deleted
        (stale) must report a conflict, never reuse - reusing a missing container
        dead-ends on RUNTIME_NOT_FOUND (observed 2026-08-10)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_id = "550e8400-e29b-41d4-a716-446655440000"
            registry_root = self._stale_registry(tmpdir, runtime_id)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.EXISTS, image="test:latest"
            )
            executor.run_captured.return_value = ProcessResult(
                stdout="", stderr="", exit_code=0
            )
            executor.inspect_container.return_value = ProcessResult(
                stdout="",
                stderr="Error: No such object: aisc-wb-stale",
                exit_code=1,
            )

            result = preflight_runtime(
                runtime_id=runtime_id,
                workspace=str(Path(tmpdir)),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            assert conflict_check.status == "fail"
            assert result.matching_runtime_id is None
            assert result.recommended_action == "resolve_conflict"
            assert any("stale" in c["reason"] for c in result.conflicts)

    def test_live_matching_container_still_recommends_reuse(self):
        """A registry record whose container is actually running still matches
        for reuse - only a missing container becomes a conflict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_id = "550e8400-e29b-41d4-a716-446655440000"
            registry_root = self._stale_registry(tmpdir, runtime_id)

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.EXISTS, image="test:latest"
            )
            executor.run_captured.return_value = ProcessResult(
                stdout="", stderr="", exit_code=0
            )
            executor.inspect_container.return_value = ProcessResult(
                stdout='[{"State": {"Running": true}}]', stderr="", exit_code=0
            )

            result = preflight_runtime(
                runtime_id=runtime_id,
                workspace=str(Path(tmpdir)),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            assert conflict_check.status == "pass"
            assert result.matching_runtime_id == runtime_id
            assert result.recommended_action == "reuse"


class TestPreflightCanStart(unittest.TestCase):
    """Test can_start and recommended_action logic."""

    def test_all_pass_can_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)
            (registry_root / "containers.json").write_text('{"default": "", "containers": {}}')

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.EXISTS,
                image="test:latest",
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            assert result.can_start is True
            assert result.recommended_action == "start"

    def test_image_missing_keeps_start_action(self):
        """S4.1.b: fresh install on an empty dir - image gate fails but the
        runtime_conflict check passes, so action stays "start" (not
        resolve_conflict). This was the mislabel: an empty workspace showed
        "工作区已有不兼容 Runtime" because any failed gate forced
        resolve_conflict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)
            (registry_root / "containers.json").write_text('{"default": "", "containers": {}}')

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.MISSING,
                image="test:latest",
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            image_check = next(c for c in result.checks if c.id == "image")
            assert image_check.status == "fail"
            assert conflict_check.status == "pass"
            assert result.can_start is False
            assert result.recommended_action == "start"

    def test_real_conflict_still_resolve_conflict(self):
        """A genuine runtime conflict (project runtime already exists for this
        workspace) must still recommend resolve_conflict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)
            (registry_root / "containers.json").write_text(
                '{"default": "", "containers": {"aisc-wb-conflict": {'
                f'"runtime_id": "22222222-2222-2222-2222-222222222222", '
                f'"workspace": "{workspace}", '
                f'"scope": "project", '
                f'"owner": "workbench", '
                f'"config_fingerprint": "old-fingerprint"}}}}'
            )

            executor = Mock()
            executor.preflight.return_value = DockerPreflightResult(
                docker_path="/usr/bin/docker", available=True, reason="ok"
            )
            executor.inspect_image.return_value = ImageInspectResult(
                status=ImageInspectStatus.EXISTS,
                image="test:latest",
            )
            executor.run_captured.return_value = ProcessResult(
                stdout="", stderr="", exit_code=0,
            )

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace=str(workspace),
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=registry_root,
            )

            conflict_check = next(c for c in result.checks if c.id == "runtime_conflict")
            assert conflict_check.status == "fail"
            assert result.recommended_action == "resolve_conflict"

    def test_any_fail_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.preflight.side_effect = Exception("Docker not found")

            result = preflight_runtime(
                runtime_id="550e8400-e29b-41d4-a716-446655440000",
                workspace="/nonexistent",
                image="test:latest",
                network="direct",
                scope="project",
                owner="workbench",
                executor=executor,
                registry_root=None,
            )

            assert result.can_start is False
            # Non-conflict gates keep action="start"; resolve_conflict is
            # reserved for actual runtime conflicts (S4.1.b regression).
            assert result.recommended_action == "start"
