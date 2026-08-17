"""Feature tests for AISC runtime backward compatibility.

These tests document and protect the current behavior of `aisc run`,
ensuring that new runtime/session commands do not break existing workflows.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# Import AISC modules
from aisc.adapters.container_registry import list_containers, register
from aisc.cli.commands.run import plan_run
from aisc.domain.models import RunPlan


class RuntimeBackwardCompatibilityTests(unittest.TestCase):
    """Tests ensuring new runtime commands don't break existing `aisc run` behavior."""

    def test_run_non_interactive_docker_argv_and_env(self):
        """Verify `aisc run --non-interactive` produces correct Docker argv."""
        with tempfile.TemporaryDirectory() as workspace:
            plan = plan_run(
                image="super-claude:latest",
                workspace=workspace,
                non_interactive=True,
                interactive=False,
                keep_alive=False,
            )

            argv = plan.docker_argv

            # Should set AISC_NON_INTERACTIVE=1
            self.assertIn("AISC_NON_INTERACTIVE=1", argv)

            # Should set CLAUDE_SCOPE=project
            self.assertIn("CLAUDE_SCOPE=project", argv)

            # Should NOT include -it (no TTY)
            self.assertNotIn("-it", argv)

            # Should include --rm (default behavior)
            self.assertIn("--rm", argv)

    def test_run_keep_alive_omits_rm_and_adds_detached(self):
        """Verify `aisc run --keep-alive` does not use --rm and uses -d."""
        with tempfile.TemporaryDirectory() as workspace:
            plan = plan_run(
                image="super-claude:latest",
                workspace=workspace,
                keep_alive=True,
                interactive=True,
                non_interactive=False,
            )

            argv = plan.docker_argv

            # Should NOT include --rm
            self.assertNotIn("--rm", argv)

            # Should include -d for detached mode as a standalone token
            # (not part of container name or other value)
            self.assertIn("-d", argv)

    def test_run_interactive_includes_it_flag(self):
        """Verify default `aisc run` (interactive) includes -it."""
        with tempfile.TemporaryDirectory() as workspace:
            plan = plan_run(
                image="super-claude:latest",
                workspace=workspace,
                interactive=True,
                non_interactive=False,
                keep_alive=False,
            )

            argv = plan.docker_argv

            # Interactive mode should include -it
            self.assertIn("-it", argv)

            # Should include --rm (default)
            self.assertIn("--rm", argv)

    def test_registry_schema_has_expected_fields(self):
        """Verify registry maintains backward-compatible schema."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            # Register a container with current schema
            register(
                root / ".aisc",  # Stage 7: registry root = state dir
                "test-container",
                {
                    "image": "super-claude:latest",
                    "workspace": "/test/workspace",
                    "network": "direct",
                    "label": "test",
                },
            )

            # Read raw registry JSON
            registry_path = root / ".aisc" / "containers.json"
            self.assertTrue(registry_path.exists())

            with open(registry_path) as f:
                registry = json.load(f)

            # Verify backward-compatible structure
            self.assertIn("default", registry)
            self.assertIn("containers", registry)
            self.assertIn("test-container", registry["containers"])

            container = registry["containers"]["test-container"]
            self.assertEqual(container["image"], "super-claude:latest")
            self.assertEqual(container["workspace"], "/test/workspace")
            self.assertEqual(container["network"], "direct")
            self.assertEqual(container["label"], "test")

    def test_registry_can_list_and_append_with_v2_1_4_format(self):
        """Verify registry upgrade: read v2.1.4, write new, old preserved, default restoration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            aisc_dir = root / ".aisc"
            aisc_dir.mkdir()

            # Write v2.1.4-format registry (numeric timestamp, no runtime_id/owner/scope)
            registry_path = aisc_dir / "containers.json"
            old_timestamp = time.time()
            old_registry = {
                "default": "old-container",
                "containers": {
                    "old-container": {
                        "image": "super-claude:v2.1.4",
                        "workspace": "/old/workspace",
                        "network": "direct",
                        "label": "old",
                        "created_at": old_timestamp,  # v2.1.4 used numeric timestamps
                    }
                },
            }
            with open(registry_path, "w") as f:
                json.dump(old_registry, f)

            # Should be able to list without error
            containers = list_containers(root / ".aisc")
            self.assertIn("old-container", containers)
            self.assertEqual(containers["old-container"]["image"], "super-claude:v2.1.4")

            # Register a new container (simulating upgrade write)
            register(
                root / ".aisc",  # Stage 7: registry root = state dir
                "new-container",
                {
                    "image": "super-claude:latest",
                    "workspace": "/new/workspace",
                    "network": "proxy",
                    "label": "new",
                },
            )

            # Old container should still exist
            containers = list_containers(root / ".aisc")
            self.assertIn("old-container", containers)
            self.assertIn("new-container", containers)

            # Old container metadata should be preserved
            self.assertEqual(containers["old-container"]["image"], "super-claude:v2.1.4")
            self.assertEqual(containers["old-container"]["network"], "direct")

            # Verify both containers coexist in raw JSON
            with open(registry_path) as f:
                registry = json.load(f)
            self.assertEqual(len(registry["containers"]), 2)
            self.assertIn("old-container", registry["containers"])
            self.assertIn("new-container", registry["containers"])

            # Test default restoration: unregister new-container (current default)
            from aisc.adapters.container_registry import unregister
            unregister(root / ".aisc", "new-container")

            # Verify new-container is removed
            containers = list_containers(root / ".aisc")
            self.assertNotIn("new-container", containers)
            self.assertIn("old-container", containers)

            # Verify default falls back to remaining old-container
            with open(registry_path) as f:
                registry = json.load(f)
            self.assertEqual(registry["default"], "old-container")

    def test_scope_environment_variables_are_set(self):
        """Verify scope-related environment variables are properly set in entrypoint."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        self.assertTrue(entrypoint_path.exists())

        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Verify temporary scope variables exist
        self.assertIn("temporary", entrypoint)
        self.assertIn('TEMP_HOME="/tmp/aisc-home"', entrypoint)

        # Verify project scope uses /root/app
        self.assertIn("project", entrypoint)
        self.assertIn("/root/app", entrypoint)

        # Verify config dirs are exported
        self.assertIn("export CLAUDE_CONFIG_DIR", entrypoint)
        self.assertIn("export CODEX_CONFIG_DIR", entrypoint)
        self.assertIn("export CC_SWITCH_CONFIG_DIR", entrypoint)


class ScopeWrapperBehaviorTests(unittest.TestCase):
    """Tests documenting current scope selection and environment setup."""

    def test_entrypoint_prompts_for_scope_in_interactive_mode(self):
        """Verify entrypoint shows scope selection menu."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Verify scope menu exists with actual format
        self.assertIn("1) 临时 temporary", entrypoint)
        self.assertIn("2) 项目 project", entrypoint)
        self.assertIn("read -r -p", entrypoint)

    def test_entrypoint_cli_scope_priority(self):
        """Verify CLI_SCOPE has priority over CLAUDE_SCOPE."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Find the priority line
        self.assertIn('SCOPE="${CLI_SCOPE:-${CLAUDE_SCOPE:-}}"', entrypoint)

        # Verify CLI_SCOPE is checked first (before CLAUDE_SCOPE)
        cli_scope_pos = entrypoint.find("CLI_SCOPE")
        claude_scope_pos = entrypoint.find("CLAUDE_SCOPE", cli_scope_pos + 1)
        self.assertLess(cli_scope_pos, claude_scope_pos)

    def test_entrypoint_scope_branches_set_different_config_dirs(self):
        """Verify temporary and project scopes set different config directories."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Find temporary scope branch
        temp_section_start = entrypoint.find('if [ "$SCOPE" = "global" ] || [ "$SCOPE" = "temp" ] || [ "$SCOPE" = "temporary" ]')
        self.assertGreater(temp_section_start, 0)

        # Temporary scope should use $TEMP_CLAUDE_DIR (defined as $TEMP_HOME/.claude)
        temp_section = entrypoint[temp_section_start:temp_section_start + 2000]
        self.assertIn('CLAUDE_CONFIG_DIR="$TEMP_CLAUDE_DIR"', temp_section)
        self.assertIn('CODEX_CONFIG_DIR="$TEMP_CODEX_DIR"', temp_section)

        # Verify TEMP_HOME is defined earlier in the script
        self.assertIn('TEMP_HOME="/tmp/aisc-home"', entrypoint)
        self.assertIn('TEMP_CLAUDE_DIR="$TEMP_HOME/.claude"', entrypoint)

        # Find else branch (project scope)
        else_pos = entrypoint.find("else", temp_section_start)
        self.assertGreater(else_pos, temp_section_start)

        project_section = entrypoint[else_pos:else_pos + 1000]
        # Project scope should use $PROJECT_CLAUDE_DIR (defined as /root/app/.claude)
        self.assertIn('CLAUDE_CONFIG_DIR="$PROJECT_CLAUDE_DIR"', project_section)
        self.assertIn('CODEX_CONFIG_DIR="$PROJECT_CODEX_DIR"', project_section)

        # Verify PROJECT_CLAUDE_DIR is defined earlier
        self.assertIn('PROJECT_CLAUDE_DIR="/root/app/.claude"', entrypoint)

    def test_cc_switch_config_dir_respects_scope(self):
        """Verify cc-switch uses scope-specific config directory."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Should set CC_SWITCH_CONFIG_DIR based on scope
        self.assertIn('CC_SWITCH_CONFIG_DIR="$TEMP_HOME/.cc-switch"', entrypoint)
        self.assertIn('CC_SWITCH_CONFIG_DIR="/root/app/.cc-switch"', entrypoint)


class LegacyCommandBehaviorTests(unittest.TestCase):
    """Tests locking down legacy command behavior BEFORE S0.2 refactoring."""

    def test_shell_produces_docker_exec_it_bash(self):
        """Verify `aisc shell` produces 'docker exec -it <name> bash'."""
        from aisc.cli.commands.container import cmd_shell, StatusResult
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock

        # Create a fake executor
        fake_executor = MagicMock()

        # Mock container discovery and status check
        fake_executor.run_captured.return_value = ProcessResult(
            exit_code=0,
            stdout="test-container\n",
            stderr="",
            command_not_found=False,
            timed_out=False,
        )

        # Mock status check - container exists and is running
        with patch("aisc.cli.commands.container.cmd_status") as mock_status:
            mock_status.return_value = StatusResult(
                exists=True,
                running=True,
                name="test-container",
            )

            # Mock streaming execution
            fake_executor.run_streaming.return_value = ProcessResult(
                exit_code=0,
                stdout="",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            # Execute shell command
            with patch("aisc.cli.commands.container.discover_container", return_value="test-container"):
                result = cmd_shell(name_override="test-container", executor=fake_executor)

            # Verify docker exec -it <name> bash was called
            fake_executor.run_streaming.assert_called_once()
            call_args = fake_executor.run_streaming.call_args[0][0]
            self.assertEqual(call_args, ["exec", "-it", "test-container", "bash"])

    def test_stop_produces_docker_stop_and_is_idempotent(self):
        """Verify `aisc stop` produces 'docker stop <name>' and is idempotent."""
        from aisc.cli.commands.container import cmd_stop, StatusResult
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock

        fake_executor = MagicMock()

        # Test 1: Stop a running container
        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="test-container"), \
             patch("aisc.adapters.container_registry.unregister"):

            mock_status.return_value = StatusResult(
                exists=True,
                running=True,
                name="test-container",
            )

            fake_executor.run_captured.return_value = ProcessResult(
                exit_code=0,
                stdout="test-container\n",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            result = cmd_stop(name_override="test-container", executor=fake_executor)

            # Verify docker stop was called
            fake_executor.run_captured.assert_called()
            call_args = fake_executor.run_captured.call_args[0][0]
            self.assertEqual(call_args, ["stop", "test-container"])

            # Verify result indicates stopped
            self.assertTrue(result["stopped"])
            self.assertFalse(result["already_stopped"])

        # Test 2: Stop an already-stopped container (idempotent)
        fake_executor.reset_mock()
        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="test-container"):

            mock_status.return_value = StatusResult(
                exists=True,
                running=False,  # Already stopped
                name="test-container",
            )

            result = cmd_stop(name_override="test-container", executor=fake_executor)

            # Should not call docker stop
            fake_executor.run_captured.assert_not_called()

            # Should return already_stopped=True
            self.assertFalse(result["stopped"])
            self.assertTrue(result["already_stopped"])

    def test_stop_raises_container_not_found_error(self):
        """Verify `aisc stop` raises AISC_ERR_CONTAINER_NOT_FOUND for missing containers."""
        from aisc.cli.commands.container import cmd_stop, StatusResult
        from aisc.domain.models import CliError
        from unittest.mock import MagicMock

        fake_executor = MagicMock()

        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="missing-container"):

            mock_status.return_value = StatusResult(
                exists=False,
                running=False,
                name="missing-container",
            )

            # Should raise CliError with specific error code
            with self.assertRaises(CliError) as cm:
                cmd_stop(name_override="missing-container", executor=fake_executor)

            self.assertEqual(cm.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")
            self.assertEqual(cm.exception.exit_code, 1)

    def test_stop_target_resolution_name_label_default(self):
        """Verify stop resolves targets via --name, --label, and default registry."""
        from aisc.cli.commands.container import cmd_stop
        from aisc.adapters.container_registry import register, list_containers
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            # Stage 7: resolve_target resolves the data-root state dir —
            # keep the test out of the real %LOCALAPPDATA%.
            os.environ["AISC_DATA_ROOT"] = str(root) + "-state"
            self.addCleanup(os.environ.pop, "AISC_DATA_ROOT", None)

            # Setup registry with multiple containers
            register(root / ".aisc", "container-a", {
                "image": "super-claude:latest",
                "workspace": "/workspace-a",
                "network": "direct",
                "label": "work",
            })
            register(root / ".aisc", "container-b", {
                "image": "super-claude:latest",
                "workspace": "/workspace-b",
                "network": "direct",
                "label": "test",
            })

            fake_executor = MagicMock()
            fake_executor.run_captured.return_value = ProcessResult(
                exit_code=0,
                stdout="container-a\n",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            # Test 1: --name takes priority over --label
            with patch("aisc.cli.commands.container.cmd_status") as mock_status:
                mock_status.return_value.exists = True
                mock_status.return_value.running = False

                result = cmd_stop(
                    name_override="container-a",
                    label_override="test",  # Points to container-b, but name should win
                    explicit_root=str(root),
                    executor=fake_executor,
                )

                self.assertEqual(result["name"], "container-a")

            # Test 2: --label resolves to matching container
            fake_executor.reset_mock()
            fake_executor.run_captured.return_value = ProcessResult(
                exit_code=0,
                stdout="container-b\n",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            with patch("aisc.cli.commands.container.cmd_status") as mock_status:
                mock_status.return_value.exists = True
                mock_status.return_value.running = False

                result = cmd_stop(
                    label_override="test",
                    explicit_root=str(root),
                    executor=fake_executor,
                )

                self.assertEqual(result["name"], "container-b")

            # Test 3: No args uses default from registry
            fake_executor.reset_mock()
            fake_executor.run_captured.return_value = ProcessResult(
                exit_code=0,
                stdout="container-b\n",  # Current default
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            with patch("aisc.cli.commands.container.cmd_status") as mock_status:
                mock_status.return_value.exists = True
                mock_status.return_value.running = False

                result = cmd_stop(
                    explicit_root=str(root),
                    executor=fake_executor,
                )

                # Should use default (container-b is last registered)
                self.assertEqual(result["name"], "container-b")

    def test_stop_calls_unregister_on_success(self):
        """Verify stop calls unregister when it successfully stops a container."""
        from aisc.cli.commands.container import cmd_stop
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock, patch

        fake_executor = MagicMock()
        fake_executor.run_captured.return_value = ProcessResult(
            exit_code=0,
            stdout="test-container\n",
            stderr="",
            command_not_found=False,
            timed_out=False,
        )

        # Mock all the dependencies
        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="test-container"), \
             patch("aisc.adapters.container_registry.unregister") as mock_unregister, \
             patch("aisc.application.resources.locate_aisc_root", return_value=Path("/mock/root")):

            mock_status.return_value.exists = True
            mock_status.return_value.running = True

            result = cmd_stop(
                name_override="test-container",
                executor=fake_executor,
            )

            # Verify unregister was called
            # Note: This tests the contract that stop should attempt to unregister.
            # The actual unregister implementation is tested separately.
            self.assertTrue(mock_unregister.called)
            call_args = mock_unregister.call_args
            self.assertEqual(call_args[0][1], "test-container")  # Second arg is container name

    def test_switch_command_is_available(self):
        """Verify `aisc switch` command exists (full behavior test requires interactive TTY)."""
        from aisc.cli.main import main

        with patch("sys.stdout", new=StringIO()), \
             patch("sys.stderr", new=StringIO()), \
             patch("sys.argv", ["aisc", "switch", "--help"]):
            try:
                main()
            except SystemExit as e:
                exit_code = e.code
            else:
                exit_code = 0

        # Should exit with 0 (help shown)
        self.assertEqual(exit_code, 0)

    def test_switch_produces_scope_wrapper_and_cc_switch(self):
        """Verify `aisc switch` produces docker exec with scope wrapper."""
        from aisc.cli.commands.container import cmd_switch, StatusResult
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock

        fake_executor = MagicMock()

        # Mock status check
        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="test-container"):

            mock_status.return_value = StatusResult(
                exists=True,
                running=True,
                name="test-container",
            )

            fake_executor.run_streaming.return_value = ProcessResult(
                exit_code=0,
                stdout="",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            # Execute switch without --quick (full TUI)
            result = cmd_switch(name_override="test-container", quick=None, executor=fake_executor)

            # Verify docker exec with scope wrapper was called
            fake_executor.run_streaming.assert_called_once()
            call_args = fake_executor.run_streaming.call_args[0][0]

            # Should use exec -it
            self.assertIn("exec", call_args)
            self.assertIn("-it", call_args)
            self.assertIn("test-container", call_args)

            # Should use bash wrapper for scope preservation
            self.assertIn("bash", call_args)
            # Should invoke cc-switch
            self.assertIn("cc-switch", " ".join(call_args))

    def test_switch_quick_mode_produces_provider_switch_argv(self):
        """Verify `aisc switch --quick <provider>` uses quick-provider argv."""
        from aisc.cli.commands.container import cmd_switch, StatusResult
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock

        fake_executor = MagicMock()

        with patch("aisc.cli.commands.container.cmd_status") as mock_status, \
             patch("aisc.cli.commands.container.discover_container", return_value="test-container"):

            mock_status.return_value = StatusResult(
                exists=True,
                running=True,
                name="test-container",
            )

            fake_executor.run_streaming.return_value = ProcessResult(
                exit_code=0,
                stdout="",
                stderr="",
                command_not_found=False,
                timed_out=False,
            )

            # Execute switch with --quick deepseek
            result = cmd_switch(name_override="test-container", quick="deepseek", executor=fake_executor)

            fake_executor.run_streaming.assert_called_once()
            call_args = fake_executor.run_streaming.call_args[0][0]

            # Should include provider switch command
            call_args_str = " ".join(call_args)
            self.assertIn("cc-switch", call_args_str)
            self.assertIn("provider", call_args_str)
            self.assertIn("switch", call_args_str)
            self.assertIn("deepseek", call_args_str)


class CLIParameterMappingTests(unittest.TestCase):
    """Tests ensuring CLI parameters correctly map to internal function calls."""

    def test_cli_non_interactive_flag_maps_to_plan_parameter(self):
        """Verify --non-interactive CLI flag correctly sets non_interactive=True."""
        from aisc.cli.commands.run import plan_run
        from unittest.mock import patch

        # Mock plan_run to capture parameters
        with patch("aisc.cli.commands.run.plan_run", wraps=plan_run) as mock_plan:
            from aisc.cli.main import main

            with tempfile.TemporaryDirectory() as workspace:
                with patch("sys.stdout", new=StringIO()), \
                     patch("sys.stderr", new=StringIO()), \
                     patch("sys.argv", ["aisc", "run", "--non-interactive",
                                        "--workspace", workspace, "--dry-run"]):
                    try:
                        main()
                    except SystemExit:
                        pass

                # Verify plan_run was called with non_interactive=True
                mock_plan.assert_called()
                call_kwargs = mock_plan.call_args[1]
                self.assertTrue(call_kwargs.get("non_interactive"))
                self.assertFalse(call_kwargs.get("interactive"))

    def test_cli_keep_alive_flag_maps_to_plan_parameter(self):
        """Verify --keep-alive CLI flag correctly sets keep_alive=True."""
        from aisc.cli.commands.run import plan_run
        from unittest.mock import patch

        with patch("aisc.cli.commands.run.plan_run", wraps=plan_run) as mock_plan:
            from aisc.cli.main import main

            with tempfile.TemporaryDirectory() as workspace:
                with patch("sys.stdout", new=StringIO()), \
                     patch("sys.stderr", new=StringIO()), \
                     patch("sys.argv", ["aisc", "run", "--keep-alive",
                                        "--workspace", workspace, "--dry-run"]):
                    try:
                        main()
                    except SystemExit:
                        pass

                # Verify plan_run was called with keep_alive=True
                mock_plan.assert_called()
                call_kwargs = mock_plan.call_args[1]
                self.assertTrue(call_kwargs.get("keep_alive"))

    def test_non_interactive_uses_run_non_interactive_executor(self):
        """Verify --non-interactive actually calls run_non_interactive(), not streaming."""
        from aisc.cli.commands.run import run_container
        from aisc.domain.models import ProcessResult
        from unittest.mock import MagicMock, patch

        # Create spy executor
        spy_executor = MagicMock()
        spy_executor.run_non_interactive.return_value = ProcessResult(
            exit_code=0,
            stdout="",
            stderr="",
            command_not_found=False,
            timed_out=False,
        )

        with tempfile.TemporaryDirectory() as workspace:
            # Execute run_container with non-interactive plan (no dry-run)
            with patch("aisc.cli.commands.run.RealDockerExecutor", return_value=spy_executor):
                from aisc.cli.commands.run import plan_run

                plan = plan_run(
                    image="super-claude:test",
                    workspace=workspace,
                    non_interactive=True,
                    interactive=False,
                    dry_run=False,  # Actually execute
                )

                result = run_container(plan, executor=spy_executor)

        # Verify run_non_interactive was called (not streaming/captured)
        spy_executor.run_non_interactive.assert_called_once()
        spy_executor.run_streaming.assert_not_called()
        spy_executor.run_captured.assert_not_called()

        # Verify correct argv was passed
        call_args = spy_executor.run_non_interactive.call_args[0][0]
        self.assertIn("AISC_NON_INTERACTIVE=1", call_args)
        self.assertIn("CLAUDE_SCOPE=project", call_args)
        self.assertNotIn("-it", call_args)


if __name__ == "__main__":
    unittest.main()
