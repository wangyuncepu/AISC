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


if __name__ == "__main__":
    unittest.main()
