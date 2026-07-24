"""Regression tests for the AISC/cc-switch runtime wiring."""

import io
import importlib.util
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SKILLS_HELPER_PATH = ROOT / "container" / "cc_switch_skills.py"
SKILLS_HELPER_SPEC = importlib.util.spec_from_file_location(
    "aisc_cc_switch_skills",
    SKILLS_HELPER_PATH,
)
assert SKILLS_HELPER_SPEC and SKILLS_HELPER_SPEC.loader
SKILLS_HELPER = importlib.util.module_from_spec(SKILLS_HELPER_SPEC)
SKILLS_HELPER_SPEC.loader.exec_module(SKILLS_HELPER)


class CcSwitchRuntimeTests(unittest.TestCase):
    def test_entrypoint_uses_scope_local_cc_switch_config_without_legacy_catalog(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn('CC_SWITCH_CONFIG_DIR="$TEMP_HOME/.cc-switch"', entrypoint)
        self.assertIn('CC_SWITCH_CONFIG_DIR="/root/app/.cc-switch"', entrypoint)
        self.assertIn("export CC_SWITCH_CONFIG_DIR", entrypoint)
        self.assertNotIn("PROVIDERS_JSON", entrypoint)
        self.assertNotIn("providers.json", entrypoint)
        self.assertNotIn("AISC_DIR", entrypoint)
        self.assertNotIn(".aisc/secrets", entrypoint)

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

    def test_entrypoint_menu_opens_cc_switch_management_tui(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        menu_prompt = entrypoint.index('read -r -p "输入 1、2、3 或 4 [默认 1]: "')
        cc_switch_option = entrypoint.index(
            'echo "  4) cc-switch 打开 Provider、路由与 Skills 管理界面"'
        )
        cc_switch_handoff = entrypoint.index(
            '4) echo "▶️  启动 cc-switch 管理界面..."; exec cc-switch ;;'
        )

        self.assertLess(cc_switch_option, menu_prompt)
        self.assertLess(menu_prompt, cc_switch_handoff)

    def test_entrypoint_initializes_codex_provider_without_enabling_route(self):
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

        self.assertIn('[ -s "$CODEX_CONFIG_DIR/config.toml" ]', entrypoint)
        self.assertLess(current_check, import_live)
        self.assertLess(import_live, official_fallback)
        codex_proxy_enable_commands = [
            line
            for line in entrypoint.splitlines()
            if line.strip().startswith("cc-switch proxy -a codex enable")
        ]
        self.assertEqual([], codex_proxy_enable_commands)
        self.assertIn(
            "Codex 未自动启用 cc-switch 代理",
            entrypoint,
        )

    def test_entrypoint_registers_factory_skills_for_claude_and_codex(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")
        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")
        helper = SKILLS_HELPER_PATH.read_text(encoding="utf-8")

        self.assertIn('CC_SWITCH_SKILLS_HOME="/root/app"', entrypoint)
        self.assertIn("/usr/local/bin/lib/cc_switch_skills.py", entrypoint)
        self.assertIn('--mode "${AISC_SKILLS_SYNC:-auto}"', entrypoint)
        self.assertIn("cc-switch 内置 skills 已是最新，跳过同步", entrypoint)
        self.assertIn("宿主 Skills 已存在", entrypoint)
        self.assertIn("INSERT OR IGNORE INTO skills", helper)
        self.assertIn('f"aisc:{name}"', helper)
        self.assertIn('["skills", "sync-method", "copy"]', helper)
        self.assertIn('["skills", "sync"]', helper)
        self.assertNotIn(
            "enabled_claude = 1, enabled_codex = 1",
            helper,
        )
        self.assertNotIn("cc-switch skills import-from-apps", entrypoint)
        self.assertIn(
            "COPY container/cc-switch-skills/ /opt/aisc/skills/",
            dockerfile,
        )
        self.assertIn(
            "COPY container/cc_switch_skills.py /usr/local/bin/lib/cc_switch_skills.py",
            dockerfile,
        )
        self.assertIn("/opt/aisc/skills/.aisc-bundle.sha256", dockerfile)
        for skill_name in ("caveman", "document-skills", "grill-me", "superpowers"):
            self.assertTrue(
                (ROOT / "container" / "cc-switch-skills" / skill_name / "SKILL.md").is_file()
            )

    def test_codex_wrapper_defaults_to_full_container_permissions(self):
        wrapper = (ROOT / "container" / "codex-wrapper").read_text(encoding="utf-8")

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", wrapper)
        self.assertIn("--dangerously-bypass-hook-trust", wrapper)
        self.assertIn("has_permission_flag", wrapper)
        self.assertIn('exec codex-real "${full_access_flags[@]}" "$@"', wrapper)

    def test_cc_switch_wrapper_maps_temp_scope_and_defaults_project_to_root_app(self):
        wrapper = (ROOT / "container" / "cc-switch-wrapper").read_text(
            encoding="utf-8"
        )
        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn('export HOME="/tmp/aisc-home"', wrapper)
        self.assertIn('export HOME="/root/app"', wrapper)
        self.assertIn('exec cc-switch-real "$@"', wrapper)
        self.assertIn(
            "COPY container/cc-switch-wrapper /usr/local/bin/cc-switch", dockerfile
        )
        self.assertIn("/usr/local/bin/cc-switch-real", dockerfile)

    def test_entrypoint_runs_as_sandboxed_root_without_permission_churn(self):
        entrypoint = (ROOT / "container" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn('export IS_SANDBOX="${IS_SANDBOX:-1}"', entrypoint)
        self.assertIn('CC_SWITCH_CONFIG_DIR="/root/app/.cc-switch"', entrypoint)
        self.assertNotIn("chown -R", entrypoint)
        self.assertNotIn("cleanup_permissions", entrypoint)

    def test_docker_image_contains_copyable_codex_factory_directory(self):
        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("/opt/aisc/factory/.codex/config.toml", dockerfile)
        self.assertIn("COPY container/_bundle/skills/ /opt/aisc/factory/.codex/skills/", dockerfile)
        self.assertIn("COPY container/global-claude.md /opt/aisc/factory/.codex/AGENTS.md", dockerfile)
        self.assertIn("WORKDIR /root/app", dockerfile)
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
            name="aisc-test",
        ).docker_argv

        self.assertNotIn("--user", argv)
        self.assertIn("/tmp/workspace:/root/app", argv)
        self.assertNotIn("/tmp/workspace/.aisc:/root/app/.aisc", argv)

    def test_legacy_cs_provider_catalog_and_secret_store_are_removed(self):
        removed = (
            "container/claude-switch",
            "config/providers.json",
            "src/aisc/adapters/config_source.py",
            "src/aisc/adapters/secret_store.py",
            "src/aisc/application/provider_service.py",
            "src/aisc/cli/commands/provider.py",
        )
        for relative_path in removed:
            self.assertFalse((ROOT / relative_path).exists(), relative_path)

        dockerfile = (ROOT / "container" / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("/usr/local/bin/cs", dockerfile)
        self.assertNotIn("container/claude-switch", dockerfile)

    def test_quick_switch_delegates_directly_to_cc_switch(self):
        from aisc.cli.commands.container import _build_switch_argv

        argv = _build_switch_argv("aisc-test", "deepseek")
        self.assertEqual(
            argv[-7:],
            ["--", "cc-switch", "-a", "claude", "provider", "switch", "deepseek"],
        )
        self.assertNotIn("cs", argv)

    def test_aisc_config_schema_no_longer_owns_provider_or_auth(self):
        from aisc.schemas.config_schema import validate_config

        issues = validate_config(
            {
                "schema_version": 1,
                "provider": {
                    "id": "legacy",
                    "auth": {"secret_ref": "provider:legacy"},
                },
            }
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].reason_code, "unknown_key")

    def test_docker_exec_wrapper_preserves_cc_switch_runtime_paths(self):
        from aisc.cli.commands.container import _SCOPE_WRAPPER

        for name in (
            "CLAUDE_CONFIG_DIR",
            "CC_SWITCH_CONFIG_DIR",
            "CODEX_CONFIG_DIR",
            "CODEX_HOME",
        ):
            self.assertIn(f"{name}=*", _SCOPE_WRAPPER)
            self.assertIn(name, _SCOPE_WRAPPER.rsplit("export ", 1)[1])
        self.assertNotIn("AISC_DIR", _SCOPE_WRAPPER)
        self.assertNotIn("PROVIDERS_JSON", _SCOPE_WRAPPER)

    def test_docker_exec_wrapper_restores_literal_values(self):
        from aisc.cli.commands.container import _SCOPE_WRAPPER

        values = {
            "CLAUDE_CONFIG_DIR": "/tmp/claude config",
            "CC_SWITCH_CONFIG_DIR": "/tmp/.aisc/.cc-switch",
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
                    'printf "%s\\n" "$CC_SWITCH_CONFIG_DIR" "$CODEX_CONFIG_DIR"',
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
                values["CODEX_CONFIG_DIR"],
            ],
        )


class CcSwitchSkillSyncTests(unittest.TestCase):
    def _create_layout(
        self,
        root: Path,
        *,
        revision: str = "bundle-v1",
        states: dict[str, tuple[bool, bool]] | None = None,
        create_targets: bool = True,
    ) -> tuple[Path, Path, Path]:
        config_dir = root / ".cc-switch"
        skills_home = root / "home"
        bundle_dir = root / "bundle"
        config_dir.mkdir()
        bundle_dir.mkdir()
        (bundle_dir / SKILLS_HELPER.REVISION_FILE).write_text(
            f"{revision}\n",
            encoding="utf-8",
        )
        (config_dir / SKILLS_HELPER.MARKER_FILE).write_text(
            f"{revision}\n",
            encoding="utf-8",
        )

        for name, *_ in SKILLS_HELPER.BUNDLED_SKILLS:
            (bundle_dir / name).mkdir()
            (bundle_dir / name / "SKILL.md").write_text(name, encoding="utf-8")
            (config_dir / "skills" / name).mkdir(parents=True)

        db = sqlite3.connect(config_dir / "cc-switch.db")
        db.execute(
            """
            CREATE TABLE skills (
                id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                directory TEXT,
                repo_owner TEXT,
                repo_name TEXT,
                repo_branch TEXT,
                enabled_claude INTEGER,
                enabled_codex INTEGER,
                installed_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        states = states or {
            name: (True, True) for name, *_ in SKILLS_HELPER.BUNDLED_SKILLS
        }
        for name, *_ in SKILLS_HELPER.BUNDLED_SKILLS:
            enabled_claude, enabled_codex = states[name]
            db.execute(
                """
                INSERT INTO skills (
                    id, name, enabled_claude, enabled_codex
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    f"aisc:{name}",
                    name,
                    int(enabled_claude),
                    int(enabled_codex),
                ),
            )
            if create_targets and enabled_claude:
                (skills_home / ".claude" / "skills" / name).mkdir(parents=True)
            if create_targets and enabled_codex:
                (skills_home / ".codex" / "skills" / name).mkdir(parents=True)
        db.commit()
        db.close()
        return config_dir, skills_home, bundle_dir

    def test_auto_mode_skips_when_revision_registration_and_targets_are_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir, skills_home, bundle_dir = self._create_layout(Path(temp_dir))

            required, reason = SKILLS_HELPER.sync_required(
                config_dir=config_dir,
                skills_home=skills_home,
                bundle_dir=bundle_dir,
                revision="bundle-v1",
            )

        self.assertFalse(required)
        self.assertEqual(reason, "current")

    def test_disabled_skills_do_not_require_targets_or_get_reenabled(self):
        states = {
            name: (False, False) for name, *_ in SKILLS_HELPER.BUNDLED_SKILLS
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir, skills_home, bundle_dir = self._create_layout(
                Path(temp_dir),
                states=states,
                create_targets=False,
            )

            required, reason = SKILLS_HELPER.sync_required(
                config_dir=config_dir,
                skills_home=skills_home,
                bundle_dir=bundle_dir,
                revision="bundle-v1",
            )
            SKILLS_HELPER._register_skills(config_dir)
            db = sqlite3.connect(config_dir / "cc-switch.db")
            persisted_states = db.execute(
                "SELECT enabled_claude, enabled_codex FROM skills"
            ).fetchall()
            db.close()

        self.assertFalse(required)
        self.assertEqual(reason, "current")
        self.assertTrue(persisted_states)
        self.assertEqual(set(persisted_states), {(0, 0)})

    def test_missing_enabled_target_requires_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir, skills_home, bundle_dir = self._create_layout(
                Path(temp_dir),
                create_targets=False,
            )

            required, reason = SKILLS_HELPER.sync_required(
                config_dir=config_dir,
                skills_home=skills_home,
                bundle_dir=bundle_dir,
                revision="bundle-v1",
            )

        self.assertTrue(required)
        self.assertEqual(reason, "Claude target missing: caveman")

    def test_changed_bundle_revision_requires_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir, skills_home, bundle_dir = self._create_layout(Path(temp_dir))

            required, reason = SKILLS_HELPER.sync_required(
                config_dir=config_dir,
                skills_home=skills_home,
                bundle_dir=bundle_dir,
                revision="bundle-v2",
            )

        self.assertTrue(required)
        self.assertEqual(reason, "bundled skills revision changed")

    def test_successful_sync_writes_marker_after_cc_switch_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir, _, bundle_dir = self._create_layout(root)
            marker = config_dir / SKILLS_HELPER.MARKER_FILE
            marker.unlink()
            log_path = root / "skills.log"

            with log_path.open("w", encoding="utf-8") as log, patch.object(
                SKILLS_HELPER,
                "_run_cc_switch",
            ) as run_cc_switch:
                SKILLS_HELPER.synchronize(
                    config_dir=config_dir,
                    bundle_dir=bundle_dir,
                    revision="bundle-v2",
                    log=log,
                )

            calls = [call.args[0] for call in run_cc_switch.call_args_list]
            marker_content = marker.read_text(encoding="utf-8")

        self.assertEqual(
            calls,
            [
                ["skills", "list"],
                ["skills", "sync-method", "copy"],
                ["skills", "sync"],
            ],
        )
        self.assertEqual(marker_content, "bundle-v2\n")

    def test_failed_cc_switch_sync_does_not_write_current_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir, _, bundle_dir = self._create_layout(root)
            marker = config_dir / SKILLS_HELPER.MARKER_FILE
            marker.unlink()
            log_path = root / "skills.log"

            with log_path.open("w", encoding="utf-8") as log, patch.object(
                SKILLS_HELPER,
                "_run_cc_switch",
                side_effect=[
                    None,
                    None,
                    subprocess.CalledProcessError(1, ["cc-switch", "skills", "sync"]),
                ],
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    SKILLS_HELPER.synchronize(
                        config_dir=config_dir,
                        bundle_dir=bundle_dir,
                        revision="bundle-v2",
                        log=log,
                    )

            marker_exists = marker.exists()

        self.assertFalse(marker_exists)

    def test_unlocked_first_install_claims_missing_skills_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            config_dir.mkdir()
            log = io.StringIO()
            prompt = io.StringIO()

            approved = SKILLS_HELPER._approve_unlocked_sync(
                config_dir=config_dir,
                skills_home=skills_home,
                input_stream=io.StringIO(),
                prompt_stream=prompt,
                log=log,
            )

            claimed = (config_dir / "skills").is_dir()

        self.assertTrue(approved)
        self.assertTrue(claimed)
        self.assertEqual(prompt.getvalue(), "")
        self.assertIn("claimed .cc-switch/skills", log.getvalue())

    def test_unusable_lock_file_selects_confirmation_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / ".cc-switch"
            config_dir.mkdir()
            (config_dir / SKILLS_HELPER.LOCK_FILE).mkdir()
            log = io.StringIO()

            lock, locked = SKILLS_HELPER._try_acquire_lock(
                config_dir=config_dir,
                log=log,
            )

        self.assertIsNone(lock)
        self.assertFalse(locked)
        self.assertIn("confirmation fallback", log.getvalue())

    def test_unlocked_existing_host_skills_accepts_yes(self):
        class InteractiveInput(io.StringIO):
            def isatty(self):
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            (config_dir / "skills").mkdir(parents=True)
            (skills_home / ".claude" / "skills").mkdir(parents=True)
            (skills_home / ".codex" / "skills").mkdir(parents=True)
            log = io.StringIO()
            prompt = io.StringIO()

            approved = SKILLS_HELPER._approve_unlocked_sync(
                config_dir=config_dir,
                skills_home=skills_home,
                input_stream=InteractiveInput("YES\n"),
                prompt_stream=prompt,
                log=log,
            )

        self.assertTrue(approved)
        self.assertIn(".cc-switch/skills", prompt.getvalue())
        self.assertIn(".claude/skills", prompt.getvalue())
        self.assertIn(".codex/skills", prompt.getvalue())
        self.assertIn("[y/N]", prompt.getvalue())

    def test_unlocked_partial_host_skills_still_prompts_and_defaults_no(self):
        class InteractiveInput(io.StringIO):
            def isatty(self):
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            config_dir.mkdir()
            (skills_home / ".claude" / "skills").mkdir(parents=True)
            log = io.StringIO()
            prompt = io.StringIO()

            approved = SKILLS_HELPER._approve_unlocked_sync(
                config_dir=config_dir,
                skills_home=skills_home,
                input_stream=InteractiveInput("\n"),
                prompt_stream=prompt,
                log=log,
            )

        self.assertFalse(approved)
        self.assertIn(".claude/skills", prompt.getvalue())
        self.assertNotIn(".codex/skills", prompt.getvalue())
        self.assertIn("declined", log.getvalue())

    def test_unlocked_noninteractive_existing_skills_declines_without_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            (config_dir / "skills").mkdir(parents=True)
            log = io.StringIO()
            prompt = io.StringIO()

            approved = SKILLS_HELPER._approve_unlocked_sync(
                config_dir=config_dir,
                skills_home=skills_home,
                input_stream=io.StringIO("y\n"),
                prompt_stream=prompt,
                log=log,
            )

        self.assertFalse(approved)
        self.assertEqual(prompt.getvalue(), "")
        self.assertIn("non-interactive", log.getvalue())

    def test_unlocked_non_directory_skills_path_fails_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            config_dir.mkdir()
            (config_dir / "skills").write_text("not a directory", encoding="utf-8")

            with self.assertRaises(NotADirectoryError):
                SKILLS_HELPER._approve_unlocked_sync(
                    config_dir=config_dir,
                    skills_home=skills_home,
                    input_stream=io.StringIO(),
                    prompt_stream=io.StringIO(),
                    log=io.StringIO(),
                )

    def test_always_mode_still_requires_unlocked_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".cc-switch"
            skills_home = root / "home"
            bundle_dir = root / "bundle"
            log_path = root / "skills.log"
            bundle_dir.mkdir()
            (bundle_dir / SKILLS_HELPER.REVISION_FILE).write_text(
                "bundle-v2\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with (
                patch.object(
                    SKILLS_HELPER,
                    "_try_acquire_lock",
                    return_value=(None, False),
                ),
                patch.object(
                    SKILLS_HELPER,
                    "sync_required",
                    return_value=(False, "current"),
                ),
                patch.object(
                    SKILLS_HELPER,
                    "_approve_unlocked_sync",
                    return_value=False,
                ) as approve,
                patch.object(SKILLS_HELPER, "synchronize") as synchronize,
                patch.object(SKILLS_HELPER.sys, "stdout", stdout),
            ):
                result = SKILLS_HELPER.main(
                    [
                        "--config-dir",
                        str(config_dir),
                        "--skills-home",
                        str(skills_home),
                        "--bundle-dir",
                        str(bundle_dir),
                        "--log",
                        str(log_path),
                        "--mode",
                        "always",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "declined\n")
        approve.assert_called_once()
        synchronize.assert_not_called()
