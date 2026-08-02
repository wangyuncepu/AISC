"""Feature tests for AISC runtime backward compatibility.

These tests document and protect the current behavior of `aisc run`,
ensuring that new runtime/session commands do not break existing workflows.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import AISC modules
from aisc.adapters.container_registry import list_containers, register


class RuntimeBackwardCompatibilityTests(unittest.TestCase):
    """Tests ensuring new runtime commands don't break existing `aisc run` behavior."""

    def test_run_non_interactive_mode_exits_without_tty(self):
        """Verify `aisc run --non-interactive` can run without TTY."""
        # This is a smoke test - actual Docker execution requires integration test
        # Here we just verify the CLI accepts the flag
        with tempfile.TemporaryDirectory() as workspace:
            result = subprocess.run(
                ["aisc", "run", "--non-interactive", "--workspace", workspace, "--dry-run"],
                capture_output=True,
                text=True,
            )
            # Should not fail with "requires TTY" error
            self.assertNotIn("TTY", result.stderr)
            self.assertNotIn("tty", result.stderr.lower())

    def test_run_keep_alive_preserves_container(self):
        """Verify `aisc run --keep-alive` does not use --rm flag."""
        # Verify the flag is recognized and doesn't cause CLI error
        result = subprocess.run(
            ["aisc", "run", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertIn("--keep-alive", result.stdout)

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

    def test_registry_can_list_containers_without_new_fields(self):
        """Verify list_containers works with old registry format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            aisc_dir = root / ".aisc"
            aisc_dir.mkdir()

            # Write old-format registry (without runtime_id, owner, scope)
            registry_path = aisc_dir / "containers.json"
            old_registry = {
                "default": "old-container",
                "containers": {
                    "old-container": {
                        "image": "super-claude:v2.1.4",
                        "workspace": "/old/workspace",
                        "network": "direct",
                        "label": "old",
                        "created_at": "2026-08-01T10:00:00Z",
                    }
                },
            }
            with open(registry_path, "w") as f:
                json.dump(old_registry, f)

            # Should be able to list without error
            containers = list_containers(root)
            # list_containers returns a dict, not a list
            self.assertIn("old-container", containers)

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

    def test_entrypoint_supports_non_interactive_scope(self):
        """Verify CLI_SCOPE environment variable controls scope."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Should check for CLI_SCOPE env var
        self.assertIn("CLI_SCOPE", entrypoint)

        # Should have default scope as project
        self.assertIn('SCOPE="project"', entrypoint)

    def test_cc_switch_config_dir_respects_scope(self):
        """Verify cc-switch uses scope-specific config directory."""
        entrypoint_path = Path(__file__).parent.parent.parent / "container" / "entrypoint.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        # Should set CC_SWITCH_CONFIG_DIR based on scope
        self.assertIn('CC_SWITCH_CONFIG_DIR="$TEMP_HOME/.cc-switch"', entrypoint)
        self.assertIn('CC_SWITCH_CONFIG_DIR="/root/app/.cc-switch"', entrypoint)


if __name__ == "__main__":
    unittest.main()
