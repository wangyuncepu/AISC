"""Stage 7 (7d): ``aisc data-root`` CLI contract — envelope, exit codes.

Subprocess-based like test_artifact_contract.py (AISC_* env injection).
Non-interactive rules: conflicts and unconsented unknowns exit non-zero.
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


def _legacy_ws(ws: Path) -> None:
    (ws / ".aisc").mkdir()
    (ws / ".aisc" / "containers.json").write_text('{"default": null}', encoding="utf-8")
    (ws / ".codex").mkdir()
    (ws / ".codex" / ".factory-version").write_text("2.1.4", encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    exe = os.environ.get("AISC_CLI_EXECUTABLE")
    argv = [exe] if exe else SYS_AISC
    env = os.environ.copy()
    env["AISC_DATA_ROOT"] = str(root)
    return subprocess.run([*argv, *args], capture_output=True, text=True, env=env)


class DataRootCliTests(unittest.TestCase):
    def test_doctor_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            proc = _run(root, "data-root", "doctor", "--workspace", str(ws),
                        "--format", "json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            envelope = json.loads(proc.stdout)
            self.assertEqual(envelope["meta"]["protocol"], "aisc.cli/v1")
            self.assertEqual(envelope["meta"]["exit_code"], 0)
            data = envelope["data"]
            self.assertEqual(data["data_root"]["root"], str(root))
            self.assertEqual(data["legacy"]["counts"]["owned"], 2)
            # Redaction: the raw workspace path is not in the payload.
            self.assertNotIn(str(ws), json.dumps(data))

    def test_migrate_dry_run_then_apply_then_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)

            dry = _run(root, "data-root", "migrate", "--workspace", str(ws),
                       "--dry-run", "--format", "json")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual(json.loads(dry.stdout)["data"]["plan"]["copy_count"], 2)

            apply1 = _run(root, "data-root", "migrate", "--workspace", str(ws),
                          "--format", "json")
            self.assertEqual(apply1.returncode, 0, apply1.stderr)
            result = json.loads(apply1.stdout)["data"]
            self.assertEqual(result["outcome"], "committed")
            self.assertEqual(result["copied"], 2)

            apply2 = _run(root, "data-root", "migrate", "--workspace", str(ws),
                          "--format", "json")
            result2 = json.loads(apply2.stdout)["data"]
            self.assertEqual(result2["copied"], 0)
            self.assertEqual(result2["skipped"], 2)

    def test_unknown_blocks_apply_nonzero_then_quarantines(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            (ws / ".claude").mkdir()
            (ws / ".claude" / "my-notes.txt").write_text("user data", encoding="utf-8")

            blocked = _run(root, "data-root", "migrate", "--workspace", str(ws),
                           "--format", "json")
            self.assertNotEqual(blocked.returncode, 0)
            envelope = json.loads(blocked.stdout)
            self.assertEqual(envelope["errors"][0]["code"],
                             "AISC_ERR_DATA_MIGRATION_UNKNOWN_PENDING")

            ok = _run(root, "data-root", "migrate", "--workspace", str(ws),
                      "--quarantine-unknown", "--format", "json")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["data"]["quarantined"], 1)

    def test_rollback_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            ws, root = Path(ws_tmp), Path(root_tmp)
            _legacy_ws(ws)
            _run(root, "data-root", "migrate", "--workspace", str(ws), "--format", "json")

            back = _run(root, "data-root", "rollback", "--workspace", str(ws),
                        "--format", "json")
            self.assertEqual(back.returncode, 0, back.stderr)
            result = json.loads(back.stdout)["data"]
            self.assertEqual(result["outcome"], "rolled_back")
            self.assertEqual(result["removed"], 2)
            # Sources intact after rollback.
            self.assertTrue((ws / ".aisc" / "containers.json").is_file())

    def test_relative_override_env_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp:
            ws = Path(ws_tmp)
            env = os.environ.copy()
            env["AISC_DATA_ROOT"] = "relative/path"
            exe = os.environ.get("AISC_CLI_EXECUTABLE")
            argv = [exe] if exe else SYS_AISC
            proc = subprocess.run(
                [*argv, "data-root", "doctor", "--workspace", str(ws),
                 "--format", "json"],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            envelope = json.loads(proc.stdout)
            self.assertEqual(envelope["errors"][0]["code"],
                             "AISC_ERR_DATA_ROOT_OVERRIDE_RELATIVE")


if __name__ == "__main__":
    unittest.main()
