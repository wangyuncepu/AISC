"""PERF P4 (D-13): SDK-backed Docker executor for the command layer.

The runtime/provider/services command layer used to hardcode
``RealDockerExecutor`` — every Docker call inside each aisc.exe invocation
was a ``docker.exe`` subprocess chain (info → ps → inspect → exec). On weak
machines each docker.exe cold start costs 100-300ms × 5-6 calls per tick.

``SdkBackedDockerExecutor`` implements the same ``DockerExecutor`` protocol
with the HOT-READ face served over the docker SDK's named-pipe/unix-socket
HTTP client (in-process, zero subprocesses):

- ``preflight()`` — SDK ping first, CLI fallback (reason vocabulary kept)
- ``inspect_container(name)`` — SDK inspect; NotFound maps to the CLI's
  "No such object" stderr semantics the callers pattern-match
- ``run_captured`` for the three hot argv shapes:
  * ``ps -a --filter label=... --format <template>`` — SDK containers.list
    + a mini renderer for the templates we ship (``ID``/``Names``/``Image``/
    ``Status``/``Label "k"`` tokens only — anything else falls back to CLI)
  * ``exec <name> <cmd...>`` (no flags) — exec_create/start/inspect
  * ``inspect <name>``
- everything else (run/build/start/stop/rm/pull/... and all streaming /
  interactive methods) delegates verbatim to an inner ``RealDockerExecutor``
  — low-frequency control operations where the CLI's behavior is battle-
  tested (buildx flags, process groups, etc.).

Failure semantics: ANY SDK exception on a mapped path falls back to the CLI
invocation — worst case = today's behavior, never worse.
``AISC_DOCKER_EXECUTOR=cli`` restores the pure-CLI executor globally.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from aisc.domain.models import DockerPreflightResult, ProcessResult

# Templates the ps renderer understands — every token must be one of
# ID / Names / Image / Status / Label "k". Anything else → CLI fallback.
_PS_TOKEN = re.compile(r'\{\{\.(ID|Names|Image|Status|Label "([^"]+)")\}\}')


def _render_ps_line(template: str, c: Any) -> Optional[str]:
    """Render one docker-ps line for a SDK container object.

    ``Status`` synthesizes the CLI's human form ("Up"/"Exited") — the only
    property consumers rely on is ``startswith("Up")`` (runtime.py
    ``_docker_status_to_state``)."""
    out: List[str] = []
    pos = 0
    for m in _PS_TOKEN.finditer(template):
        out.append(template[pos : m.start()])
        label_key = m.group(2)
        try:
            if label_key is not None:
                out.append(str(c.labels.get(label_key, "")))
            elif m.group(1) == "Status":
                out.append("Up" if bool(c.attrs.get("State", {}).get("Running")) else "Exited")
            elif m.group(1) == "ID":
                out.append(str(c.id)[:12])
            elif m.group(1) == "Names":
                names = list(c.attrs.get("Names") or [])
                out.append((names[0] if names else c.name).lstrip("/"))
            elif m.group(1) == "Image":
                # attrs-only: `c.image` costs one extra API roundtrip per
                # container on the real SDK — Config.Image rides list already.
                out.append(str(c.attrs.get("Config", {}).get("Image", "")))
            else:
                return None  # unreachable; keeps the checker honest
        except Exception:  # noqa: BLE001 — unexpected shape: bail to CLI
            return None
        pos = m.end()
    out.append(template[pos:])
    return "".join(out)


class SdkBackedDockerExecutor:
    """DockerExecutor protocol with the hot-read face on the SDK."""

    def __init__(self, client: Any = None):
        self._client = client
        from aisc.adapters.docker_ import RealDockerExecutor

        self._cli = RealDockerExecutor()

    # -- SDK client ------------------------------------------------------

    def _sdk(self) -> Any:
        if self._client is None:
            from aisc.adapters.docker_gateway import _default_client

            self._client = _default_client()
        return self._client

    # -- structured hot ops ----------------------------------------------

    def preflight(self) -> DockerPreflightResult:
        try:
            self._sdk().ping()
            return DockerPreflightResult(
                docker_path="(sdk)", available=True, reason="ok"
            )
        except Exception:  # noqa: BLE001 — SDK unusable: CLI may still be
            return self._cli.preflight()

    def inspect_container(self, container_name: str) -> ProcessResult:
        try:
            data = self._sdk().api.inspect_container(container_name)
            return ProcessResult(
                stdout=json.dumps([data]), stderr="", exit_code=0
            )
        except Exception as exc:  # noqa: BLE001
            import docker.errors

            if isinstance(exc, docker.errors.NotFound):
                return ProcessResult(
                    stdout="",
                    stderr=f"Error: No such object: {container_name}",
                    exit_code=1,
                )
            # Transient/unknown: CLI fallback preserves today's semantics.
            return self._cli.inspect_container(container_name)

    # -- free argv: map the three hot shapes, CLI for the rest ------------

    def run_captured(
        self,
        docker_argv: List[str],
        *,
        timeout: Optional[float] = None,
        input_text: Optional[str] = None,
    ) -> ProcessResult:
        try:
            if docker_argv and docker_argv[0] == "ps":
                mapped = self._run_ps(docker_argv)
                if mapped is not None:
                    return mapped
            elif docker_argv and docker_argv[0] == "exec":
                mapped = self._run_exec(docker_argv)
                if mapped is not None:
                    return mapped
            elif docker_argv and docker_argv[0] == "inspect" and len(docker_argv) == 2:
                return self.inspect_container(docker_argv[1])
        except Exception:  # noqa: BLE001 — any mapping trouble: CLI path
            pass
        return self._cli.run_captured(
            docker_argv, timeout=timeout, input_text=input_text
        )

    def _run_ps(self, argv: List[str]) -> Optional[ProcessResult]:
        filters: Dict[str, List[str]] = {}
        template: Optional[str] = None
        all_flag = False
        i = 1
        while i < len(argv):
            a = argv[i]
            if a in ("-a", "--all"):
                all_flag = True
            elif a == "--filter" and i + 1 < len(argv):
                f = argv[i + 1]
                if not f.startswith("label="):
                    return None  # non-label filters unmapped → CLI
                filters.setdefault("label", []).append(f[len("label=") :])
                i += 1
            elif a == "--format" and i + 1 < len(argv):
                template = argv[i + 1]
                i += 1
            elif a.startswith("-"):
                return None  # unknown flag → CLI
            i += 1
        if template is None:
            return None
        containers = self._sdk().containers.list(all=all_flag, filters=filters or None)
        lines = []
        for c in containers:
            line = _render_ps_line(template, c)
            if line is None:
                return None
            lines.append(line)
        return ProcessResult(stdout="\n".join(lines), stderr="", exit_code=0)

    def _run_exec(self, argv: List[str]) -> Optional[ProcessResult]:
        # Plain `exec <name> <cmd...>` only — flags (-e/-u/-w/...) between
        # "exec" and the container name are unmapped (the command TAIL may
        # contain anything, including dash-prefixed tool args like --json).
        if len(argv) < 3 or argv[1].startswith("-"):
            return None
        container_name, cmd = argv[1], argv[2:]
        api = self._sdk().api
        exec_id = api.exec_create(container_name, cmd, stdout=True, stderr=True)
        sock = api.exec_start(exec_id, socket=False, tty=False)
        if hasattr(sock, "read"):
            raw = sock.read() or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8", "replace")
        else:
            raw = b""
        info = api.exec_inspect(exec_id)
        return ProcessResult(
            stdout=raw.decode("utf-8", "replace"),
            stderr="",
            exit_code=int(info.get("ExitCode", 0) or 0),
        )

    # -- everything else: verbatim CLI delegation --------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__.get("_cli"), name)


def default_executor() -> Any:
    """Command-layer executor factory (PERF P4).

    ``AISC_DOCKER_EXECUTOR=cli`` restores the pure-CLI executor; tests pass
    their own ``executor`` as before (the factory only feeds the ``or``
    default)."""
    if os.environ.get("AISC_DOCKER_EXECUTOR", "").lower() == "cli":
        from aisc.adapters.docker_ import RealDockerExecutor

        return RealDockerExecutor()
    return SdkBackedDockerExecutor()
