"""Feature tests for AISC runtime backward compatibility.

These tests document and protect the current behavior of `aisc run`,
ensuring that new runtime/session commands do not break existing workflows.
"""

import json
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
                root,
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
        """Verify registry upgrade: read v2.1.4, write new, old preserved."""
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
            containers = list_containers(root)
            self.assertIn("old-container", containers)
            self.assertEqual(containers["old-container"]["image"], "super-claude:v2.1.4")

            # Register a new container (simulating upgrade write)
            register(
                root,
                "new-container",
                {
                    "image": "super-claude:latest",
                    "workspace": "/new/workspace",
                    "network": "proxy",
                    "label": "new",
                },
            )

            # Old container should still exist
            containers = list_containers(root)
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
    """Tests for legacy commands documenting actual behavior, not just existence."""

    def test_shell_command_is_available(self):
        """Verify `aisc shell` command exists and shows help."""
        from aisc.cli.main import main

        with patch("sys.stdout", new=StringIO()), \
             patch("sys.stderr", new=StringIO()), \
             patch("sys.argv", ["aisc", "shell", "--help"]):
            try:
                main()
            except SystemExit as e:
                exit_code = e.code
            else:
                exit_code = 0

        # Should exit with 0 (help shown)
        self.assertEqual(exit_code, 0)

    def test_stop_command_is_available(self):
        """Verify `aisc stop` command exists and shows help."""
        from aisc.cli.main import main

        with patch("sys.stdout", new=StringIO()), \
             patch("sys.stderr", new=StringIO()), \
             patch("sys.argv", ["aisc", "stop", "--help"]):
            try:
                main()
            except SystemExit as e:
                exit_code = e.code
            else:
                exit_code = 0

        # Should exit with 0 (help shown)
        self.assertEqual(exit_code, 0)

    def test_switch_command_is_available(self):
        """Verify `aisc switch` command exists and shows help."""
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

    # TODO: After S0.2, add behavior characterization tests:
    # - shell → docker exec -it <name> bash
    # - stop → name/label resolution, idempotent, stable error codes
    # - switch → scope wrapper, quick provider argv


if __name__ == "__main__":
    unittest.main()
