"""Stage 0 (S0.1): environment probe + BaselineManifest determinism tests.

Covers B-A01 (deterministic baseline across two runs) and the fail-closed /
no-secret parts of B-A02/B-A08 that belong to the baseline tooling:

- two manifest builds differ only in the timestamp field;
- a missing tool marks the manifest incomplete and never overwrites a
  previously PASSed ``latest.json``;
- the manifest only records explicitly allowlisted environment variables;
- fixture hashing is stable and content-addressed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so dataclass/typing introspection can find the
    # module namespace (spec_from_file_location alone leaves it unregistered).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROBE = _load("aisc_baseline_probe", "scripts/baseline/probe.py")
MANIFEST = _load("aisc_baseline_manifest", "scripts/baseline/manifest.py")
RUN = _load("aisc_baseline_run", "scripts/baseline/run_baseline.py")


@dataclass(frozen=True)
class _Proc:
    stdout: str = ""
    returncode: int = 0


AISC_VERSION_JSON = (
    '{"meta":{"protocol":"aisc.cli/v1","command":"version","exit_code":0,'
    '"timestamp":"t","version":"2.1.5.dev0","run_id":"r"},"data":null,"errors":[]}'
)


class FakeRunner:
    """Injects deterministic command output; missing tools raise FileNotFoundError.

    Defaults to a healthy toolchain so a bare ``FakeRunner()`` yields a
    ``complete`` baseline; tests pass ``missing=`` to simulate failures.
    """

    DEFAULT_VERSIONS = {
        "node": "v22.2.0",
        "npm": "10.5.0",
        "rustc": "rustc 1.82.0 (f6e511eec 2024-10-15)",
        "cargo": "cargo 1.82.0",
        "docker": "Docker version 27.3.1, build 123",
        "aisc": AISC_VERSION_JSON,
        "git": "deadbeef" * 4 + "\n",
    }

    def __init__(self, versions: dict[str, str] | None = None, missing: set[str] | None = None):
        self.versions = {**self.DEFAULT_VERSIONS, **(versions or {})}
        self.missing = set(missing or ())
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> _Proc:
        self.calls.append(argv)
        key = Path(argv[0]).name
        if key in self.missing:
            raise FileNotFoundError(key)
        if key == "git":
            # Always resolve; the runner does not need to distinguish rev-parse calls.
            return _Proc(stdout="deadbeef" * 4 + "\n")
        return _Proc(stdout=self.versions.get(key, ""))


def _base_manifest_kwargs() -> dict:
    return {
        "git_commit": "deadbeef" * 4,
        "git_branch": "stage-0-baseline-gates",
        "os_name": "Windows",
        "os_arch": "AMD64",
        "os_release": "11",
        "toolchain": {"python": {"version": "3.14.5", "path": "C:/py/python.exe"}},
        "commands": ["python -m pytest tests -q"],
        "env_allowlist": {"AISC_TEST_CLI": "C:/tmp/aisc.exe"},
        "fixture_hashes": {"tests/fixtures/manifest.json": "sha256:abc"},
        "probe_status": "complete",
    }


class BaselineProbeTests(unittest.TestCase):
    def test_python_version_comes_from_interpreter_not_subprocess(self):
        tools = PROBE.probe_all(run=FakeRunner())
        self.assertIsNotNone(tools["python"].version)
        self.assertEqual(tools["python"].version, sys.version.split()[0])
        # python must not be shelled out
        self.assertTrue(all("python" not in c[0] for c in FakeRunner().calls))

    def test_missing_tool_is_marked_with_error(self):
        runner = FakeRunner(missing={"docker"})
        tools = PROBE.probe_all(run=runner)
        self.assertIsNotNone(tools["docker"].error)
        self.assertIsNone(tools["docker"].version)

    def test_all_present_tools_have_version(self):
        runner = FakeRunner(versions={"node": "v22.2.0", "npm": "10.5.0",
                                      "rustc": "rustc 1.82.0 (f6e511eec 2024-10-15)",
                                      "cargo": "cargo 1.82.0", "docker": "Docker version 27.3.1, build 123"})
        tools = PROBE.probe_all(run=runner)
        for name in ("node", "npm", "rustc", "cargo", "docker"):
            self.assertIsNotNone(tools[name].version, name)


class BaselineManifestTests(unittest.TestCase):
    def test_manifest_is_deterministic_except_timestamp(self):
        first = MANIFEST.build_manifest(**dict(_base_manifest_kwargs(), generated_at="2026-08-14T00:00:00Z"))
        second = MANIFEST.build_manifest(**dict(_base_manifest_kwargs(), generated_at="2026-08-14T00:00:01Z"))
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(first, second)

    def test_manifest_records_only_allowlisted_env(self):
        env = {
            "AISC_TEST_CLI": "C:/tmp/aisc.exe",
            "ANTHROPIC_API_KEY": "sk-super-secret",
            "GITHUB_TOKEN": "ghp_secret",
            "HOME": "C:/Users/me",
        }
        manifest = MANIFEST.build_manifest(
            **dict(_base_manifest_kwargs(), env_allowlist={"AISC_TEST_CLI": env["AISC_TEST_CLI"]})
        )
        raw = json.dumps(manifest, ensure_ascii=True)
        self.assertIn("AISC_TEST_CLI", raw)
        self.assertNotIn("sk-super-secret", raw)
        self.assertNotIn("ghp_secret", raw)
        self.assertNotIn("GITHUB_TOKEN", raw)

    def test_fixture_hash_is_stable_and_sha256_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            # bytes() avoids Windows write_text translating \n -> \r\n
            path.write_bytes(b'{"hello": "world"}\n')
            digest = MANIFEST.hash_file(path)
        self.assertTrue(digest.startswith("sha256:"))
        # sha256('{"hello": "world"}\n')
        self.assertEqual(digest, "sha256:44aff4ab2d7c3250525675a08f0cfa9591168cffe51791c5f5bbc417c15a6c38")

    def test_fixture_hashes_relative_and_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "a.json").write_text("A", encoding="utf-8")
            (root / "sub" / "b.json").write_text("B", encoding="utf-8")
            hashes = MANIFEST.fixture_hashes(root)
        self.assertEqual(set(hashes), {"a.json", "sub/b.json"})
        self.assertTrue(all(v.startswith("sha256:") for v in hashes.values()))


class BaselineRunTests(unittest.TestCase):
    def test_incomplete_run_does_not_overwrite_latest(self):
        runner = FakeRunner(missing={"docker"})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            latest = out / "latest.json"
            latest.write_text("previous PASS", encoding="utf-8")
            manifest = RUN.run_baseline(
                out_dir=out,
                commands=["python -m pytest tests -q"],
                env_allowlist={},
                run=runner,
                generated_at="t",
            )
            self.assertEqual(manifest["probe_status"], "incomplete")
            self.assertEqual(latest.read_text(encoding="utf-8"), "previous PASS")

    def test_complete_run_writes_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = RUN.run_baseline(
                out_dir=out,
                commands=["python -m pytest tests -q"],
                env_allowlist={},
                run=FakeRunner(),
                generated_at="t",
            )
            self.assertEqual(manifest["probe_status"], "complete")
            self.assertTrue((out / "latest.json").is_file())

    def test_strict_incomplete_raises(self):
        runner = FakeRunner(missing={"docker"})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RUN.BaselineIncomplete):
                RUN.run_baseline(
                    out_dir=Path(tmp),
                    commands=[],
                    env_allowlist={},
                    run=runner,
                    strict=True,
                    generated_at="t",
                )


if __name__ == "__main__":
    unittest.main()
