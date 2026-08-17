"""Stage 7 (7e, DATA-01/04): state wiring — workspace stays clean.

The registry boundary (``workspace_state_dir`` + the CLI/runtime call
sites) must write AISC-owned state ONLY under the data root, adopt legacy
``<workspace>/.aisc`` state on first use, and never create ``.aisc`` in a
fresh workspace.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aisc.adapters.container_registry import list_containers, register
from aisc.application.data_root import DataRootResolver, workspace_state_dir
from aisc.domain.data_root import workspace_dir_name


def _resolved(ws: Path, root: Path):
    return DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)


class StateWiringTests(unittest.TestCase):
    def test_state_dir_is_under_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            resolved = _resolved(ws, root)
            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                state = workspace_state_dir(ws)
            self.assertEqual(
                state,
                root / "workspaces" / workspace_dir_name(resolved.workspace_hash) / "runtime",
            )

    def test_fresh_workspace_never_gains_dot_aisc(self) -> None:
        """DATA-01 core: registering state leaves the workspace untouched."""
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                state = workspace_state_dir(ws)
            register(state, "c1", {
                "image": "super-claude:test", "workspace": "/w",
                "network": "direct", "label": "x",
            })
            self.assertEqual(set(list_containers(state)), {"c1"})
            # The workspace gained NOTHING.
            self.assertEqual(list(p.name for p in ws.iterdir()), [])

    def test_legacy_state_adopted_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            legacy = ws / ".aisc"
            legacy.mkdir()
            (legacy / "containers.json").write_text(
                '{"default": "old-c", "containers": {"old-c": {"image": "i"}}}',
                encoding="utf-8",
            )
            (legacy / "user-unknown.txt").write_text("keep me", encoding="utf-8")

            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                state = workspace_state_dir(ws)

            adopted = json.loads((state / "containers.json").read_text("utf-8"))
            self.assertEqual(adopted["default"], "old-c")
            # Unknown legacy files are NOT adopted (migration handles them).
            self.assertFalse((state / "user-unknown.txt").exists())
            # Legacy source kept intact (no destructive move).
            self.assertTrue((legacy / "containers.json").is_file())
            self.assertEqual(set(list_containers(state)), {"old-c"})

    def test_existing_data_root_state_wins_over_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            resolved = _resolved(ws, root)
            state = resolved.workspace_dirs["runtime"]
            state.mkdir(parents=True)
            (state / "containers.json").write_text(
                '{"default": "new-c", "containers": {}}', encoding="utf-8"
            )
            legacy = ws / ".aisc"
            legacy.mkdir()
            (legacy / "containers.json").write_text(
                '{"default": "stale", "containers": {}}', encoding="utf-8"
            )

            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                got = workspace_state_dir(ws)
            self.assertEqual(json.loads(
                (got / "containers.json").read_text("utf-8"))["default"], "new-c")

    def test_invalid_override_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp:
            ws = Path(ws_tmp)
            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": "relative/x"}):
                with self.assertRaises(Exception):
                    workspace_state_dir(ws)
            # Nothing was created anywhere near the workspace.
            self.assertEqual(list(p.name for p in ws.iterdir()), [])


class ArtifactRootWiringTests(unittest.TestCase):
    """DATA-04: artifact registry lives under <data-root>/artifacts; the
    pre-Stage-7 root stays readable (transition fallback)."""

    def test_canonical_and_legacy_fallback(self) -> None:
        from aisc.adapters.data_root_store import SCOPE_SHARED  # noqa: F401
        from aisc.application.artifact import (
            _legacy_data_root,
            data_root,
            list_records,
            registry_path,
        )
        from aisc.domain.artifacts import ArtifactRecord

        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            with mock.patch.dict(os.environ, {
                "AISC_DATA_ROOT": str(root),
                "AISC_ARTIFACT_DATA_ROOT": "",  # let the data root win
            }):
                self.assertEqual(data_root(), root / "artifacts")

                # Write goes to the canonical location.
                rec = ArtifactRecord(
                    artifact_id="11111111-1111-4111-8111-111111111111",
                    workspace_relative_path="out/a.txt",
                    producer={"agent": "claude", "session_id": "s1",
                              "runtime_id": "r1"},
                ).validate()
                from aisc.application.artifact import record
                record(ws, rec, session_id="s1")
                self.assertTrue(registry_path(ws, "s1").is_file())
                self.assertEqual(len(list_records(ws)), 1)

                # Legacy-only records remain readable when canonical is empty
                # (simulate: point the canonical override elsewhere).
                with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root) + "-empty"}):
                    legacy = _legacy_data_root()
                    self.assertNotEqual(legacy, root / "artifacts")
                    # legacy fallback only triggers on a real legacy tree —
                    # verified in integration; here the empty canonical root
                    # must simply report nothing (no crash).
                    self.assertEqual(list_records(ws), [])


class ContainerMountWiringTests(unittest.TestCase):
    """DATA-01 at the docker-argv level: project runs mount agent state
    from the data root and never copy into the workspace."""

    def test_plan_run_mounts_data_root_and_keeps_workspace_clean(self) -> None:
        from aisc.cli.commands.run import plan_run

        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                plan = plan_run(image="super-claude:latest", workspace=str(ws),
                                name="t", interactive=True, dry_run=True)
            argv = " ".join(plan.docker_argv)
            self.assertIn(f"{root}", argv)
            self.assertIn(":/root/.claude", argv)
            self.assertIn(":/root/.codex", argv)
            self.assertIn(":/root/.cc-switch", argv)
            self.assertIn(":/root/.local/state/cc-switch", argv)
            # The IMAGE is the single source of container scripts — no host
            # entrypoint overlays (a stale host bundle downgraded a fresh
            # image once; see 7f gate findings).
            self.assertNotIn(":/usr/local/bin/entrypoint.sh", argv)
            self.assertNotIn(":/usr/local/bin/cc-switch", argv)
            # Host-side mount targets were created under the data root…
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
            for sub in ("claude", "codex", "cc-switch", "runtime"):
                self.assertTrue((resolved.workspace_dir / sub).is_dir(), sub)
            # …and the workspace itself gained NOTHING (DATA-01).
            self.assertEqual(list(p.name for p in ws.iterdir()), [])


class ConfigLayerWiringTests(unittest.TestCase):
    """Workspace config layer: canonical first, legacy read fallback."""

    def _path(self, ws: Path) -> str:
        from aisc.application.config_service import _ws_path_str

        return _ws_path_str(str(ws))

    def test_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
                resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
                canonical = resolved.workspace_dir / "config.json"
                legacy = ws / ".aisc" / "config.json"

                # Fresh workspace → canonical (reported missing there).
                self.assertEqual(self._path(ws), str(canonical))

                # Legacy only → read fallback to legacy.
                legacy.parent.mkdir()
                legacy.write_text("{}", encoding="utf-8")
                self.assertEqual(self._path(ws), str(legacy))

                # Both → canonical wins.
                canonical.parent.mkdir(parents=True)
                canonical.write_text("{}", encoding="utf-8")
                self.assertEqual(self._path(ws), str(canonical))


if __name__ == "__main__":
    unittest.main()
