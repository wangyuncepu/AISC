"""Environment tool probing for the Stage 0 baseline manifest.

Every subprocess goes through an injectable ``run`` callable so tests can fake
missing tools / versions without touching the real toolchain. Python itself is
read from the running interpreter (``sys.version``) and never shelled out.

Results are plain ``ToolInfo`` objects with an ``error`` set when the tool is
missing, timed out, or its output cannot be parsed; the caller decides whether
an error makes the baseline ``incomplete``.
"""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class ToolInfo:
    name: str
    version: Optional[str]
    path: Optional[str]
    error: Optional[str] = None


# Minimal subprocess-like result contract (compatible with CompletedProcess).
class ProcResult:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


RunFn = Callable[[List[str]], object]


def _run_captured(argv: List[str]) -> object:
    """Run *argv* with a 15s cap and UTF-8 text; timeouts yield returncode 124."""
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return ProcResult("", returncode=124)


def real_run(argv: List[str]) -> object:
    """Default runner that works across Git-Bash / POSIX shim setups.

    Python cannot execute a POSIX shim (no-extension ``npm``/``git``) or a
    ``.cmd`` directly via CreateProcess, so we resolve ``.exe`` first and fall
    back to ``bash -lc`` — the shell the AISC dev environment actually uses.
    """
    resolved = shutil.which(argv[0])
    if resolved is not None:
        candidate = [resolved, *argv[1:]]
        try:
            return _run_captured(candidate)
        except Exception:  # noqa: BLE001 - fall through to the shell
            pass

    # Login-shell fallback resolves Git-for-Windows shims and .cmd wrappers.
    return _run_captured(["bash", "-lc", shlex.join(argv)])


def _parse_first_field(stdout: str) -> Optional[str]:
    text = stdout.strip()
    if not text:
        return None
    return text.split()[0]


def _parse_node(stdout: str) -> Optional[str]:
    text = stdout.strip().lstrip("v")
    return text or None


def _parse_rustc(stdout: str) -> Optional[str]:
    fields = stdout.strip().split()
    return fields[1] if len(fields) >= 2 else None


def _parse_cargo(stdout: str) -> Optional[str]:
    fields = stdout.strip().split()
    return fields[1] if len(fields) >= 2 else None


def _parse_docker(stdout: str) -> Optional[str]:
    text = stdout.strip()
    if "version" not in text:
        return text or None
    return text.split("version", 1)[1].strip().split(",")[0].strip()


def _parse_aisc(stdout: str) -> Optional[str]:
    try:
        envelope = json.loads(stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    return envelope.get("meta", {}).get("version")


# (tool name, argv, version parser). Python is handled separately.
_TOOL_SPECS = [
    ("node", ["node", "--version"], _parse_node),
    ("npm", ["npm", "--version"], _parse_first_field),
    ("rustc", ["rustc", "--version"], _parse_rustc),
    ("cargo", ["cargo", "--version"], _parse_cargo),
    ("docker", ["docker", "--version"], _parse_docker),
    ("aisc", ["aisc", "version", "--format", "json"], _parse_aisc),
]


def probe_all(run: Optional[RunFn] = None) -> Dict[str, ToolInfo]:
    """Probe every supported tool, returning ``{name: ToolInfo}``.

    Python is reported from ``sys``. Missing/unparsable tools carry an
    ``error`` and a ``None`` version so callers can compute completeness.
    """
    runner = run or real_run
    tools: Dict[str, ToolInfo] = {
        "python": ToolInfo("python", sys.version.split()[0], sys.executable),
    }

    for name, argv, parser in _TOOL_SPECS:
        try:
            result = runner(argv)
        except FileNotFoundError:
            tools[name] = ToolInfo(name, None, None, "command not found")
            continue
        except Exception as exc:  # noqa: BLE001 - probe must never crash the baseline
            tools[name] = ToolInfo(name, None, None, f"probe error: {exc}")
            continue

        stdout = getattr(result, "stdout", None)
        if not isinstance(stdout, str):
            tools[name] = ToolInfo(name, None, None, "unreadable output")
            continue

        version = parser(stdout)
        if version is None:
            tools[name] = ToolInfo(name, None, None, "unparsable output")
            continue

        executable = None
        if isinstance(result, subprocess.CompletedProcess) and result.args:
            executable = result.args[0]
        tools[name] = ToolInfo(name, version, executable)

    return tools


def collect_os_info() -> Dict[str, str]:
    """Return OS name/arch/release; arch and release can be None on odd platforms."""
    return {
        "name": platform.system() or None,
        "arch": platform.machine() or None,
        "release": platform.release() or None,
    }
