"""Characterization tests for ``scripts/_state.sh`` — state file helpers.

Tests init / set / get, primary-priority / legacy-fallback, and dual-write
behaviour.  Runs in an isolated temp directory so the real ``.aisc/`` and
``.deploy/`` are never touched.
"""

from __future__ import annotations

import os
import unittest

from tests.features.helpers import TempProject, repo_root
from tests.harness.test_runner import CliRunner


class StateScriptTest(unittest.TestCase):
    """Isolated subprocess tests sourcing _state.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = CliRunner()

    def setUp(self) -> None:
        # Copy only _state.sh into a temp project skeleton
        self.proj = TempProject(scripts=("_state.sh",))

    def tearDown(self) -> None:
        self.proj.destroy()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _bash(self, code: str, **kw):
        """Run *code* after sourcing _state.sh from the temp scripts dir."""
        full = f'source "{self.proj.scripts_dir}/_state.sh"\n{code}'
        return self.runner.run(
            ["bash", "-c", full],
            cwd=self.proj.tmpdir,
            **kw,
        )

    def _read_file(self, *parts: str) -> str:
        path = self.proj.path(*parts)
        if not os.path.isfile(path):
            return ""
        with open(path) as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # state_init
    # ------------------------------------------------------------------

    def test_state_init_creates_primary(self) -> None:
        r = self._bash("state_init")
        self.assertEqual(r.exit_code, 0)
        content = self._read_file(".aisc", "state.env")
        self.assertIn("# AISC launcher state", content)

    def test_state_init_creates_legacy(self) -> None:
        r = self._bash("state_init")
        self.assertEqual(r.exit_code, 0)
        content = self._read_file(".deploy", "state.env")
        self.assertIn("# AISC launcher state", content)

    def test_state_init_idempotent(self) -> None:
        """Running state_init twice should not error."""
        self._bash("state_init")
        r = self._bash("state_init")
        self.assertEqual(r.exit_code, 0)

    # ------------------------------------------------------------------
    # state_set
    # ------------------------------------------------------------------

    def test_state_set_writes_primary(self) -> None:
        self._bash("state_init; state_set IMAGE my-image:v1")
        primary = self._read_file(".aisc", "state.env")
        self.assertIn("IMAGE=my-image:v1", primary)

    def test_state_set_writes_legacy(self) -> None:
        self._bash("state_init; state_set IMAGE my-image:v1")
        legacy = self._read_file(".deploy", "state.env")
        self.assertIn("IMAGE=my-image:v1", legacy)

    def test_state_set_updates_existing_key(self) -> None:
        self._bash("state_init; state_set IMAGE v1; state_set IMAGE v2")
        primary = self._read_file(".aisc", "state.env")
        # Should have v2, not v1
        self.assertIn("IMAGE=v2", primary)
        self.assertNotIn("IMAGE=v1", primary)

    def test_state_set_preserves_other_keys(self) -> None:
        self._bash(
            "state_init; state_set IMAGE v1; state_set NAME c1; state_set IMAGE v2"
        )
        primary = self._read_file(".aisc", "state.env")
        self.assertIn("IMAGE=v2", primary)
        self.assertIn("NAME=c1", primary)

    # ------------------------------------------------------------------
    # state_get — primary-first, legacy fallback
    # ------------------------------------------------------------------

    def test_state_get_primary_exists(self) -> None:
        self._bash("state_init; state_set IMAGE from_primary")
        r = self._bash("state_get IMAGE")
        self.assertIn("from_primary", r.stdout.strip())

    def test_state_get_fallback_to_legacy(self) -> None:
        """When primary has no value, fall back to legacy file."""
        # Write directly to legacy only
        self._bash("state_init")
        # Manually write a key to legacy file (simulating old state)
        os.makedirs(self.proj.path(".deploy"), exist_ok=True)
        with open(self.proj.path(".deploy", "state.env"), "a") as fh:
            fh.write("OLD_KEY=legacy_value\n")
        r = self._bash("state_get OLD_KEY")
        self.assertIn("legacy_value", r.stdout.strip())

    def test_state_get_primary_overrides_legacy(self) -> None:
        """Primary value wins over legacy when both exist."""
        self._bash("state_init; state_set KEY from_primary")
        # Also write a different value in legacy
        with open(self.proj.path(".deploy", "state.env"), "a") as fh:
            fh.write("KEY=from_legacy\n")
        r = self._bash("state_get KEY")
        self.assertIn("from_primary", r.stdout.strip())
        self.assertNotIn("from_legacy", r.stdout.strip())

    def test_state_get_missing_returns_empty(self) -> None:
        self._bash("state_init")
        r = self._bash("state_get NO_SUCH_KEY")
        self.assertEqual(r.stdout.strip(), "")

    # ------------------------------------------------------------------
    # Dual-write invariant
    # ------------------------------------------------------------------

    def test_dual_write_both_files_receive_set(self) -> None:
        self._bash("state_init; state_set IMAGE dual_test")
        primary_val = ""
        legacy_val = ""
        pf = self.proj.path(".aisc", "state.env")
        lf = self.proj.path(".deploy", "state.env")
        if os.path.isfile(pf):
            with open(pf) as f:
                for line in f:
                    if line.startswith("IMAGE="):
                        primary_val = line.strip()
        if os.path.isfile(lf):
            with open(lf) as f:
                for line in f:
                    if line.startswith("IMAGE="):
                        legacy_val = line.strip()
        self.assertEqual(primary_val, "IMAGE=dual_test")
        self.assertEqual(legacy_val, "IMAGE=dual_test")

    # ------------------------------------------------------------------
    # No pollution of real repo
    # ------------------------------------------------------------------

    def test_no_real_state_pollution(self) -> None:
        """Sanity: the real .aisc/state.env is never touched by this test."""
        real_primary = os.path.join(repo_root(), ".aisc", "state.env")
        real_legacy = os.path.join(repo_root(), ".deploy", "state.env")
        before_primary = ""
        before_legacy = ""
        if os.path.isfile(real_primary):
            with open(real_primary) as fh:
                before_primary = fh.read()
        if os.path.isfile(real_legacy):
            with open(real_legacy) as fh:
                before_legacy = fh.read()

        # Run some state operations in the temp project
        self._bash("state_init; state_set IMAGE test_no_pollute")

        # Verify real files unchanged
        if os.path.isfile(real_primary):
            with open(real_primary) as fh:
                self.assertEqual(before_primary, fh.read(),
                                 "Real .aisc/state.env was modified!")
        if os.path.isfile(real_legacy):
            with open(real_legacy) as fh:
                self.assertEqual(before_legacy, fh.read(),
                                 "Real .deploy/state.env was modified!")


if __name__ == "__main__":
    unittest.main()
