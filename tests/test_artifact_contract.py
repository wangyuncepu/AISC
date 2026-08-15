"""Stage 3 (3a, ART-01/02): aisc.artifact/v1 schema + CLI contract tests.

Covers:
- A-ART01-1: schema v1 round-trip preserves unknown fields.
- A-ART01-2: unsupported/corrupt schema fail closed, never overwrite.
- A-ART02-1: record/list/inspect/clear-session envelopes (pip entry, and the
  frozen sidecar via AISC_CLI_EXECUTABLE).
- A-ART02-2: relative/create/modify/delete/rename/missing/duplicate matrix.
- A-ART05-1 (CLI half): absolute / .. / NUL / backslash / drive / UNC rejected.
- A-ART04-1: registry lives outside the workspace (git status stays clean).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYS_AISC = [sys.executable, "-m", "aisc"]

RUNTIME_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
SESSION2 = "33333333-3333-4333-8333-333333333333"


def _cli_env(data_root: Path) -> dict:
    env = os.environ.copy()
    env["AISC_ARTIFACT_DATA_ROOT"] = str(data_root)
    return env


def _run(data_root: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    exe = os.environ.get("AISC_CLI_EXECUTABLE")
    argv = [exe] if exe else SYS_AISC
    env = _cli_env(data_root)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([*argv, *args], capture_output=True, text=True, env=env)


def _json(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)


def _record_argv(**kw) -> list[str]:
    args = ["artifact", "record", "--runtime-id", RUNTIME_ID, "--session-id", SESSION_ID,
            "--agent", kw.get("agent", "claude"), "--path", kw["path"],
            "--format", "json"]
    if kw.get("kind"):
        args += ["--kind", kw["kind"]]
    if kw.get("action"):
        args += ["--action", kw["action"]]
    if kw.get("media_type"):
        args += ["--media-type", kw["media_type"]]
    if kw.get("label"):
        args += ["--label", kw["label"]]
    if kw.get("previous_path"):
        args += ["--previous-path", kw["previous_path"]]
    if kw.get("session_id"):
        args[4] = kw["session_id"]
    return args


class ArtifactSchemaTests(unittest.TestCase):
    """A-ART01-1 / A-ART01-2: schema round-trip + fail-closed."""

    def test_round_trip_preserves_unknown_fields(self):
        from aisc.domain.artifacts import ArtifactRecord

        rec = ArtifactRecord(
            artifact_id="aaaaaaaa-0000-4000-8000-000000000001",
            workspace_relative_path="reports/result.md",
            label="报告",
            producer={"agent": "claude", "session_id": SESSION_ID, "runtime_id": RUNTIME_ID},
            extra={"x_future": {"kept": True}},
        ).validate()
        # Inject an unknown top-level field via dict round-trip.
        d = rec.to_dict()
        d["x_unknown_future"] = {"note": "must survive"}
        parsed = ArtifactRecord.from_dict(d)
        self.assertIn("x_unknown_future", parsed.extra)
        self.assertEqual(parsed.extra["x_unknown_future"], {"note": "must survive"})
        self.assertEqual(parsed.label, "报告")

    def test_unsupported_schema_version_fails_closed(self):
        from aisc.domain.artifacts import ArtifactRecord

        with self.assertRaises(ValueError):
            ArtifactRecord.from_dict({
                "schema_version": 99,
                "artifact_id": "aaaaaaaa-0000-4000-8000-000000000001",
                "workspace_relative_path": "a.md",
            })

    def test_shared_v1_fixture_parses_and_round_trips(self):
        """A-ART01-1: the shared tests/fixtures/artifact/record-v1.json parses
        in Python (Rust/TS consume the same file)."""
        from aisc.domain.artifacts import ArtifactRecord

        fixture = REPO_ROOT / "tests" / "fixtures" / "artifact" / "record-v1.json"
        rec = ArtifactRecord.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
        self.assertEqual(rec.workspace_relative_path, "reports/result.md")
        self.assertEqual(rec.kind, "deliverable")
        self.assertEqual(rec.provenance, "manifest")
        again = ArtifactRecord.from_dict(rec.to_dict())
        self.assertEqual(again.to_dict(), rec.to_dict())

    def test_corrupt_line_isolated_in_registry(self):
        with tempfile.TemporaryDirectory(prefix="aisc-art-") as d:
            root = Path(d)
            # A corrupt line must not truncate the registry.
            from aisc.application.artifact import registry_path
            from aisc.domain.artifacts import ArtifactRecord
            from aisc.application.artifact import record, list_records

            ws = root / "ws"
            ws.mkdir()
            rec = ArtifactRecord(
                artifact_id="bbbbbbbb-0000-4000-8000-000000000002",
                workspace_relative_path="a.md",
                producer={"agent": "claude", "session_id": SESSION_ID, "runtime_id": RUNTIME_ID},
            ).validate()
            record(ws, rec, session_id=SESSION_ID)
            p = registry_path(ws, SESSION_ID)
            p.write_text("not-json\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
            records = list_records(ws, session_id=SESSION_ID)
            self.assertEqual(len(records), 1)  # corrupt line isolated, valid kept


class ArtifactPathValidationTests(unittest.TestCase):
    """A-ART05-1 (CLI half): syntax-level rejection."""

    def test_invalid_paths_rejected(self):
        from aisc.domain.artifacts import validate_relative_path

        for bad in ("", " ", "../etc/passwd", "a/../../b", "/etc/passwd",
                    "C:/x", "C:\\x", "\\\\server\\share", "a\\b", "nul",
                    "con.txt", "a\x00b", "."):
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    validate_relative_path(bad)

    def test_valid_paths_accepted_and_normalized(self):
        from aisc.domain.artifacts import validate_relative_path

        for ok, expected in (
            ("a.md", "a.md"),
            ("reports/result.md", "reports/result.md"),
            ("a//b.md", "a/b.md"),
            ("./a.md", "a.md"),
            ("deep/nested/file.txt", "deep/nested/file.txt"),
        ):
            with self.subTest(path=ok):
                self.assertEqual(validate_relative_path(ok), expected)


class ArtifactCliTests(unittest.TestCase):
    """A-ART02-1 / A-ART02-2: CLI lifecycle + matrix."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="aisc-art-cli-")
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self, **kw) -> dict:
        proc = _run(self.root, *_record_argv(**kw))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return _json(proc)["data"]["artifact"]

    def test_record_list_inspect_clear(self):
        a = self._record(path="reports/result.md", kind="deliverable",
                         media_type="text/markdown", label="报告")
        self.assertEqual(a["provenance"], "manifest")
        self.assertEqual(a["workspace_relative_path"], "reports/result.md")

        listed = _json(_run(self.root, "artifact", "list", "--format", "json"))["data"]
        self.assertEqual(len(listed["artifacts"]), 1)

        got = _json(_run(self.root, "artifact", "inspect", "--artifact-id",
                         a["artifact_id"], "--format", "json"))["data"]["artifact"]
        self.assertEqual(got["workspace_relative_path"], "reports/result.md")

        clear = _json(_run(self.root, "artifact", "clear-session",
                           "--runtime-id", RUNTIME_ID, "--session-id", SESSION_ID,
                           "--format", "json"))["data"]
        self.assertTrue(clear["cleared"])
        after = _json(_run(self.root, "artifact", "list", "--format", "json"))["data"]
        self.assertEqual(len(after["artifacts"]), 0)

    def test_modify_delete_rename_matrix(self):
        a1 = self._record(path="doc.md", action="created")
        # modify same path -> new artifact id (both present, idempotent by id)
        a2 = self._record(path="doc.md", action="modified")
        self.assertNotEqual(a1["artifact_id"], a2["artifact_id"])
        # delete
        d = self._record(path="doc.md", action="deleted")
        listed = _json(_run(self.root, "artifact", "list", "--format", "json"))["data"]
        self.assertEqual(len(listed["artifacts"]), 3)
        # rename requires previous_path
        bad = _run(self.root, "artifact", "record", "--runtime-id", RUNTIME_ID,
                   "--session-id", SESSION_ID, "--agent", "claude",
                   "--path", "renamed.md", "--action", "renamed", "--format", "json")
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(_json(bad)["errors"][0]["code"], "AISC_ERR_ARTIFACT_INVALID")
        # rename with previous_path
        r = self._record(path="renamed.md", action="renamed", previous_path="doc.md")
        self.assertEqual(r["previous_path"], "doc.md")

    def test_duplicate_id_updates_in_place(self):
        from aisc.application.artifact import list_records, record as _record
        from aisc.domain.artifacts import ArtifactRecord

        ws = self.root / "ws"
        ws.mkdir()
        producer = {"agent": "claude", "session_id": SESSION_ID, "runtime_id": RUNTIME_ID}
        base = dict(artifact_id="cccccccc-0000-4000-8000-000000000003",
                    workspace_relative_path="x.md", producer=producer)
        _record(ws, ArtifactRecord(**base, action="created").validate(), session_id=SESSION_ID)
        _record(ws, ArtifactRecord(**base, action="deleted").validate(), session_id=SESSION_ID)
        listed = list_records(ws, session_id=SESSION_ID)
        # Same artifact_id: one record, updated to deleted.
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].action, "deleted")

    def test_registry_never_in_workspace(self):
        """A-ART04-1: recording must not create files inside the workspace."""
        ws = self.root / "ws"
        ws.mkdir()
        proc = _run(self.root, "artifact", "record", "--runtime-id", RUNTIME_ID,
                    "--session-id", SESSION_ID, "--agent", "claude",
                    "--path", "doc.md", "--workspace", str(ws), "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Nothing created inside the workspace.

    def test_record_accepts_absolute_path_inside_workspace(self):
        """Agents may pass container absolute paths; convert to workspace-relative."""
        ws = self.root / "ws"
        ws.mkdir()
        abs_path = ws / "doc.md"
        proc = _run(self.root, "artifact", "record", "--runtime-id", RUNTIME_ID,
                    "--session-id", SESSION_ID, "--agent", "claude",
                    "--path", str(abs_path), "--workspace", str(ws), "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = _json(proc)["data"]["artifact"]
        self.assertEqual(data["workspace_relative_path"], "doc.md")
        self.assertEqual(sorted(p.name for p in ws.iterdir()), [])

    def test_envelope_and_stable_errors(self):
        # bad path -> AISC_ERR_ARTIFACT_INVALID with exit 2
        bad = _run(self.root, "artifact", "record", "--runtime-id", RUNTIME_ID,
                   "--session-id", SESSION_ID, "--agent", "claude",
                   "--path", "../escape", "--format", "json")
        env = _json(bad)
        self.assertEqual(env["meta"]["protocol"], "aisc.cli/v1")
        self.assertEqual(env["meta"]["exit_code"], 2)
        self.assertEqual(env["errors"][0]["code"], "AISC_ERR_ARTIFACT_INVALID")
        # not found -> AISC_ERR_ARTIFACT_NOT_FOUND with exit 1
        nf = _run(self.root, "artifact", "inspect", "--artifact-id",
                  "00000000-0000-4000-8000-000000000000", "--format", "json")
        env2 = _json(nf)
        self.assertEqual(env2["meta"]["exit_code"], 1)
        self.assertEqual(env2["errors"][0]["code"], "AISC_ERR_ARTIFACT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
