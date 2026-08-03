"""Unit tests for runtime commands.

Tests preflight_runtime() logic with mocked Docker executor.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from aisc.application.runtime import preflight_runtime, validate_uuid_v4
from aisc.domain.models import RuntimeErrorCode


class TestUuidValidation:
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


class TestPreflightDockerCheck:
    """Test Docker availability check."""

    def test_docker_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            executor.run.return_value = Mock(returncode=0)

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
            executor.run.side_effect = Exception("Docker not found")

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


class TestPreflightWorkspaceCheck:
    """Test workspace validity check."""

    def test_workspace_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.run.return_value = Mock(returncode=1)  # Docker unavailable

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
        executor.run.return_value = Mock(returncode=1)

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


class TestPreflightImageCheck:
    """Test image existence check."""

    def test_image_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)

            executor = Mock()
            # Docker info succeeds, image inspect succeeds
            executor.run.side_effect = [
                Mock(returncode=0),  # docker info
                Mock(returncode=0),  # docker image inspect
            ]

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
            # Docker info succeeds, image inspect fails
            executor.run.side_effect = [
                Mock(returncode=0),  # docker info
                Mock(returncode=1),  # docker image inspect
            ]

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
            # Docker info fails
            executor.run.return_value = Mock(returncode=1)

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
            # Image check should still fail (not skip) when Docker is unavailable
            assert image_check.status == "fail"
            assert image_check.error_code == RuntimeErrorCode.IMAGE_NOT_FOUND


class TestPreflightNetworkCheck:
    """Test network mode validation."""

    def test_network_direct_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.run.return_value = Mock(returncode=1)

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
            executor.run.return_value = Mock(returncode=1)

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
            executor.run.return_value = Mock(returncode=1)

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


class TestPreflightConflictCheck:
    """Test runtime conflict detection."""

    def test_no_conflict_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)

            # Create empty registry
            (registry_root / "registry.json").write_text('{"default": "", "containers": {}}')

            executor = Mock()
            executor.run.return_value = Mock(returncode=0)

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
        """When registry cannot be read, must fail-closed with conflict error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            # Do NOT create registry - should trigger read error

            executor = Mock()
            executor.run.return_value = Mock(returncode=0)

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
            # Must fail-closed when registry is unreadable
            assert conflict_check.status == "fail"
            assert conflict_check.error_code == RuntimeErrorCode.RUNTIME_CONFLICT


class TestPreflightCanStart:
    """Test can_start and recommended_action logic."""

    def test_all_pass_can_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            workspace.mkdir(exist_ok=True)
            registry_root = workspace / ".aisc"
            registry_root.mkdir(exist_ok=True)
            (registry_root / "registry.json").write_text('{"default": "", "containers": {}}')

            executor = Mock()
            executor.run.side_effect = [
                Mock(returncode=0),  # docker info
                Mock(returncode=0),  # image inspect
            ]

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

    def test_any_fail_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = Mock()
            executor.run.return_value = Mock(returncode=1)

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
            assert result.recommended_action == "resolve_conflict"
