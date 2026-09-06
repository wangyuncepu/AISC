"""PERF P4 (D-13): SDK-backed executor — parse-compatibility matrix.

The command layer's parsers (runtime.py `_query_docker_labels` /
`_get_container_state`, web_gateway helpers) consume CLI-shaped
ProcessResults. These tests pin that the SDK-mapped outputs are
BYTE-COMPATIBLE with those parsers, plus the fallback/escape semantics.
"""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "docker_sdk_backed", ROOT / "src" / "aisc" / "adapters" / "docker_sdk_backed.py"
)
assert _spec and _spec.loader
SB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SB)

from aisc.application.runtime import (  # noqa: E402
    _docker_status_to_state,
    _find_docker_container_by_runtime_id,
    _get_container_state,
)

RID = "550e8400-e29b-41d4-a716-446655440000"
FMT3 = "{{.ID}}\t{{.Names}}\t{{.Status}}"
FMT7 = (
    "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t"
    '{{.Label "io.aisc.runtime-id"}}\t'
    '{{.Label "io.aisc.workspace-key"}}\t'
    '{{.Label "io.aisc.owner"}}'
)


class _FakeContainer:
    def __init__(self, *, cid, name, image, running, labels):
        self.id = cid
        self.name = name
        self.labels = labels
        self.attrs = {
            "State": {"Running": running},
            "Names": [f"/{name}"],
            "Config": {"Image": image},
        }


class _FakeContainers:
    def __init__(self, rows):
        self._rows = rows

    def list(self, all=False, filters=None):  # noqa: A002 — docker-py API
        rows = self._rows
        if filters and "label" in filters:
            wanted = filters["label"]
            if isinstance(wanted, str):
                wanted = [wanted]
            for lab in wanted:
                k, _, v = lab.partition("=")
                rows = [r for r in rows if r.labels.get(k) == v]
        return rows


class _FakeApi:
    def __init__(self, containers, exec_stdout=b'{"ok": 1}', exec_code=0):
        self._containers = containers
        self._exec_stdout = exec_stdout
        self._exec_code = exec_code

    def inspect_container(self, name):
        for c in self._containers._rows:
            if c.name == name:
                return {
                    "State": {"Running": True},
                    "NetworkSettings": {"Ports": {"45871/tcp": [{"HostIp": "127.0.0.1", "HostPort": "47000"}]}},
                    "HostConfig": {"PortBindings": {"45871/tcp": [{"HostIp": "127.0.0.1", "HostPort": "47000"}]}},
                }
        import docker.errors

        raise docker.errors.NotFound(f"No such container: {name}")

    def exec_create(self, container, cmd, **kwargs):
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, **kwargs):
        import io

        return io.BytesIO(self._exec_stdout)

    def exec_inspect(self, exec_id):
        return {"ExitCode": self._exec_code, "Running": False}


class _FakeClient:
    def __init__(self, rows, **kw):
        self.containers = _FakeContainers(rows)
        self.api = _FakeApi(self.containers, **kw)

    def ping(self):
        return True


def _executor(rows, **kw):
    return SB.SdkBackedDockerExecutor(client=_FakeClient(rows, **kw))


ROWS = [
    _FakeContainer(
        cid="a" * 64, name="aisc-wb-1", image="super-claude:latest",
        running=True,
        labels={
            "io.aisc.managed": "true", "io.aisc.kind": "runtime",
            "io.aisc.runtime-id": RID, "io.aisc.workspace-key": "k",
            "io.aisc.owner": "workbench",
        },
    ),
    _FakeContainer(
        cid="b" * 64, name="other", image="nginx", running=False, labels={},
    ),
]


class SdkBackedExecutorTests(unittest.TestCase):
    def test_ps_find_by_runtime_id_parses_like_cli(self):
        ex = _executor(ROWS)
        found = _find_docker_container_by_runtime_id(RID, ex)
        self.assertEqual(found["container_name"], "aisc-wb-1")
        self.assertEqual(found["container_id"], "a" * 12)  # CLI short id
        self.assertEqual(found["state"], "running")

    def test_ps_status_maps_up_and_exited(self):
        self.assertEqual(_docker_status_to_state("Up"), "running")
        self.assertEqual(_docker_status_to_state("Exited"), "stopped")
        ex = _executor(ROWS)
        r = ex.run_captured(["ps", "-a", "--format", FMT3])
        lines = r.stdout.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("\tUp"))
        self.assertTrue(lines[1].endswith("\tExited"))

    def test_ps_seven_column_template_with_labels(self):
        ex = _executor(ROWS)
        r = ex.run_captured([
            "ps", "-a",
            "--filter", "label=io.aisc.managed=true",
            "--filter", "label=io.aisc.kind=runtime",
            "--format", FMT7,
        ])
        parts = r.stdout.split("\n")[0].split("\t")
        self.assertEqual(parts[1], "aisc-wb-1")
        self.assertEqual(parts[3], "Up")
        self.assertEqual(parts[4], RID)

    def test_inspect_container_shapes_and_not_found(self):
        ex = _executor(ROWS)
        r = ex.inspect_container("aisc-wb-1")
        self.assertEqual(r.exit_code, 0)
        data = json.loads(r.stdout)
        self.assertTrue(data[0]["State"]["Running"])
        # state parser path
        self.assertEqual(_get_container_state("aisc-wb-1", ex), "running")
        # not-found keeps the CLI stderr wording the callers match on
        r404 = ex.inspect_container("ghost")
        self.assertEqual(r404.exit_code, 1)
        self.assertIn("No such object", r404.stderr)
        self.assertEqual(_get_container_state("ghost", ex), "not_found")

    def test_exec_capture_maps_stdout_and_exit_code(self):
        ex = _executor(ROWS, exec_stdout=b'[{"port": 3000}]', exec_code=0)
        r = ex.run_captured(["exec", "aisc-wb-1", "aisc-web-list", "--json"])
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(json.loads(r.stdout)[0]["port"], 3000)
        ex2 = _executor(ROWS, exec_stdout=b"", exec_code=7)
        self.assertEqual(
            ex2.run_captured(["exec", "aisc-wb-1", "tool"]).exit_code, 7
        )

    def test_unknown_shapes_fall_back_to_cli(self):
        ex = _executor(ROWS)
        with mock.patch.object(ex._cli, "run_captured") as cli_call:
            cli_call.return_value = "cli-result"
            # flags in exec → CLI; unknown ps flag → CLI; other verbs → CLI
            self.assertEqual(
                ex.run_captured(["exec", "-e", "K=V", "c", "cmd"]), "cli-result"
            )
            self.assertEqual(
                ex.run_captured(["ps", "--latest", "5"]), "cli-result"
            )
            self.assertEqual(ex.run_captured(["info"]), "cli-result")

    def test_delegation_and_preflight(self):
        ex = _executor(ROWS)
        self.assertTrue(ex.preflight().available)
        with mock.patch.object(ex._cli, "stop_container") as stop:
            stop.return_value = "stopped"
            self.assertEqual(ex.stop_container("x"), "stopped")  # __getattr__ delegate

    def test_env_escape_hatch(self):
        with mock.patch.dict(os.environ, {"AISC_DOCKER_EXECUTOR": "cli"}):
            e = SB.default_executor()
            self.assertNotIsInstance(e, SB.SdkBackedDockerExecutor)
        with mock.patch.dict(os.environ, {}):
            self.assertIsInstance(SB.default_executor(), SB.SdkBackedDockerExecutor)


if __name__ == "__main__":
    unittest.main()
