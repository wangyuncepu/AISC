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
        self.assertNotIn('AISC_PROVIDERS_JSON="$AISC_DIR/providers.json"', entrypoint)
        self.assertIn('LEGACY_PROVIDERS_JSON="$AISC_DIR/providers.json"', entrypoint)
        self.assertIn('rm -f "$LEGACY_PROVIDERS_JSON"', entrypoint)
        self.assertIn("export CC_SWITCH_CONFIG_DIR", entrypoint)
        self.assertIn("export PROVIDERS_JSON", entrypoint)

    def test_entrypoint_starts_default_daemon_before_handoff(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        daemon_start = entrypoint.index("cc-switch daemon start")
        process_handoff = entrypoint.rindex('exec "$@"')
        self.assertLess(daemon_start, process_handoff)
        self.assertIn(
            'cc-switch daemon start --detach >"$CC_SWITCH_DAEMON_LOG" 2>&1',
            entrypoint,
        )
        self.assertNotIn(
            'cc-switch daemon start >"$CC_SWITCH_DAEMON_LOG" 2>&1 &',
            entrypoint,
        )
        readiness_check = entrypoint.index('CC_SWITCH_DAEMON_READY=1', daemon_start)
        proxy_enable = entrypoint.index("cc-switch proxy -a claude enable", daemon_start)
        self.assertLess(readiness_check, proxy_enable)
        self.assertIn('if [ "$CC_SWITCH_DAEMON_READY" = "1" ]; then', entrypoint)

    def test_entrypoint_initializes_codex_provider_before_enabling_route(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        daemon_ready = entrypoint.index(
            'if [ "$CC_SWITCH_DAEMON_READY" = "1" ]; then'
        )
        current_check = entrypoint.index(
            "cc-switch -a codex provider current", daemon_ready
        )
        import_live = entrypoint.index(
            "cc-switch -a codex provider import-live", current_check
        )
        official_fallback = entrypoint.index(
            "cc-switch -a codex provider switch codex-official", import_live
        )
        route_enable = entrypoint.index(
            "cc-switch proxy -a codex enable", official_fallback
        )

        self.assertIn('[ -s "$CODEX_CONFIG_DIR/config.toml" ]', entrypoint)
        self.assertLess(current_check, import_live)
        self.assertLess(import_live, official_fallback)
        self.assertLess(official_fallback, route_enable)

    def test_entrypoint_registers_factory_skills_for_claude_and_codex(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("cc-switch skills sync-method copy", entrypoint)
        self.assertIn('CC_SWITCH_SKILLS_HOME="/root"', entrypoint)
        self.assertIn('CC_SWITCH_SKILLS_SSOT="$CC_SWITCH_CONFIG_DIR/skills/gstack"', entrypoint)
        self.assertIn("INSERT OR IGNORE INTO skills", entrypoint)
        self.assertIn('"aisc:gstack"', entrypoint)
        self.assertIn("cc-switch skills sync", entrypoint)
        self.assertNotIn("cc-switch skills repos add garrytan/gstack", entrypoint)
        self.assertNotIn("cc-switch skills import-from-apps", entrypoint)

    def test_codex_wrapper_defaults_to_full_container_permissions(self):
        wrapper = (ROOT / "container" / "codex-wrapper").read_text(encoding="utf-8")

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", wrapper)
        self.assertIn("--dangerously-bypass-hook-trust", wrapper)
        self.assertIn("has_permission_flag", wrapper)
        self.assertIn('exec codex-real "${full_access_flags[@]}" "$@"', wrapper)

    def test_cc_switch_wrapper_maps_temp_scope_and_defaults_project_to_root(self):
        wrapper = (ROOT / "container" / "cc-switch-wrapper").read_text(
            encoding="utf-8"
        )
        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn('export HOME="/tmp/aisc-home"', wrapper)
        self.assertIn('export HOME="/root"', wrapper)
        self.assertIn('exec cc-switch-real "$@"', wrapper)
        self.assertIn(
            "COPY container/cc-switch-wrapper /usr/local/bin/cc-switch", dockerfile
        )
        self.assertIn("/usr/local/bin/cc-switch-real", dockerfile)

    def test_entrypoint_runs_as_sandboxed_root_without_permission_churn(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn('export IS_SANDBOX="${IS_SANDBOX:-1}"', entrypoint)
        self.assertIn('AISC_DIR="/root/.aisc"', entrypoint)
        self.assertNotIn("chown -R", entrypoint)
        self.assertNotIn("cleanup_permissions", entrypoint)

    def test_docker_image_contains_copyable_codex_factory_directory(self):
        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("/opt/aisc/factory/.codex/config.toml", dockerfile)
        self.assertIn("COPY container/_bundle/skills/ /opt/aisc/factory/.codex/skills/", dockerfile)
        self.assertIn("COPY container/global-claude.md /opt/aisc/factory/.codex/AGENTS.md", dockerfile)
        self.assertIn("WORKDIR /root", dockerfile)
        self.assertIn('ENV PATH="/opt/aisc/venv/bin:${PATH}"', dockerfile)
        self.assertIn("ENV IS_SANDBOX=1", dockerfile)
        self.assertIn("USER root", dockerfile)
        self.assertNotIn("USER AISC", dockerfile)
        self.assertNotIn("/home/AISC", dockerfile)
        self.assertNotIn(
            "codex --version >/dev/null 2>&1 || true",
            dockerfile,
        )

    def test_run_plan_uses_root_mounts_without_user_override(self):
        from aisc.domain.models import RunPlan

        argv = RunPlan(
            workspace="/tmp/workspace",
            provider_config_dir="/tmp/workspace/.aisc",
            name="aisc-test",
        ).docker_argv

        self.assertNotIn("--user", argv)
        self.assertIn("/tmp/workspace:/root", argv)
        self.assertIn("/tmp/workspace/.aisc:/root/.aisc", argv)

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
            "PROVIDERS_JSON": "/tmp/project $literal/.aisc/.cc-switch/providers.json",
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
