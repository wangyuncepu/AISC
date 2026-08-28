"""Unit tests for runtime lifecycle commands (start/list/inspect/stop/restart/remove).

Uses a purpose-built fake Docker executor so no Docker daemon is required.
Exercises the application logic in ``aisc.application.runtime`` against a
temp-file registry, covering idempotency, conflicts, lock ordering, ready
check, cleanup-on-failure and reconciliation per contract §5.2-5.5.
"""


# Stage 7: keep run/start paths hermetic — they resolve the data root and
# create the agent mount dirs; without this the tests would write into the
# real %LOCALAPPDATA% AISC data.
import os as _os
import tempfile as _tempfile
_os.environ.setdefault("AISC_DATA_ROOT", _tempfile.mkdtemp(prefix="aisc-test-data-"))
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aisc.adapters.container_registry import (
    list_containers,
    list_containers_readonly,
    register,
)
from aisc.application.runtime import (
    _READY_COLD_TIMEOUT,
    _READY_DEFAULT_TIMEOUT,
    _registry_has_history,
    container_name_for,
    inspect_runtime,
    list_runtimes,
    remove_runtime,
    restart_runtime,
    start_runtime,
    stop_runtime,
    workspace_key_for,
)
from aisc.domain.models import (
    CliError,
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
    RuntimeErrorCode,
    RuntimeExitCode,
)

RID_A = "550e8400-e29b-41d4-a716-446655440000"
RID_B = "660e8400-e29b-41d4-a716-446655440000"


class RuntimeFakeExecutor:
    """In-memory Docker executor for runtime lifecycle tests.

    Tracks created containers and answers ``run_captured``/``inspect_container``
    /``stop_container``/``remove_container`` consistently so the application
    layer's Docker calls are exercised realistically.
    """

    def __init__(self, docker_available=True, image_exists=True, ready=True):
        self.docker_available = docker_available
        self.image_exists = image_exists
        self.ready = ready
        # name -> {container_id, state, runtime_id, workspace_key, owner, image}
        self.containers: dict = {}
        self.removed: list = []
        self._next = 0

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _arg_after(argv, flag):
        for i, a in enumerate(argv):
            if a == flag and i + 1 < len(argv):
                return argv[i + 1]
        return ""

    @staticmethod
    def _label_val(argv, label):
        needle = f"{label}="
        for a in argv:
            idx = a.find(needle)
            if idx >= 0:
                return a[idx + len(needle):]
        return ""

    def _status_str(self, state):
        return "Up 2 seconds" if state == "running" else "Exited (0) 1s ago"

    def _ps_result(self, argv):
        joined = " ".join(argv)
        if "io.aisc.managed=true" in joined:
            lines = []
            for name, c in self.containers.items():
                lines.append("\t".join([
                    c["container_id"], name, c["image"], self._status_str(c["state"]),
                    c["runtime_id"], c["workspace_key"], c["owner"],
                ]))
            return ProcessResult(stdout="\n".join(lines), stderr="", exit_code=0)
        # label=io.aisc.runtime-id=<rid> query (3 fields)
        rid = self._label_val(argv, "io.aisc.runtime-id")
        lines = []
        for name, c in self.containers.items():
            if rid and c["runtime_id"] == rid:
                lines.append("\t".join([
                    c["container_id"], name, self._status_str(c["state"]),
                ]))
        return ProcessResult(stdout="\n".join(lines), stderr="", exit_code=0)

    # -- DockerExecutor protocol ---------------------------------------
    def preflight(self):
        return DockerPreflightResult(
            docker_path="/usr/bin/docker",
            available=self.docker_available,
            reason="ok" if self.docker_available else "daemon_unreachable",
        )

    def inspect_image(self, name):
        if self.image_exists:
            return ImageInspectResult(
                status=ImageInspectStatus.EXISTS, image=name,
                image_id=getattr(self, "image_id", "sha256:fake-image"),
            )
        return ImageInspectResult(status=ImageInspectStatus.MISSING, image=name)

    def run_captured(self, argv, *, timeout=None):
        cmd = argv[0] if argv else ""
        if cmd == "run":
            name = self._arg_after(argv, "--name")
            rid = self._label_val(argv, "io.aisc.runtime-id")
            wskey = self._label_val(argv, "io.aisc.workspace-key")
            owner = self._label_val(argv, "io.aisc.owner")
            image = argv[-1]
            self._next += 1
            cid = f"cid{self._next:012d}"
            self.containers[name] = {
                "container_id": cid,
                "state": "running" if self.ready else "stopped",
                "runtime_id": rid,
                "workspace_key": wskey,
                "owner": owner,
                "image": image,
            }
            return ProcessResult(stdout=cid, stderr="", exit_code=0)
        if cmd == "exec":
            name = argv[1]
            c = self.containers.get(name)
            if c and self.ready:
                ctx = {
                    "schema_version": "aisc.runtime-context/v1",
                    "runtime_id": c["runtime_id"],
                    "scope": "project",
                }
                return ProcessResult(stdout=json.dumps(ctx), stderr="", exit_code=0)
            return ProcessResult(stdout="", stderr="not ready", exit_code=1)
        if cmd == "ps":
            return self._ps_result(argv)
        if cmd == "start":
            name = argv[1]
            if name in self.containers:
                self.containers[name]["state"] = "running"
            return ProcessResult(stdout="", stderr="", exit_code=0)
        return ProcessResult(stdout="", stderr="", exit_code=0)

    def inspect_container(self, name):
        c = self.containers.get(name)
        if c is None:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        data = [{"State": {"Running": c["state"] == "running"}}]
        return ProcessResult(stdout=json.dumps(data), stderr="", exit_code=0)

    def stop_container(self, name, timeout=10):
        c = self.containers.get(name)
        if c is None:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        c["state"] = "stopped"
        return ProcessResult(stdout="", stderr="", exit_code=0)

    def remove_container(self, name, force=False):
        if name not in self.containers:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        del self.containers[name]
        self.removed.append(name)
        return ProcessResult(stdout="", stderr="", exit_code=0)


def _make_workspace():
    d = tempfile.mkdtemp()
    return Path(d)


class TestContainerNaming(unittest.TestCase):
    def test_container_name(self):
        self.assertEqual(container_name_for(RID_A), "aisc-wb-550e8400")

    def test_workspace_key_is_sha256_hex(self):
        key = workspace_key_for("/tmp/foo")
        self.assertEqual(len(key), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))


class TestStartRuntime(unittest.TestCase):
    def test_start_success(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        result = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(result.state, "running")
        self.assertTrue(result.ready)
        self.assertFalse(result.reused)
        self.assertEqual(result.container_name, "aisc-wb-550e8400")
        self.assertTrue(result.container_id)
        self.assertEqual(result.config["scope"], "project")

        # registry entry committed with all fields
        entries = list_containers_readonly(ws / ".aisc")
        self.assertEqual(len(entries), 1)
        meta = entries["aisc-wb-550e8400"]
        self.assertEqual(meta["runtime_id"], RID_A)
        self.assertEqual(meta["scope"], "project")
        self.assertEqual(meta["owner"], "workbench")
        self.assertTrue(meta["config_fingerprint"].startswith("sha256:"))
        self.assertEqual(meta["container_id"], result.container_id)
        self.assertTrue(meta["workspace_key"])

    def test_start_idempotent_reuse(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        first = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                              "project", "workbench", executor=ex,
                              registry_root=ws / ".aisc", ready_timeout=2.0)
        second = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(second.reused)
        self.assertEqual(second.state, "running")
        self.assertTrue(second.ready)
        self.assertEqual(second.container_id, first.container_id)
        # only one container created
        self.assertEqual(len(ex.containers), 1)

    def test_start_conflict_different_fingerprint(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_A, str(ws), "other:tag", "direct", "project",
                          "workbench", executor=ex, registry_root=ws / ".aisc",
                          ready_timeout=2.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_CONFLICT)

    def test_start_project_workspace_conflict(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_B, str(ws), "super-claude:latest", "direct", "project",
                          "workbench", executor=ex, registry_root=ws / ".aisc",
                          ready_timeout=2.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_CONFLICT)

    # -- 容器随镜像同步更新 (KI-4 挂账) ----------------------------------

    def test_start_records_image_id_and_reuses_when_unchanged(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ex.image_id = "sha256:image-v1"
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        meta = list_containers_readonly(ws / ".aisc")["aisc-wb-550e8400"]
        self.assertEqual(meta["image_id"], "sha256:image-v1")

        second = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(second.reused)
        self.assertEqual(len(ex.containers), 1)

    def test_start_conflict_image_changed(self):
        """Same tag rebuilt (image ID differs) → reuse is refused as a
        conflict with a precise reason; the existing recreate guidance
        takes over."""
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ex.image_id = "sha256:image-v1"
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        ex.image_id = "sha256:image-v2"  # image rebuilt under the same tag
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                          "project", "workbench", executor=ex,
                          registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_CONFLICT)
        conflicts = cm.exception.data.get("conflicts", [])
        self.assertEqual(len(conflicts), 1)
        self.assertIn("image", conflicts[0]["reason"].lower())
        # nothing was reused or created
        self.assertEqual(len(ex.containers), 1)

    def test_start_reuse_when_image_id_unobservable(self):
        """A transient probe failure (current image ID unobservable) must
        never block reuse — unknown ≠ changed."""
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ex.image_id = "sha256:image-v1"
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        with patch("aisc.application.runtime._resolve_image_id",
                   return_value=None):
            second = start_runtime(RID_A, str(ws), "super-claude:latest",
                                   "direct", "project", "workbench", executor=ex,
                                   registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(second.reused)

    def test_start_legacy_meta_heals_image_id(self):
        """Records created before this change carry no image_id: they stay
        reusable (no false conflict) and the reuse start back-fills the
        field so future rebuilds are detected."""
        from aisc.adapters.container_registry import register as reg_register

        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ex.image_id = "sha256:image-v1"
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        name = "aisc-wb-550e8400"
        reg = ws / ".aisc"
        legacy_meta = dict(list_containers_readonly(reg)[name])
        legacy_meta.pop("image_id")
        reg_register(reg, name, legacy_meta, set_default=False)
        self.assertEqual(
            list_containers_readonly(reg)[name].get("image_id", ""), "")

        second = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(second.reused)
        self.assertEqual(
            list_containers_readonly(reg)[name]["image_id"], "sha256:image-v1")

    def test_start_ready_timeout_cleans_up(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor(ready=False)
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                          "workbench", executor=ex, registry_root=ws / ".aisc",
                          ready_timeout=1.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_OPERATION_FAILED)
        # container must be removed and no registry entry written
        self.assertEqual(ex.containers, {})
        self.assertEqual(ex.removed, ["aisc-wb-550e8400"])
        self.assertEqual(list_containers_readonly(ws / ".aisc"), {})

    def test_start_registry_commit_failure_cleans_up(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        with patch("aisc.adapters.container_registry.register",
                   side_effect=OSError("disk full")):
            with self.assertRaises(CliError) as cm:
                start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                              "project", "workbench", executor=ex,
                              registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_OPERATION_FAILED)
        self.assertEqual(ex.removed, ["aisc-wb-550e8400"])

    def test_start_registry_lock_timeout_cleans_up_and_preserves_code(self):
        """If register raises CliError(STATE_LOCK_TIMEOUT) (registry lock
        contention), the just-created container is still cleaned up and the
        original STATE_LOCK_TIMEOUT code is preserved -- not remapped to
        RUNTIME_OPERATION_FAILED and not orphaned (review regression)."""
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        lock_err = CliError(
            message="Failed to acquire registry lock within 10s",
            exit_code=RuntimeExitCode.STATE_LOCK_TIMEOUT,
            error_code=RuntimeErrorCode.STATE_LOCK_TIMEOUT,
        )
        with patch("aisc.adapters.container_registry.register",
                   side_effect=lock_err):
            with self.assertRaises(CliError) as cm:
                start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                              "project", "workbench", executor=ex,
                              registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.STATE_LOCK_TIMEOUT)
        self.assertEqual(cm.exception.error_code, RuntimeErrorCode.STATE_LOCK_TIMEOUT)
        # Container cleaned up, no orphan, no registry entry.
        self.assertEqual(ex.removed, ["aisc-wb-550e8400"])
        self.assertEqual(ex.containers, {})
        self.assertEqual(list_containers_readonly(ws / ".aisc"), {})

    def test_start_invalid_runtime_id(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        with self.assertRaises(CliError) as cm:
            start_runtime("not-a-uuid", str(ws), "super-claude:latest", "direct",
                          "project", "workbench", executor=ex,
                          registry_root=ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.INVALID_RUNTIME_ID)

    def test_start_docker_unavailable(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor(docker_available=False)
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                          "workbench", executor=ex, registry_root=ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.DOCKER_UNAVAILABLE)

    def test_start_image_missing(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor(image_exists=False)
        with self.assertRaises(CliError) as cm:
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                          "workbench", executor=ex, registry_root=ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, 5)


class TestListRuntimes(unittest.TestCase):
    def test_list_empty(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        runtimes = list_runtimes(ex, ws / ".aisc")
        self.assertEqual(runtimes, [])

    def test_list_registered_and_missing(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        # inject a Docker-only container (missing from registry) for same workspace
        ws_key = workspace_key_for(str(ws))
        ex.containers["aisc-wb-orphan"] = {
            "container_id": "orphan001", "state": "running",
            "runtime_id": RID_B, "workspace_key": ws_key, "owner": "workbench",
            "image": "super-claude:latest",
        }
        runtimes = list_runtimes(ex, ws / ".aisc")
        states = {r.container_name: r.registry_state for r in runtimes}
        self.assertEqual(states["aisc-wb-550e8400"], "registered")
        self.assertEqual(states["aisc-wb-orphan"], "missing")

    def test_list_docker_unavailable(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor(docker_available=False)
        with self.assertRaises(CliError) as cm:
            list_runtimes(ex, ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.DOCKER_UNAVAILABLE)

    def test_list_owner_filter(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        register(ws / ".aisc", "aisc-wb-550e8400", {
            "image": "super-claude:latest", "workspace": str(ws),
            "runtime_id": RID_A, "owner": "workbench", "scope": "project",
            "config_fingerprint": "sha256:a", "container_id": "x",
            "workspace_key": workspace_key_for(str(ws)),
        })
        register(ws / ".aisc", "other-runtime", {
            "image": "super-claude:latest", "workspace": str(ws),
            "runtime_id": RID_B, "owner": "someone-else", "scope": "project",
            "config_fingerprint": "sha256:b", "container_id": "y",
            "workspace_key": workspace_key_for(str(ws)),
        })
        runtimes = list_runtimes(ex, ws / ".aisc", owner="workbench")
        owners = {r.owner for r in runtimes}
        self.assertEqual(owners, {"workbench"})


class TestInspectRuntime(unittest.TestCase):
    def test_inspect_not_found(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        snap = inspect_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap.state, "not_found")

    def test_inspect_running(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        snap = inspect_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap.state, "running")
        self.assertEqual(snap.registry_state, "registered")

    def test_inspect_unknown_when_docker_down(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor(docker_available=False)
        snap = inspect_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap.state, "unknown")

    def test_inspect_invalid_runtime_id(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        with self.assertRaises(CliError) as cm:
            inspect_runtime("bad", ex, ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.INVALID_RUNTIME_ID)


class TestColdStartReadyTimeout(unittest.TestCase):
    """S8d: a workspace's FIRST start (empty registry = cold caches) widens
    the ready wait to _READY_COLD_TIMEOUT; an explicit ready_timeout always
    wins, and a registry with history keeps the steady-state budget."""

    def test_registry_has_history_states(self):
        ws = _make_workspace()
        self.assertFalse(_registry_has_history(ws / ".aisc"))  # fresh = cold
        register(ws / ".aisc", "aisc-wb-550e8400", {
            "runtime_id": RID_A, "owner": "workbench",
            "config_fingerprint": "sha256:x", "container_id": "cid",
        })
        self.assertTrue(_registry_has_history(ws / ".aisc"))  # history = warm
        # Corrupt registry: warm (the steady-state default never depends on
        # a broken state file).
        (ws / ".aisc" / "registry.json").write_text("{broken", encoding="utf-8")
        self.assertTrue(_registry_has_history(ws / ".aisc"))

    def _captured_wait_timeout(self, ws, ex, ready_timeout):
        from aisc.application import runtime as runtime_mod

        captured = {}
        real_wait = runtime_mod._wait_ready

        def spy(executor, name, rid, timeout=_READY_DEFAULT_TIMEOUT):
            captured["timeout"] = timeout
            return real_wait(executor, name, rid, timeout=timeout)

        kwargs = {"executor": ex, "registry_root": ws / ".aisc"}
        if ready_timeout is not None:
            kwargs["ready_timeout"] = ready_timeout
        # Patch the gateway allocator (function-local import → patch the
        # source) so the test never binds a real host port.
        with patch("aisc.application.web_gateway.allocate_gateway_host_port",
                   return_value=47001), \
                patch.object(runtime_mod, "_wait_ready", side_effect=spy):
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                          "project", "workbench", **kwargs)
        return captured["timeout"]

    def test_cold_first_start_gets_extended_budget(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        timeout = self._captured_wait_timeout(ws, ex, ready_timeout=None)
        self.assertEqual(timeout, _READY_COLD_TIMEOUT)

    def test_warm_registry_keeps_steady_state(self):
        from aisc.application import runtime as runtime_mod

        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        captured = {}
        real_wait = runtime_mod._wait_ready

        def spy(executor, name, rid, timeout=_READY_DEFAULT_TIMEOUT):
            captured["timeout"] = timeout
            return real_wait(executor, name, rid, timeout=timeout)

        # Warm = the history probe says True (seeding a real entry would
        # trip project-scope conflict semantics, so stub the probe).
        with patch("aisc.application.web_gateway.allocate_gateway_host_port",
                   return_value=47001), \
                patch.object(runtime_mod, "_registry_has_history", return_value=True), \
                patch.object(runtime_mod, "_wait_ready", side_effect=spy):
            start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                          "project", "workbench", executor=ex,
                          registry_root=ws / ".aisc")
        self.assertEqual(captured["timeout"], _READY_DEFAULT_TIMEOUT)

    def test_explicit_ready_timeout_always_wins(self):
        ws = _make_workspace()  # cold workspace
        ex = RuntimeFakeExecutor()
        timeout = self._captured_wait_timeout(ws, ex, ready_timeout=2.0)
        self.assertEqual(timeout, 2.0)


class TestStopRestartRemove(unittest.TestCase):
    def _start(self, ws, ex):
        return start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                             "project", "workbench", executor=ex,
                             registry_root=ws / ".aisc", ready_timeout=2.0)

    def test_stop_idempotent(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        first = stop_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(first.state, "stopped")
        # stopping an already-stopped container succeeds
        second = stop_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(second.state, "stopped")
        # registry entry preserved
        self.assertIn("aisc-wb-550e8400", list_containers_readonly(ws / ".aisc"))

    def test_restart(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        stop_runtime(RID_A, ex, ws / ".aisc")
        snap = restart_runtime(RID_A, ex, ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(snap.state, "running")

    def test_remove_running_without_force_rejected(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        with self.assertRaises(CliError) as cm:
            remove_runtime(RID_A, ex, ws / ".aisc", force=False)
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_OPERATION_FAILED)
        # still registered
        self.assertIn("aisc-wb-550e8400", list_containers_readonly(ws / ".aisc"))

    def test_remove_running_with_force(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        snap = remove_runtime(RID_A, ex, ws / ".aisc", force=True)
        self.assertEqual(snap.state, "not_found")
        self.assertEqual(ex.removed, ["aisc-wb-550e8400"])
        self.assertNotIn("aisc-wb-550e8400", list_containers_readonly(ws / ".aisc"))

    def test_remove_stopped(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        stop_runtime(RID_A, ex, ws / ".aisc")
        snap = remove_runtime(RID_A, ex, ws / ".aisc", force=False)
        self.assertEqual(snap.state, "not_found")
        self.assertEqual(ex.removed, ["aisc-wb-550e8400"])

    def test_remove_not_found_is_idempotent(self):
        # Contract §十二: remove is idempotent. Removing a runtime that is
        # already gone returns a not_found snapshot (rc 0), not an error.
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        snap = remove_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap.state, "not_found")
        self.assertEqual(snap.registry_state, "not_found")
        # A second remove of the same (still-absent) runtime also succeeds.
        snap2 = remove_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap2.state, "not_found")

    # --- G-07 (05 §3.1): --grace plumbing and command-layer validation ---

    def test_stop_default_grace_is_ten(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        with patch.object(ex, "stop_container", wraps=ex.stop_container) as sp:
            stop_runtime(RID_A, ex, ws / ".aisc")
            sp.assert_called_once()
            self.assertEqual(sp.call_args.kwargs.get("timeout"), 10)

    def test_stop_threads_explicit_grace(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        with patch.object(ex, "stop_container", wraps=ex.stop_container) as sp:
            stop_runtime(RID_A, ex, ws / ".aisc", grace_seconds=3)
            sp.assert_called_once()
            self.assertEqual(sp.call_args.kwargs.get("timeout"), 3)

    def test_cmd_runtime_stop_rejects_out_of_range_grace(self):
        from aisc.cli.commands.runtime import cmd_runtime_stop
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        self._start(ws, ex)
        for bad in (0, -1, 601):
            with self.assertRaises(CliError) as cm:
                cmd_runtime_stop(RID_A, str(ws), executor=ex, grace_seconds=bad)
            self.assertEqual(cm.exception.exit_code, 2)
            self.assertEqual(cm.exception.error_code, "AISC_ERR_USAGE")
        # validation happens before any Docker call: container still running
        self.assertEqual(ex.containers["aisc-wb-550e8400"]["state"], "running")


class TestReviewFixes(unittest.TestCase):
    """Regression tests for issues raised in the 645170b code review."""

    def test_stop_docker_only_container_marked_missing(self):
        """Stopping a container that exists in Docker but not the registry
        reports registry_state='missing', not 'registered' (review medium 2)."""
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ws_key = workspace_key_for(str(ws))
        # Inject a Docker-only container (no registry entry).
        ex.containers["aisc-wb-550e8400"] = {
            "container_id": "cid000000000001", "state": "running",
            "runtime_id": RID_A, "workspace_key": ws_key, "owner": "workbench",
            "image": "super-claude:latest",
        }
        snap = stop_runtime(RID_A, ex, ws / ".aisc")
        self.assertEqual(snap.state, "stopped")
        self.assertEqual(snap.registry_state, "missing")

    def test_restart_docker_only_container_marked_missing(self):
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        ws_key = workspace_key_for(str(ws))
        ex.containers["aisc-wb-550e8400"] = {
            "container_id": "cid000000000001", "state": "stopped",
            "runtime_id": RID_A, "workspace_key": ws_key, "owner": "workbench",
            "image": "super-claude:latest",
        }
        snap = restart_runtime(RID_A, ex, ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(snap.state, "running")
        self.assertEqual(snap.registry_state, "missing")

    def test_wait_ready_continues_past_transient_exception(self):
        """A single docker exec exception must not abort _wait_ready (review
        low-med 3); it should keep polling until the context appears."""
        from aisc.application.runtime import _wait_ready

        class TransientExecutor:
            def __init__(self):
                self.calls = 0
            def run_captured(self, argv, *, timeout=None):
                if argv[0] == "exec":
                    self.calls += 1
                    if self.calls == 1:
                        raise OSError("container briefly restarting")
                    return ProcessResult(
                        stdout=json.dumps({
                            "schema_version": "aisc.runtime-context/v1",
                            "runtime_id": RID_A,
                        }),
                        stderr="", exit_code=0,
                    )
                return ProcessResult(stdout="", stderr="", exit_code=0)

        ex = TransientExecutor()
        ctx = _wait_ready(ex, "aisc-wb-550e8400", RID_A, timeout=5.0)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["runtime_id"], RID_A)
        self.assertGreaterEqual(ex.calls, 2)

    def test_wait_ready_returns_none_on_timeout_only(self):
        """When the context never appears, _wait_ready polls until the deadline
        and returns None (not on the first non-zero exec)."""
        from aisc.application.runtime import _wait_ready

        class NeverReadyExecutor:
            def run_captured(self, argv, *, timeout=None):
                return ProcessResult(stdout="", stderr="no such file", exit_code=1)

        ctx = _wait_ready(NeverReadyExecutor(), "aisc-wb-550e8400", RID_A, timeout=1.0)
        self.assertIsNone(ctx)

    def test_start_reuse_stopped_restarts_to_running(self):
        """Re-calling start on a stopped matching runtime restarts it instead
        of returning a reused-but-stopped limbo (review low-med 4)."""
        ws = _make_workspace()
        ex = RuntimeFakeExecutor()
        start_runtime(RID_A, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        stop_runtime(RID_A, ex, ws / ".aisc")
        # Re-call start with the same runtime_id + config.
        result = start_runtime(RID_A, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(result.reused)
        self.assertEqual(result.state, "running")
        self.assertTrue(result.ready)
        # No second container was created.
        self.assertEqual(len(ex.containers), 1)


if __name__ == "__main__":
    unittest.main()
