"""Regression tests for the AISC/cc-switch runtime wiring."""

import unittest
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CcSwitchRuntimeTests(unittest.TestCase):
    def test_entrypoint_uses_project_local_cc_switch_config_and_catalog(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn('CC_SWITCH_CONFIG_DIR="$AISC_DIR/.cc-switch"', entrypoint)
        self.assertIn('PROVIDERS_JSON="$CC_SWITCH_CONFIG_DIR/providers.json"', entrypoint)
        self.assertIn('ln -s ../providers.json "$CC_SWITCH_PROVIDERS_JSON"', entrypoint)
        self.assertIn("export CC_SWITCH_CONFIG_DIR", entrypoint)
        self.assertIn("export PROVIDERS_JSON", entrypoint)

    def test_entrypoint_starts_default_daemon_before_handoff(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        daemon_start = entrypoint.index("cc-switch daemon start")
        process_handoff = entrypoint.rindex('exec "$@"')
        self.assertLess(daemon_start, process_handoff)
        self.assertNotIn("proxy enable", entrypoint)

    def test_cs_prefers_shared_catalog_and_syncs_live_provider(self):
        cs = (ROOT / "container" / "claude-switch").read_text(encoding="utf-8")

        provider_resolution = cs.index("# Resolve providers.json")
        explicit = cs.index('[ -n "${PROVIDERS_JSON:-}" ]', provider_resolution)
        aisc_fallback = cs.index('[ -n "${AISC_DIR:-}" ]', provider_resolution)
        self.assertLess(explicit, aisc_fallback)
        self.assertIn("cc-switch --app claude provider import-live", cs)

    def test_docker_exec_wrapper_preserves_cc_switch_runtime_paths(self):
        from aisc.cli.commands.container import _SCOPE_WRAPPER

        for name in (
            "CLAUDE_CONFIG_DIR",
            "CC_SWITCH_CONFIG_DIR",
            "AISC_DIR",
            "PROVIDERS_JSON",
            "CODEX_CONFIG_DIR",
            "CODEX_HOME",
        ):
            self.assertIn(f"{name}=*", _SCOPE_WRAPPER)
            self.assertIn(name, _SCOPE_WRAPPER.rsplit("export ", 1)[1])

    def test_docker_exec_wrapper_restores_literal_values(self):
        from aisc.cli.commands.container import _SCOPE_WRAPPER

        values = {
            "CLAUDE_CONFIG_DIR": "/tmp/claude config",
            "CC_SWITCH_CONFIG_DIR": "/tmp/.aisc/.cc-switch",
            "AISC_DIR": "/tmp/project $literal/.aisc",
            "PROVIDERS_JSON": "/tmp/project $literal/.aisc/providers.json",
            "CODEX_CONFIG_DIR": "/tmp/codex config",
            "CODEX_HOME": "/tmp/codex config",
        }
        environ = b"\0".join(
            f"{key}={value}".encode() for key, value in values.items()
        ) + b"\0"
        with tempfile.NamedTemporaryFile() as source:
            source.write(environ)
            source.flush()
            proc = subprocess.run(
                [
                    "bash", "-c", _SCOPE_WRAPPER, "aisc-scope",
                    source.name, "--", "bash", "-c",
                    'printf "%s\\n" "$CC_SWITCH_CONFIG_DIR" "$AISC_DIR" "$PROVIDERS_JSON"',
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout.splitlines(),
            [
                values["CC_SWITCH_CONFIG_DIR"],
                values["AISC_DIR"],
                values["PROVIDERS_JSON"],
            ],
        )
