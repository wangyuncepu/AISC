"""Stage 7 (7c, DATA-02/D7-03): legacy-layout scan, allowlist and manifest.

Synthetic legacy workspaces follow the measured fresh-init inventory
(stage-7/02-domain-contract.md). Execution (copy/rollback/quarantine) is 7d;
these tests pin the read-only classification and the manifest contract.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aisc.application.data_root import DataRootResolver
from aisc.application.legacy_scan import scan_legacy_workspace
from aisc.domain.data_migration import (
    ENTRY_CONFLICT,
    ENTRY_OWNED,
    ENTRY_TRANSIENT,
    ENTRY_UNKNOWN,
    MIGRATION_PROTOCOL,
    NAMESPACE_AISC,
    NAMESPACE_FOREIGN,
    STATE_PREPARED,
    MigrationEntry,
    MigrationManifest,
    classify,
)


def _build_legacy_workspace(ws: Path) -> None:
    """The measured fresh-init shape (Downloads\\test inventory)."""
    (ws / ".aisc").mkdir()
    (ws / ".aisc" / "containers.json").write_text('{"default": null}', encoding="utf-8")
    (ws / ".aisc" / "state.env").write_text("DO_RUN=0\n", encoding="utf-8")
    (ws / ".aisc" / "config.json").write_text('{"schema_version": 1}', encoding="utf-8")
    (ws / ".aisc" / ".containers.lock").write_text("", encoding="utf-8")
    lock_dir = ws / ".aisc" / "workspace-locks"
    lock_dir.mkdir()
    (lock_dir / "abc.lock").write_text("", encoding="utf-8")

    claude = ws / ".claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("guide", encoding="utf-8")
    (claude / "config.json").write_text("{}", encoding="utf-8")
    (claude / "settings.json").write_text("{}", encoding="utf-8")
    (claude / "settings.local.json").write_text("{}", encoding="utf-8")
    (claude / "skills" / "caveman").mkdir(parents=True)
    (claude / "skills" / "caveman" / "SKILL.md").write_text("skill", encoding="utf-8")
    (claude / "projects" / "p1").mkdir(parents=True)
    (claude / "projects" / "p1" / "x.json").write_text("{}", encoding="utf-8")

    codex = ws / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text("[proj]", encoding="utf-8")
    (codex / "AGENTS.md").write_text("agents", encoding="utf-8")
    (codex / ".factory-version").write_text("2.1.4", encoding="utf-8")
    (codex / "skills" / "doc").mkdir(parents=True)
    (codex / "skills" / "doc" / "SKILL.md").write_text("skill", encoding="utf-8")

    cc = ws / ".cc-switch"
    cc.mkdir()
    for name in ("cc-switch.db", "cc-switch.db-shm", "cc-switch.db-wal",
                 "settings.json", "session-scan-cache.db",
                 ".aisc-bundled-skills.sha256",
                 ".aisc-preset-providers-claude.sha256",
                 ".aisc-preset-providers-codex.sha256",
                 "cc-switch.db.init.lock", "state-mutation.lock",
                 ".aisc-bundled-skills.lock"):
        (cc / name).write_text(f"content of {name}", encoding="utf-8")
    (cc / "skills" / "x").mkdir(parents=True)
    (cc / "skills" / "x" / "SKILL.md").write_text("skill", encoding="utf-8")

    daemon = ws / ".local" / "state" / "cc-switch"
    daemon.mkdir(parents=True)
    (daemon / "cc-switchd.log").write_text("log", encoding="utf-8")
    (daemon / "runtime").mkdir()
    (daemon / "runtime" / "daemon.pid").write_text("123", encoding="utf-8")


class PureClassificationTests(unittest.TestCase):
    def test_allowlist_mappings(self) -> None:
        cases = [
            (".aisc", "containers.json", ENTRY_OWNED, "runtime/containers.json"),
            (".aisc", "state.env", ENTRY_OWNED, "runtime/state.env"),
            (".aisc", "config.json", ENTRY_OWNED, "config.json"),
            (".aisc", ".containers.lock", ENTRY_TRANSIENT, ""),
            (".aisc", "workspace-locks/a.lock", ENTRY_TRANSIENT, ""),
            (".aisc", "surprise.bin", ENTRY_UNKNOWN, ""),
            (".claude", "settings.json", ENTRY_OWNED, "claude/settings.json"),
            (".claude", "skills/a/B.md", ENTRY_OWNED, "claude/skills/a/B.md"),
            (".claude", "sessions/s1.json", ENTRY_OWNED, "claude/sessions/s1.json"),
            (".claude", "my-notes.txt", ENTRY_UNKNOWN, ""),
            (".codex", ".factory-version", ENTRY_OWNED, "codex/.factory-version"),
            (".cc-switch", "cc-switch.db", ENTRY_OWNED, "cc-switch/cc-switch.db"),
            (".cc-switch", "cc-switch.db-wal", ENTRY_OWNED, "cc-switch/cc-switch.db-wal"),
            (".cc-switch", "state-mutation.lock", ENTRY_TRANSIENT, ""),
            (".cc-switch", "nested/settings.json", ENTRY_UNKNOWN, ""),
            (".local", "state/cc-switch/cc-switchd.log", ENTRY_TRANSIENT, ""),
            (".local", "state/cc-switch/runtime/daemon.pid", ENTRY_TRANSIENT, ""),
            (".local", "state/other/x", ENTRY_UNKNOWN, ""),
        ]
        for ns, rel, expected_cls, expected_target in cases:
            with self.subTest(f"{ns}/{rel}"):
                self.assertEqual(classify(ns, rel), (expected_cls, expected_target))


class ScanTests(unittest.TestCase):
    def _scan(self, ws: Path, root: Path):
        resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
        return scan_legacy_workspace(ws, resolved)

    def test_fresh_workspace_has_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            scan = self._scan(ws, root)
            self.assertEqual(scan.findings, [])
            self.assertEqual(scan.entries, [])
            self.assertEqual(scan.counts(), {"owned": 0, "transient": 0, "unknown": 0, "conflict": 0})
            self.assertFalse(scan.summary()["has_unknowns"])

    def test_full_legacy_shape(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _build_legacy_workspace(ws)
            scan = self._scan(ws, root)

            kinds = {f.namespace: f.kind for f in scan.findings}
            self.assertEqual(kinds, {
                ".aisc": NAMESPACE_AISC, ".claude": NAMESPACE_AISC,
                ".codex": NAMESPACE_AISC, ".cc-switch": NAMESPACE_AISC,
                ".local": NAMESPACE_AISC,
            })

            counts = scan.counts()
            # owned: 3 (.aisc) + 6 (.claude) + 4 (.codex) + 9 (.cc-switch)
            self.assertEqual(counts["owned"], 22)
            # transient: 2 (.aisc locks) + 3 (.cc-switch locks) + 2 (daemon)
            self.assertEqual(counts["transient"], 7)
            self.assertEqual(counts["unknown"], 0)
            self.assertEqual(counts["conflict"], 0)

            by_rel = {e.relative: e for e in scan.entries}
            self.assertEqual(by_rel[".aisc/containers.json"].target, "runtime/containers.json")
            self.assertEqual(by_rel[".aisc/config.json"].target, "config.json")
            self.assertEqual(by_rel[".cc-switch/settings.json"].target, "cc-switch/settings.json")
            self.assertEqual(by_rel[".claude/skills/caveman/SKILL.md"].target,
                             "claude/skills/caveman/SKILL.md")
            self.assertEqual(by_rel[".cc-switch/cc-switch.db-wal"].target,
                             "cc-switch/cc-switch.db-wal")
            self.assertEqual(by_rel[".cc-switch/state-mutation.lock"].target, "")
            self.assertEqual(by_rel[".local/state/cc-switch/runtime/daemon.pid"].target, "")
            for rel, e in by_rel.items():
                if e.classification == ENTRY_OWNED:
                    self.assertTrue(e.sha256, f"owned entry must be hashed: {rel}")
                    self.assertEqual(len(e.sha256), 64)
            self.assertGreater(scan.owned_bytes(), 0)
            self.assertFalse(scan.summary()["has_unknowns"])

    def test_unknown_user_file_inside_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _build_legacy_workspace(ws)
            (ws / ".claude" / "my-notes.txt").write_text("user data", encoding="utf-8")
            scan = self._scan(ws, root)
            self.assertTrue(scan.summary()["has_unknowns"])
            entry = next(e for e in scan.entries if e.relative == ".claude/my-notes.txt")
            self.assertEqual(entry.classification, ENTRY_UNKNOWN)
            self.assertEqual(entry.target, "")

    def test_foreign_namespace_without_init_markers(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            # A user's own .claude with NO AISC markers anywhere.
            (ws / ".claude").mkdir()
            (ws / ".claude" / "settings.json").write_text("user's own", encoding="utf-8")
            scan = self._scan(ws, root)
            self.assertEqual(scan.findings[0].kind, NAMESPACE_FOREIGN)
            self.assertEqual(scan.entries, [])  # reported, never migrated
            self.assertTrue(scan.summary()["has_foreign"])

    def test_conflict_and_identical_target(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _build_legacy_workspace(ws)
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
            # Identical bytes already migrated → still owned (7d skips).
            same = resolved.workspace_dir / "runtime" / "containers.json"
            same.parent.mkdir(parents=True)
            same.write_text('{"default": null}', encoding="utf-8")
            # Different bytes at target → conflict, fail closed.
            diff = resolved.workspace_dir / "cc-switch" / "settings.json"
            diff.parent.mkdir(parents=True, exist_ok=True)
            diff.write_text("different", encoding="utf-8")

            scan = scan_legacy_workspace(ws, resolved)
            by_rel = {e.relative: e for e in scan.entries}
            self.assertEqual(by_rel[".aisc/containers.json"].classification, ENTRY_OWNED)
            self.assertEqual(by_rel[".cc-switch/settings.json"].classification, ENTRY_CONFLICT)
            self.assertTrue(scan.summary()["has_conflicts"])

    def test_scan_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _build_legacy_workspace(ws)

            def snapshot(base: Path):
                return sorted(
                    str(p.relative_to(base)) for p in base.rglob("*")
                )

            before_ws, before_root = snapshot(ws), snapshot(root)
            resolved = DataRootResolver(env={"AISC_DATA_ROOT": str(root)}).resolve(ws)
            scan_legacy_workspace(ws, resolved)
            self.assertEqual(snapshot(ws), before_ws)
            self.assertEqual(snapshot(root), before_root)
            self.assertFalse(resolved.workspace_dir.exists())


class ManifestContractTests(unittest.TestCase):
    def _manifest(self) -> MigrationManifest:
        return MigrationManifest(
            workspace_hash="sha256-v1:" + "a" * 64,
            source="C:\\ws", target="C:\\root\\workspaces\\sha256-v1-aaa",
            entries=[MigrationEntry(relative=".cc-switch/settings.json",
                                    classification=ENTRY_OWNED, sha256="b" * 64,
                                    size=9, target="cc-switch/settings.json")],
            state=STATE_PREPARED,
        )

    def test_round_trip(self) -> None:
        m = self._manifest()
        restored = MigrationManifest.from_dict(json.loads(json.dumps(m.to_dict())))
        self.assertEqual(restored, m)

    def test_wrong_schema_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            MigrationManifest.from_dict({"schema": "aisc.data-migration/v2"})
        with self.assertRaises(ValueError):
            MigrationManifest.from_dict({"schema": MIGRATION_PROTOCOL, "schema_version": 2})

    def test_bad_state_and_classification_fail_closed(self) -> None:
        raw = self._manifest().to_dict()
        raw["state"] = "half-done"
        with self.assertRaises(ValueError):
            MigrationManifest.from_dict(raw)
        raw2 = self._manifest().to_dict()
        raw2["entries"][0]["classification"] = "maybe"
        with self.assertRaises(ValueError):
            MigrationManifest.from_dict(raw2)

    def test_manifest_defaults_to_prepared_state(self) -> None:
        m = MigrationManifest()
        self.assertEqual(m.schema, MIGRATION_PROTOCOL)
        self.assertEqual(m.state, STATE_PREPARED)


if __name__ == "__main__":
    unittest.main()
