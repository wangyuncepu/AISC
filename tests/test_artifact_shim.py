"""2.1.9 T3b (R1): container-side aisc shim — registry compatibility.

The shim (container/lib/aisc_shim.py) is what agents invoke as `aisc`
inside the container. Its entire reason to exist is that its output is the
SAME registry the host CLI/Workbench reads — these tests pin that contract:

- JSONL lands at <root>/<workspace-hash[:16]>/<session-id>.jsonl
- every line parses and validates as a host ArtifactRecord
- the host's list_records() (via AISC_ARTIFACT_DATA_ROOT) reads shim output
- deterministic artifact_id: re-recording replaces, not duplicates
- /root/app prefix normalization + error paths
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from aisc.domain.artifacts import ArtifactRecord

ROOT = Path(__file__).resolve().parent.parent
SHIM = ROOT / "container" / "lib" / "aisc_shim.py"

RT = "3212ee97-1af9-4412-a836-47311b63e139"
SID = "8848aaa1-1234-4abc-8def-123456789abc"


class ShimTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="aisc-shim-")
        self.base = Path(self._tmp.name)
        self.ws = self.base / "ws"
        self.ws.mkdir()
        # Same sha256(canonical path) the host computes; the FULL hex is what
        # docker injects as AISC_WORKSPACE_HASH — the shim truncates to [:16].
        canon = str(self.ws.resolve())
        self.ws_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        self.artifacts = self.base / "artifacts"

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, **extra):
        env = {
            "AISC_RUNTIME_ID": RT,
            "AISC_TERMINAL_SESSION_ID": SID,
            "AISC_AGENT": "codex",
            "AISC_WORKSPACE_HASH": self.ws_hash,
            "AISC_ARTIFACT_ROOT": str(self.artifacts),
            "PATH": os.environ.get("PATH", ""),
        }
        env.update(extra)
        # Strip host-side overrides that must not leak into the shim.
        for k in ("AISC_DATA_ROOT", "AISC_ARTIFACT_DATA_ROOT"):
            env.pop(k, None)
        return env

    def _run(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(SHIM), "artifact", "record", *args],
            capture_output=True, text=True,
            env=env if env is not None else self._env(),
        )

    def _registry_file(self) -> Path:
        return self.artifacts / self.ws_hash[:16] / f"{SID}.jsonl"

    def test_record_lands_in_host_registry_layout_and_validates(self):
        r = self._run("--path", "docs/report.md", "--label", "报告")
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self._registry_file()
        self.assertTrue(f.exists(), f)
        rec = ArtifactRecord.from_dict(json.loads(f.read_text(encoding="utf-8")))
        rec.validate()
        self.assertEqual(rec.workspace_relative_path, "docs/report.md")
        self.assertEqual(rec.producer["agent"], "codex")
        self.assertEqual(rec.producer["session_id"], SID)
        self.assertEqual(rec.producer["runtime_id"], RT)
        self.assertEqual(rec.provenance, "manifest")
        self.assertEqual(rec.state, "present")
        self.assertEqual(rec.label, "报告")

    def test_host_list_records_reads_shim_output(self):
        from aisc.application.artifact import list_records

        self._run("--path", "docs/report.md")
        # Host-side read via the explicit override (same layout the shared
        # data root would produce).
        with unittest.mock.patch.dict(
            os.environ, {"AISC_ARTIFACT_DATA_ROOT": str(self.artifacts)}
        ):
            records = list_records(self.ws)
        self.assertEqual([r.workspace_relative_path for r in records],
                         ["docs/report.md"])
        self.assertEqual(records[0].producer["agent"], "codex")

    def test_rerecord_replaces_not_duplicates(self):
        self._run("--path", "out.md", "--label", "v1")
        r2 = self._run("--path", "out.md", "--label", "v2", "--action", "modified")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        lines = [l for l in self._registry_file().read_text(encoding="utf-8").splitlines() if l]
        # Same (path, action) would be one entry; created + modified are two
        # DIFFERENT facts — but re-recording the SAME fact replaces:
        self._run("--path", "out.md", "--label", "v2b", "--action", "modified")
        lines2 = [l for l in self._registry_file().read_text(encoding="utf-8").splitlines() if l]
        self.assertEqual(len(lines2), len(lines))
        labels = [json.loads(l)["label"] for l in lines2]
        self.assertIn("v2b", labels)
        self.assertNotIn("v2", labels)

    def test_container_mount_prefix_stripped(self):
        r = self._run("--path", "/root/app/pkg1/mod.py", "--kind", "source_change")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = ArtifactRecord.from_dict(json.loads(self._registry_file().read_text(encoding="utf-8")))
        self.assertEqual(rec.workspace_relative_path, "pkg1/mod.py")

    def test_absolute_outside_workspace_rejected(self):
        r = self._run("--path", "/etc/passwd")
        self.assertEqual(r.returncode, 2)
        self.assertIn("workspace-relative", r.stderr)

    def test_missing_env_rejected_with_names(self):
        env = self._env()
        del env["AISC_TERMINAL_SESSION_ID"]
        r = self._run("--path", "x.md", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("AISC_TERMINAL_SESSION_ID", r.stderr)

    def test_agent_flag_overrides_env(self):
        r = self._run("--path", "a.md", "--agent", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = ArtifactRecord.from_dict(json.loads(self._registry_file().read_text(encoding="utf-8")))
        self.assertEqual(rec.producer["agent"], "claude")

    def test_renamed_requires_previous_path(self):
        r = self._run("--path", "new.md", "--action", "renamed")
        self.assertEqual(r.returncode, 2)
        self.assertIn("previous-path", r.stderr)


import unittest.mock  # noqa: E402  (used inside test_host_list_records_reads_shim_output)

if __name__ == "__main__":
    unittest.main()
