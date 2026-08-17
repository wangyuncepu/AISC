"""Stage 7 (7d, DATA-02/03): migration executor — prepare/copy/commit/
resume/rollback/quarantine semantics.

Invariants under test: sources never modified by copy-phase; the manifest
is the rollback boundary; conflicts/changed sources/unknowns fail closed
with stable codes; cancel leaves a resumable prepared manifest.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aisc.adapters.data_root_store import DataRootStore
from aisc.application.data_migration import MigrationExecutor
from aisc.application.data_root import DataRootResolver
from aisc.domain.data_migration import (
    ERR_CONFLICT,
    ERR_INSUFFICIENT_SPACE,
    ERR_SOURCE_CHANGED,
    ERR_UNKNOWN_PENDING,
    STATE_COMMITTED,
    STATE_PREPARED,
    STATE_ROLLED_BACK,
    STATUS_COPIED,
    MigrationManifest,
)
from aisc.domain.models import CliError


def _legacy_ws(ws: Path) -> None:
    (ws / ".aisc").mkdir()
    (ws / ".aisc" / "containers.json").write_text('{"default": null}', encoding="utf-8")
    (ws / ".aisc" / "state.env").write_text("DO_RUN=0\n", encoding="utf-8")
    (ws / ".aisc" / ".containers.lock").write_text("", encoding="utf-8")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (ws / ".claude" / "skills").mkdir()
    (ws / ".claude" / "skills" / "a.md").write_text("skill-a", encoding="utf-8")
    (ws / ".codex").mkdir()
    (ws / ".codex" / ".factory-version").write_text("2.1.4", encoding="utf-8")


def _executor(ws: Path, root: Path) -> MigrationExecutor:
    resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
    return MigrationExecutor(ws, resolved, store=DataRootStore(resolved))


class MigrateTests(unittest.TestCase):
    def test_commit_copies_sources_stay_markers_written(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            result = ex.migrate()

            self.assertEqual(result.outcome, "committed")
            self.assertEqual(result.copied, 5)  # containers/state.env/…/factory-version
            # Targets exist with identical bytes.
            resolved = ex.resolved
            self.assertEqual(
                (resolved.workspace_dir / "runtime" / "containers.json").read_text("utf-8"),
                '{"default": null}',
            )
            self.assertTrue((resolved.workspace_dir / "claude" / "skills" / "a.md").is_file())
            # Sources are NEVER touched by the copy phase.
            self.assertTrue((ws / ".aisc" / "containers.json").is_file())
            self.assertTrue((ws / ".claude" / "settings.json").is_file())
            # Transients stay in place, unmigrated.
            self.assertTrue((ws / ".aisc" / ".containers.lock").is_file())
            # Fully-migrated namespaces carry the redirect marker.
            for ns in (".aisc", ".claude", ".codex"):
                marker = ws / ns / ".aisc-migrated"
                self.assertTrue(marker.is_file(), ns)
                payload = json.loads(marker.read_text("utf-8"))
                self.assertEqual(payload["schema"], "aisc.data-migration/v1")
            # Manifest committed, staging cleaned.
            manifest = MigrationManifest.from_dict(
                json.loads(ex.manifest_path().read_text("utf-8"))
            )
            self.assertEqual(manifest.state, STATE_COMMITTED)
            self.assertEqual(sorted(manifest.markers), [".aisc", ".claude", ".codex"])
            self.assertFalse(ex.staging_dir().exists())

    def test_rerun_after_commit_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            ex.migrate()
            second = ex.migrate()
            self.assertEqual(second.outcome, "committed")
            self.assertEqual(second.copied, 0)
            self.assertEqual(second.skipped, 5)

    def test_cancel_leaves_resumable_prepared_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            calls = {"n": 0}

            def stop_after_two() -> bool:
                calls["n"] += 1
                return calls["n"] <= 2  # continue for first two entries only

            result = ex.migrate(should_continue=stop_after_two)
            self.assertEqual(result.outcome, "cancelled")
            manifest = MigrationManifest.from_dict(
                json.loads(ex.manifest_path().read_text("utf-8"))
            )
            self.assertEqual(manifest.state, STATE_PREPARED)

            resumed = ex.migrate()
            self.assertEqual(resumed.outcome, "committed")
            self.assertEqual(resumed.copied + resumed.skipped, 5)
            # All targets in place after resume.
            self.assertTrue(
                (ex.resolved.workspace_dir / "codex" / ".factory-version").is_file()
            )

    def test_source_changed_mid_migration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)

            def mutate_then_continue(done: int, total: int, rel: str) -> None:
                # While staging the FIRST entry, rewrite a LATER entry's
                # source — its scan hash is now stale.
                if done == 1:
                    (ws / ".claude" / "settings.json").write_text("MUTATED", encoding="utf-8")

            with self.assertRaises(CliError) as ctx:
                ex.migrate(progress=mutate_then_continue)
            self.assertEqual(ctx.exception.error_code, ERR_SOURCE_CHANGED)

    def test_conflict_fails_closed_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            # Different bytes already at a target.
            clash = ex.resolved.workspace_dir / "claude" / "settings.json"
            clash.parent.mkdir(parents=True)
            clash.write_text("existing user data", encoding="utf-8")
            with self.assertRaises(CliError) as ctx:
                ex.migrate()
            self.assertEqual(ctx.exception.error_code, ERR_CONFLICT)
            self.assertEqual(ctx.exception.exit_code, 1)

    def test_unknown_requires_consent_then_quarantines(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            mystery = ws / ".claude" / "my-notes.txt"
            mystery.write_text("user data", encoding="utf-8")
            ex = _executor(ws, root)

            with self.assertRaises(CliError) as ctx:
                ex.migrate()
            self.assertEqual(ctx.exception.error_code, ERR_UNKNOWN_PENDING)

            result = ex.migrate(quarantine_unknown=True)
            self.assertEqual(result.quarantined, 1)
            # Moved to quarantine (copy-verified, source removed).
            qfile = ex.quarantine_dir() / ".claude" / "my-notes.txt"
            self.assertEqual(qfile.read_text("utf-8"), "user data")
            self.assertFalse(mystery.exists())

    def test_insufficient_space_fails_closed(self) -> None:
        import collections

        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            usage = collections.namedtuple("usage", "total used free")(1, 1, 0)
            with mock.patch("aisc.application.data_migration.shutil.disk_usage",
                            return_value=usage):
                with self.assertRaises(CliError) as ctx:
                    ex.migrate()
            self.assertEqual(ctx.exception.error_code, ERR_INSUFFICIENT_SPACE)


class RollbackTests(unittest.TestCase):
    def test_rollback_removes_only_manifest_targets(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            # A pre-existing user file at the data root must survive rollback.
            keep_me = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
            unrelated = keep_me.workspace_dir / "claude" / "user-own.json"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("not part of migration", encoding="utf-8")

            ex = _executor(ws, root)
            ex.migrate()
            result = ex.rollback()

            self.assertEqual(result.outcome, "rolled_back")
            self.assertEqual(result.removed, 5)
            self.assertEqual(result.kept, 0)
            # Manifest-listed targets gone; unrelated file kept; sources intact.
            self.assertFalse((keep_me.workspace_dir / "runtime" / "containers.json").exists())
            self.assertTrue(unrelated.is_file())
            self.assertTrue((ws / ".aisc" / "containers.json").is_file())
            manifest = MigrationManifest.from_dict(
                json.loads(ex.manifest_path().read_text("utf-8"))
            )
            self.assertEqual(manifest.state, STATE_ROLLED_BACK)
            # Markers removed.
            self.assertFalse((ws / ".claude" / ".aisc-migrated").exists())

    def test_rollback_keeps_user_modified_targets(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            ex.migrate()
            target = ex.resolved.workspace_dir / "claude" / "settings.json"
            target.write_text("user edited after migration", encoding="utf-8")
            result = ex.rollback()
            self.assertEqual(result.kept, 1)
            self.assertEqual(result.removed, 4)
            self.assertEqual(target.read_text("utf-8"), "user edited after migration")

    def test_rollback_restores_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            mystery = ws / ".claude" / "my-notes.txt"
            mystery.write_text("user data", encoding="utf-8")
            ex = _executor(ws, root)
            ex.migrate(quarantine_unknown=True)
            self.assertFalse(mystery.exists())
            result = ex.rollback()
            self.assertEqual(result.restored, 1)
            self.assertEqual(mystery.read_text("utf-8"), "user data")

    def test_rollback_without_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            ex = _executor(ws, root)
            with self.assertRaises(CliError):
                ex.rollback()


class DoctorDryRunTests(unittest.TestCase):
    def test_dry_run_reports_plan_and_touches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)

            def snapshot(base: Path):
                return sorted(str(p.relative_to(base)) for p in base.rglob("*"))

            before_ws, before_root = snapshot(ws), snapshot(root)
            ex = _executor(ws, root)
            plan = ex.dry_run()
            self.assertEqual(plan["plan"]["copy_count"], 5)
            self.assertEqual(plan["conflicts"], [])
            self.assertEqual(snapshot(ws), before_ws)
            self.assertEqual(snapshot(root), before_root)

    def test_doctor_reports_root_and_pending_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            ex = _executor(ws, root)
            report = ex.doctor()
            self.assertEqual(report["data_root"]["origin"], "env")
            self.assertIsNone(report["pending_manifest"])
            self.assertEqual(report["legacy"]["counts"]["owned"], 5)
            ex.migrate()
            report2 = ex.doctor()
            self.assertEqual(report2["pending_manifest"]["state"], STATE_COMMITTED)


if __name__ == "__main__":
    unittest.main()
