"""F2-C (fix2-design.md): the run-decoupled command family.

- `cli_runs` history: absolute-path upsert, cap, resume resolution
- `cmd_agent`: exec argv shape, --workspace resolution, passthrough after `--`
- `cmd_stop_all`: CLI-owned only (owner=workbench untouched)
- `aisc run` activation argv: -d, no --rm, no -it
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tempfile as _tf
_os_env = _tf.mkdtemp(prefix="aisc-test-data-")
os.environ.setdefault("AISC_DATA_ROOT", _os_env)

from aisc.cli.commands import runs as cli_runs  # noqa: E402
from aisc.cli.commands.agents import cmd_agent  # noqa: E402
from aisc.domain.models import ProcessResult  # noqa: E402


class CliRunsHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("AISC_DATA_ROOT")
        os.environ["AISC_DATA_ROOT"] = self._tmp.name
        # data root must satisfy the resolver's layout expectations
        (Path(self._tmp.name) / "config").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("AISC_DATA_ROOT", None)
        else:
            os.environ["AISC_DATA_ROOT"] = self._old
        self._tmp.cleanup()

    def test_record_upserts_by_absolute_path_newest_first(self):
        # Paths ride through Path() — the platform's absolute form (POSIX on
        # Linux, backslash locally); compare with the same normalization.
        p_a, p_b = str(Path("/home/tv/a")), str(Path("/home/tv/b"))
        cli_runs.record(p_a, "img", "direct", "")
        cli_runs.record(p_b, "img", "direct", "")
        cli_runs.record(p_a, "img2", "proxy", "L")  # upsert, not append
        items = cli_runs.list_runs()
        self.assertEqual([r["path"] for r in items], [p_a, p_b])
        self.assertEqual(items[0]["image"], "img2")
        self.assertEqual(items[0]["network"], "proxy")
        self.assertEqual(items[0]["label"], "L")

    def test_cap_bounds_the_history(self):
        with patch.object(cli_runs, "HISTORY_CAP", 3):
            for i in range(6):
                cli_runs.record(str(Path(f"/ws/{i}")), "img", "direct", "")
            self.assertEqual(len(cli_runs.list_runs()), 3)
            self.assertEqual(cli_runs.list_runs()[0]["path"], str(Path("/ws/5")))

    def test_resume_resolves_index_and_path(self):
        cli_runs.record("/home/tv/proj", "img", "direct", "")
        cli_runs.record("/home/tv/other", "img", "proxy", "")
        self.assertEqual(cli_runs.resolve_resume("1")["path"], str(Path("/home/tv/other")))
        self.assertEqual(cli_runs.resolve_resume("2")["path"], str(Path("/home/tv/proj")))
        self.assertEqual(cli_runs.resolve_resume(str(Path("/home/tv/proj")))["path"],
                         str(Path("/home/tv/proj")))
        self.assertIsNone(cli_runs.resolve_resume("99"))
        self.assertIsNone(cli_runs.resolve_resume("/nope"))

    def test_require_resume_raises_usage(self):
        from aisc.domain.models import CliError

        with self.assertRaises(CliError) as ctx:
            cli_runs.require_resume("7")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_USAGE")


class AgentSugarTests(unittest.TestCase):
    def _exec(self):
        ex = MagicMock()
        ex.run_streaming.return_value = ProcessResult(
            exit_code=0, stdout="", stderr="", command_not_found=False, timed_out=False)
        ex.run_captured.return_value = ProcessResult(
            exit_code=0, stdout="", stderr="", command_not_found=False, timed_out=False)
        return ex

    def test_claude_execs_into_active_container_with_passthrough(self):
        ex = self._exec()
        with patch("aisc.cli.commands.container.discover_container",
                   return_value="box-1") as disc:
            proc = cmd_agent("claude", ["-c", "--model", "x"], executor=ex)
        disc.assert_called_once()
        argv = ex.run_streaming.call_args[0][0]
        self.assertEqual(argv, ["exec", "-it", "box-1", "claude", "-c", "--model", "x"])

    def test_workspace_resolution_overrides_discovery(self):
        ex = self._exec()
        tmp = Path(tempfile.mkdtemp())
        entries = {
            "box-other": {"workspace": "/other"},
            "box-mine": {"workspace": "/home/tv/proj"},
        }
        with patch("aisc.adapters.container_registry.list_containers", return_value=entries), \
             patch("aisc.application.data_root.workspace_state_dir", return_value=tmp), \
             patch("aisc.cli.commands.container.discover_container") as disc:
            cmd_agent("codex", [], workspace="/home/tv/proj", executor=ex)
        disc.assert_not_called()
        argv = ex.run_streaming.call_args[0][0]
        self.assertEqual(argv[:4], ["exec", "-it", "box-mine", "codex"])

    def test_workspace_without_container_is_not_found(self):
        from aisc.domain.models import CliError

        tmp = Path(tempfile.mkdtemp())
        with patch("aisc.adapters.container_registry.list_containers", return_value={}), \
             patch("aisc.application.data_root.workspace_state_dir", return_value=tmp):
            with self.assertRaises(CliError) as ctx:
                cmd_agent("claude", [], workspace="/gone", executor=self._exec())
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_NOT_FOUND")

    def test_capture_mode_returns_envelope_dict(self):
        ex = self._exec()
        with patch("aisc.cli.commands.container.discover_container", return_value="box-1"):
            out = cmd_agent("claude", ["-c"], capture=True, executor=ex)
        ex.run_streaming.assert_not_called()
        self.assertEqual(out["container"], "box-1")
        self.assertEqual(out["exit_code"], 0)
        # No TTY rides along in capture mode — no -it in the exec argv.
        argv = ex.run_captured.call_args[0][0]
        self.assertEqual(argv, ["exec", "box-1", "claude", "-c"])


class StopAllTests(unittest.TestCase):
    def test_stop_all_skips_workbench_and_removes_cli_owned(self):
        from aisc.cli.commands.container import cmd_stop_all

        ex = MagicMock()
        ex.run_captured.return_value = ProcessResult(
            exit_code=0, stdout="", stderr="", command_not_found=False, timed_out=False)
        entries = {
            "cli-box": {"owner": "", "workspace": "/a"},
            "wb-box": {"owner": "workbench", "workspace": "/b"},
        }
        import tempfile as _t
        shared_root = Path(_t.mkdtemp())
        reg_dir = shared_root / "workspaces" / "h1" / "runtime"
        reg_dir.mkdir(parents=True)
        (reg_dir / "containers.json").write_text("{}", encoding="utf-8")
        with patch("aisc.adapters.container_registry.list_containers", return_value=entries), \
             patch("aisc.adapters.container_registry.unregister") as unreg, \
             patch("aisc.application.data_root.DataRootResolver.resolve_shared_root",
                   return_value=shared_root):
            out = cmd_stop_all(executor=ex)
        self.assertEqual([s["name"] for s in out["stopped"]], ["cli-box"])
        self.assertEqual(out["skipped"], 1)
        argvs = [c[0][0] for c in ex.run_captured.call_args_list]
        self.assertIn(["stop", "cli-box"], argvs)
        self.assertIn(["rm", "-f", "cli-box"], argvs)
        self.assertNotIn(["stop", "wb-box"], argvs)
        unreg.assert_called_once()


class ActivationArgvTests(unittest.TestCase):
    def test_activation_plan_is_detached_keepalive(self):
        from aisc.cli.commands.run import plan_run

        with tempfile.TemporaryDirectory() as ws:
            plan = plan_run(image="super-claude:latest", workspace=ws,
                            interactive=False, keep_alive=True)
        argv = plan.docker_argv
        self.assertIn("-d", argv)
        self.assertNotIn("--rm", argv)
        self.assertNotIn("-it", argv)


if __name__ == "__main__":
    unittest.main()


class AliasResumeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("AISC_DATA_ROOT")
        os.environ["AISC_DATA_ROOT"] = self._tmp.name
        (Path(self._tmp.name) / "config").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("AISC_DATA_ROOT", None)
        else:
            os.environ["AISC_DATA_ROOT"] = self._old
        self._tmp.cleanup()

    def test_alias_is_the_strongest_resume_key(self):
        p = str(Path("/home/tv/proj"))
        cli_runs.record(p, "img", "direct", "", alias="myproj")
        cli_runs.record(str(Path("/home/tv/other")), "img", "direct", "", alias="x")
        got = cli_runs.resolve_resume("myproj")
        self.assertIsNotNone(got)
        self.assertEqual(got["path"], p)

    def test_record_roundtrips_alias(self):
        cli_runs.record("/a", "img", "direct", "", alias="k")
        self.assertEqual(cli_runs.list_runs()[0]["alias"], "k")
        cli_runs.record("/a", "img", "direct", "", alias="")
        self.assertEqual(cli_runs.list_runs()[0]["alias"], "")


class WorkspacesViewTests(unittest.TestCase):
    def _setup_registries(self, tmp):
        import json as _json
        reg = Path(tmp) / "workspaces" / "h1" / "runtime"
        reg.mkdir(parents=True)
        (reg / "containers.json").write_text(_json.dumps({
            "default": "box-live",
            "containers": {
                "box-live": {"image": "i", "workspace": "/w/live",
                             "network": "direct", "label": "", "owner": ""},
                "box-dead": {"image": "i", "workspace": "/w/dead",
                             "network": "direct", "label": "", "owner": ""},
                "box-wb": {"image": "i", "workspace": "/w/wb",
                           "network": "direct", "label": "", "owner": "workbench"},
            },
        }), encoding="utf-8")

    def test_list_joins_docker_state_and_skips_workbench(self):
        from aisc.cli.commands.workspaces import cmd_workspaces

        tmp = tempfile.mkdtemp()
        self._setup_registries(tmp)
        ex = MagicMock()
        ex.run_captured.return_value = ProcessResult(
            exit_code=0,
            stdout="box-live\tUp 3 hours\nbox-dead\tExited (0)\nbox-wb\tUp 1 hour\n",
            stderr="", command_not_found=False, timed_out=False)
        with patch("aisc.application.data_root.DataRootResolver.resolve_shared_root",
                   return_value=Path(tmp)):
            rows = cmd_workspaces(executor=ex)
        # (the scan globs <shared>/workspaces/*/runtime)
        names = [r["container"] for r in rows]
        self.assertIn("box-live", names)
        self.assertIn("box-dead", names)
        self.assertNotIn("box-wb", names)
        live = next(r for r in rows if r["container"] == "box-live")
        self.assertTrue(live["running"])
        dead = next(r for r in rows if r["container"] == "box-dead")
        self.assertFalse(dead["running"])

    def test_stop_sweeps_only_running_cli_owned(self):
        from aisc.cli.commands.workspaces import cmd_workspaces_stop

        tmp = tempfile.mkdtemp()
        self._setup_registries(tmp)
        ex = MagicMock()
        ps = ProcessResult(exit_code=0,
                           stdout="box-live\tUp 3 hours\nbox-dead\tExited (0)",
                           stderr="", command_not_found=False, timed_out=False)
        ok = ProcessResult(exit_code=0, stdout="", stderr="",
                           command_not_found=False, timed_out=False)
        ex.run_captured.side_effect = lambda argv, timeout=None: ps if argv[:1] == ["ps"] else ok
        with patch("aisc.application.data_root.DataRootResolver.resolve_shared_root",
                   return_value=Path(tmp)):
            out = cmd_workspaces_stop(executor=ex)
        self.assertEqual([s["container"] for s in out["stopped"]], ["box-live"])
        argvs = [c[0][0] for c in ex.run_captured.call_args_list]
        self.assertIn(["stop", "box-live"], argvs)
        self.assertIn(["rm", "-f", "box-live"], argvs)
        self.assertNotIn(["stop", "box-dead"], argvs)


class PsMachineViewTests(unittest.TestCase):
    """`aisc ps` machine-wide scan (manual test r1 #1): the old cwd-anchored
    single registry never saw F2-C activations — ps now scans every
    workspace registry (the same data face as `aisc workspaces`)."""

    def _setup_registries(self, tmp):
        import json as _json
        reg = Path(tmp) / "workspaces" / "h1" / "runtime"
        reg.mkdir(parents=True)
        (reg / "containers.json").write_text(_json.dumps({
            "default": "box-live",
            "containers": {
                "box-live": {"image": "i", "workspace": "/w/live",
                             "network": "direct", "label": ""},
                "box-ghost": {"image": "i", "workspace": "/w/ghost",
                              "network": "direct", "label": ""},
                "box-wb": {"image": "i", "workspace": "/w/wb",
                           "network": "direct", "label": "", "owner": "workbench"},
            },
        }), encoding="utf-8")

    def test_scans_all_registries_with_active_star_and_gone(self):
        from aisc.cli.commands.container import cmd_ps

        tmp = tempfile.mkdtemp()
        self._setup_registries(tmp)
        ex = MagicMock()
        ex.run_captured.return_value = ProcessResult(
            exit_code=0,
            stdout="box-live\tUp 3 hours\nbox-wb\tExited (0) 5 minutes ago\n",
            stderr="", command_not_found=False, timed_out=False)
        with patch("aisc.application.data_root.DataRootResolver.resolve_shared_root",
                   return_value=Path(tmp)), \
             patch("aisc.cli.commands.runs.get_active", return_value="/w/live"):
            rows = cmd_ps(executor=ex)
        by_name = {r.name: r for r in rows}
        # ps is container-centric: workbench-owned rows are listed too
        self.assertEqual(set(by_name), {"box-live", "box-ghost", "box-wb"})
        self.assertTrue(by_name["box-live"].active)
        self.assertTrue(by_name["box-live"].running)
        # registered but docker never heard of it → gone (orphan hygiene)
        self.assertEqual(by_name["box-ghost"].status, "gone")
        self.assertFalse(by_name["box-ghost"].running)
        self.assertFalse(by_name["box-wb"].active)
        self.assertEqual(rows[0].name, "box-live")  # active sorts first

    def test_docker_down_shows_unknown_not_gone(self):
        from aisc.cli.commands.container import cmd_ps

        tmp = tempfile.mkdtemp()
        self._setup_registries(tmp)
        ex = MagicMock()
        ex.run_captured.return_value = ProcessResult(
            exit_code=1, stdout="", stderr="daemon down",
            command_not_found=False, timed_out=False)
        with patch("aisc.application.data_root.DataRootResolver.resolve_shared_root",
                   return_value=Path(tmp)):
            rows = cmd_ps(executor=ex)
        self.assertTrue(rows)
        # docker unreachable → nothing is guessed as gone
        self.assertTrue(all(r.status == "?" for r in rows))

    def test_explicit_root_is_a_data_root_seam(self):
        from aisc.cli.commands.container import cmd_ps

        tmp = tempfile.mkdtemp()
        self._setup_registries(tmp)
        ex = MagicMock()
        ex.run_captured.return_value = ProcessResult(
            exit_code=0, stdout="box-live\tUp 2 minutes\n",
            stderr="", command_not_found=False, timed_out=False)
        rows = cmd_ps(explicit_root=tmp, executor=ex)  # no resolver patch needed
        by_name = {r.name: r for r in rows}
        self.assertEqual(set(by_name), {"box-live", "box-ghost", "box-wb"})
        self.assertTrue(by_name["box-live"].running)
        self.assertEqual(by_name["box-ghost"].status, "gone")


class AgentWorkspaceResolveTests(unittest.TestCase):
    """`aisc claude --workspace <path>` resolution — the registry is a
    ``name → meta`` map (not a list), which the first F2-C cut got wrong."""

    def test_resolve_by_workspace_reads_dict_registry(self):
        from aisc.cli.commands.agents import _resolve_by_workspace

        tmp = Path(tempfile.mkdtemp())
        containers = {
            "box": {"workspace": "/w/live", "image": "i", "label": ""},
            "other": {"workspace": "/w/dead", "image": "i", "label": ""},
        }
        with patch("aisc.adapters.container_registry.list_containers",
                   return_value=containers), \
             patch("aisc.application.data_root.workspace_state_dir",
                   return_value=tmp):
            name = _resolve_by_workspace("/w/live", None)
        self.assertEqual(name, "box")

    def test_resolve_by_workspace_miss_raises(self):
        from aisc.cli.commands.agents import _resolve_by_workspace
        from aisc.domain.models import CliError

        tmp = Path(tempfile.mkdtemp())
        with patch("aisc.adapters.container_registry.list_containers",
                   return_value={"box": {"workspace": "/w/live"}}), \
             patch("aisc.application.data_root.workspace_state_dir",
                   return_value=tmp):
            with self.assertRaises(CliError):
                _resolve_by_workspace("/w/nope", None)
