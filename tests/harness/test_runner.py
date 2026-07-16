"""Test harness: RunResult, CliRunner, and JSON/JSONL protocol helpers.

Pure stdlib — zero external dependencies.  Designed to be reused by S2+ tests.

Protocol assertions follow ``docs/rfc/aisc-cli-v1.md`` (``aisc.cli/v1``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# RunResult & CliRunner
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Result of a subprocess execution captured by CliRunner."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class CliRunner:
    """Run subprocess commands for testing, capturing stdout / stderr / exit code.

    Usage::

        runner = CliRunner()
        result = runner.run(["bash", "myscript.sh"], cwd=tmpdir, timeout=5.0)
        assert result.exit_code == 0
    """

    def run(
        self,
        args: List[str],
        *,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        input_text: Optional[str] = None,
        env_clear: bool = False,
    ) -> RunResult:
        """Execute *args* in a subprocess and return a ``RunResult``.

        Args:
            args: Command and arguments (list of strings).
            env: Extra environment variables.  By default merged with
                ``os.environ``.  When *env_clear* is ``True``, only given vars
                plus platform-essential ones are used.
            cwd: Working directory for the child process.
            timeout: Timeout in seconds (float).  On expiry returns
                ``RunResult(timed_out=True, exit_code=-1)``.
            input_text: Text piped to the child's stdin.
            env_clear: If ``True``, start from a minimal environment (``PATH`` +
                platform essentials) and only add the given *env* on top.
        """
        run_env: Optional[Dict[str, str]] = None
        if env_clear:
            run_env = self._minimal_env()
            if env:
                run_env.update(env)
        elif env is not None:
            run_env = os.environ.copy()
            run_env.update(env)

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=run_env,
                input=input_text,
                timeout=timeout,
            )
            return RunResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return RunResult(stdout="", stderr="", exit_code=-1, timed_out=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _minimal_env() -> Dict[str, str]:
        """Minimal environment for isolated subprocess execution.

        Cross-platform design — preserves essential vars on both Linux and
        Windows so that basic shell / interpreter operations work, but
        discards leaked parent-process state.
        """
        env: Dict[str, str] = {}

        # Always keep PATH so executables / shells can be found
        if "PATH" in os.environ:
            env["PATH"] = os.environ["PATH"]

        if sys.platform == "win32":
            # Windows essentials — keep the OS functional inside subprocess
            for _k in (
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "COMSPEC",
                "PATHEXT",
                "WINDIR",
                "USERPROFILE",
                "APPDATA",
                "LOCALAPPDATA",
                "PROGRAMFILES",
                "PROGRAMFILES(X86)",
                "PROGRAMDATA",
                "HOMEDRIVE",
                "HOMEPATH",
                "OS",
            ):
                if _k in os.environ:
                    env[_k] = os.environ[_k]
        else:
            # Unix essentials
            for _k in ("HOME", "USER", "SHELL", "LANG", "LC_ALL"):
                if _k in os.environ:
                    env[_k] = os.environ[_k]

        return env


# ---------------------------------------------------------------------------
# JSON / JSONL protocol assertion helpers  (aisc.cli/v1)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def parse_json(text: str) -> Any:
    """Parse *text* as JSON.  Returns the parsed object or ``None``."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def parse_json_envelope(text: str) -> Optional[Dict[str, Any]]:
    """Parse *text* as a complete JSON envelope (RFC §2).

    **Strict**: ``json.loads(text)`` — no prefix/suffix extraction.
    The entire *text* must be a single, valid JSON object.

    Returns the parsed dict, or ``None`` if *text* is not valid JSON
    or the top-level value is not a dict.
    """
    data = parse_json(text)
    if isinstance(data, dict):
        return data
    return None


def parse_jsonl(text: str) -> List[Any]:
    """Parse newline-delimited JSON (JSONL) text.

    Returns a list where each element is the parsed object for that line, or
    ``None`` for lines that are not valid JSON.  Blank / whitespace-only lines
    are silently skipped.
    """
    results: List[Any] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        results.append(parse_json(stripped))
    return results


# ---------------------------------------------------------------------------
# JSON Envelope assertion  (RFC §2, §7.1)
# ---------------------------------------------------------------------------

def _is_nonempty_str(val: Any) -> bool:
    return isinstance(val, str) and len(val) > 0


def assert_json_envelope(
    result: RunResult,
    expected_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate ``result.stdout`` as an RFC-compliant JSON envelope.

    Checks enforced (``aisc.cli/v1``, RFC §2):

    * stdout is a valid JSON object (strict — no prefix/suffix text).
    * ``meta`` dict present.
    * ``meta.protocol == "aisc.cli/v1"``.
    * ``meta.command`` non-empty string.
    * ``meta.exit_code`` is ``int`` and **equals ``result.exit_code``**.
    * ``meta.timestamp`` non-empty string.
    * ``meta.version`` non-empty string.
    * ``meta.run_id`` non-empty string.
    * ``data`` is ``dict`` or ``None``.
    * ``errors`` is ``list``.
    * Success (``exit_code == 0``) → ``errors`` must be ``[]``.
    * Failure (``exit_code != 0``) → ``errors`` must have ≥ 1 item; each
      item is a dict with ``code``, ``message``, ``hint`` (hint may be
      ``None``).

    When *expected_fields* is provided, each key/value pair is asserted
    against the **top-level** parsed dict as an additional check.

    Returns the parsed dict for further assertions.
    Raises ``AssertionError`` on any protocol violation.
    """
    # 1. Strict JSON parse — stdout must be pure JSON
    data = parse_json_envelope(result.stdout)
    assert data is not None, (
        f"stdout is not a valid JSON envelope (strict): {result.stdout[:200]!r}"
    )

    # 2. meta dict
    meta = data.get("meta")
    assert isinstance(meta, dict), (
        f"'meta' missing or not a dict; got {type(meta).__name__}"
    )

    # 2a. meta.protocol
    assert meta.get("protocol") == "aisc.cli/v1", (
        f"meta.protocol: expected 'aisc.cli/v1', got {meta.get('protocol')!r}"
    )

    # 2b. meta.command — non-empty string
    cmd = meta.get("command")
    assert _is_nonempty_str(cmd), (
        f"meta.command: must be non-empty string, got {cmd!r}"
    )

    # 2c. meta.exit_code — int, equals process exit code
    meta_exit = meta.get("exit_code")
    assert isinstance(meta_exit, int), (
        f"meta.exit_code: must be int, got {type(meta_exit).__name__} ({meta_exit!r})"
    )
    assert meta_exit == result.exit_code, (
        f"meta.exit_code {meta_exit} != process exit_code {result.exit_code}"
    )

    # 2d. meta.timestamp — non-empty string
    ts = meta.get("timestamp")
    assert _is_nonempty_str(ts), (
        f"meta.timestamp: must be non-empty string, got {ts!r}"
    )

    # 2e. meta.version — non-empty string
    ver = meta.get("version")
    assert _is_nonempty_str(ver), (
        f"meta.version: must be non-empty string, got {ver!r}"
    )

    # 2f. meta.run_id — non-empty string
    rid = meta.get("run_id")
    assert _is_nonempty_str(rid), (
        f"meta.run_id: must be non-empty string, got {rid!r}"
    )

    # 3. data — dict or None
    payload = data.get("data")
    assert payload is None or isinstance(payload, dict), (
        f"'data': must be dict or null, got {type(payload).__name__}"
    )

    # 4. errors — list
    errs = data.get("errors")
    assert isinstance(errs, list), (
        f"'errors': must be list, got {type(errs).__name__}"
    )

    # 5. success vs failure semantics
    if result.exit_code == 0:
        assert len(errs) == 0, (
            f"success (exit_code=0) requires empty errors, got {len(errs)} items"
        )
    else:
        assert len(errs) >= 1, (
            f"failure (exit_code={result.exit_code}) requires ≥ 1 error, got {len(errs)}"
        )
        for i, err in enumerate(errs):
            assert isinstance(err, dict), (
                f"errors[{i}]: must be dict, got {type(err).__name__}"
            )
            assert isinstance(err.get("code"), str), (
                f"errors[{i}].code: must be string, got {err.get('code')!r}"
            )
            assert isinstance(err.get("message"), str), (
                f"errors[{i}].message: must be string, got {err.get('message')!r}"
            )
            # hint may be string or None
            hint = err.get("hint")
            assert hint is None or isinstance(hint, str), (
                f"errors[{i}].hint: must be string or null, got {hint!r}"
            )

    # 6. Optional top-level additional assertions
    if expected_fields:
        for key, val in expected_fields.items():
            actual = data.get(key)
            assert actual == val, (
                f"top-level field {key!r}: expected {val!r}, got {actual!r}"
            )

    return data


# ---------------------------------------------------------------------------
# JSONL Event Stream assertion  (RFC §3, §7.2)
# ---------------------------------------------------------------------------

# The seven required fields per JSONL event (RFC §3.2)
_JSONL_REQUIRED_FIELDS = ("protocol", "command", "run_id", "seq", "type", "ts", "data")


def assert_jsonl_protocol(
    lines: List[Any],
    *,
    expect_exit_code: Optional[int] = None,
) -> None:
    """Validate a JSONL protocol stream per RFC §3.

    Checks enforced:

    * Every entry is a ``dict`` with 7 required fields:
      ``protocol``, ``command``, ``run_id``, ``seq``, ``type``, ``ts``, ``data``.
    * ``protocol == "aisc.cli/v1"`` on every line.
    * ``command`` and ``run_id`` are strings and consistent across the stream.
    * ``seq`` is ``int``, starts at **1**, and increments by exactly **1**
      each line (strictly monotonic +1).
    * ``type`` is ``string``, ``ts`` is ``string``.
    * ``data`` is a ``dict``.
    * **Exactly one terminal event** — the **last line** — whose ``type``
      matches ``<command>.complete``, ``<command>.failed``, or
      ``<command>.cancelled`` (RFC §3.4).
    * ``data.exit_code`` in the terminal must be ``int``, and when
      *expect_exit_code* is given, must equal it.

    .. note::

        ``build.step.complete`` is **not** a terminal — only exact matches
        against ``{command}.{{complete,failed,cancelled}}`` qualify.

    Raises ``AssertionError`` on any protocol violation.
    """
    assert len(lines) > 0, "JSONL stream is empty"

    command: Optional[str] = None
    run_id: Optional[str] = None
    terminals: List[Dict[str, Any]] = []
    terminal_indices: List[int] = []

    for i, obj in enumerate(lines):
        # -- must be dict -------------------------------------------------
        assert obj is not None, f"line {i}: not valid JSON"
        assert isinstance(obj, dict), (
            f"line {i}: not a JSON object, got {type(obj).__name__}"
        )

        # -- 7 required fields --------------------------------------------
        for field in _JSONL_REQUIRED_FIELDS:
            assert field in obj, f"line {i}: missing required field '{field}'"

        # -- protocol -----------------------------------------------------
        assert obj["protocol"] == "aisc.cli/v1", (
            f"line {i}: protocol must be 'aisc.cli/v1', got {obj['protocol']!r}"
        )

        # -- command consistency ------------------------------------------
        assert isinstance(obj["command"], str), (
            f"line {i}: 'command' must be string, got {type(obj['command']).__name__}"
        )
        if command is None:
            command = obj["command"]
        else:
            assert obj["command"] == command, (
                f"line {i}: command changed from {command!r} to {obj['command']!r}"
            )

        # -- run_id consistency -------------------------------------------
        assert isinstance(obj["run_id"], str), (
            f"line {i}: 'run_id' must be string, got {type(obj['run_id']).__name__}"
        )
        if run_id is None:
            run_id = obj["run_id"]
        else:
            assert obj["run_id"] == run_id, (
                f"line {i}: run_id changed from {run_id!r} to {obj['run_id']!r}"
            )

        # -- seq — starts at 1, increments by 1 ---------------------------
        seq = obj["seq"]
        assert isinstance(seq, int), (
            f"line {i}: 'seq' must be int, got {type(seq).__name__}"
        )
        expected_seq = i + 1  # 1-based, increment by 1 each line
        assert seq == expected_seq, (
            f"line {i}: expected seq={expected_seq}, got seq={seq}"
        )

        # -- type / ts ----------------------------------------------------
        assert isinstance(obj["type"], str), (
            f"line {i}: 'type' must be string, got {type(obj['type']).__name__}"
        )
        assert isinstance(obj["ts"], str), (
            f"line {i}: 'ts' must be string, got {type(obj['ts']).__name__}"
        )

        # -- data must be dict --------------------------------------------
        assert isinstance(obj["data"], dict), (
            f"line {i}: 'data' must be dict, got {type(obj['data']).__name__}"
        )

        # -- terminal detection (RFC §3.4) --------------------------------
        # Terminal types: <command>.complete / .failed / .cancelled
        terminal_types = {
            f"{command}.complete",
            f"{command}.failed",
            f"{command}.cancelled",
        }
        if obj["type"] in terminal_types:
            terminals.append(obj)
            terminal_indices.append(i)

    # -- exactly one terminal, must be the last line ----------------------
    assert len(terminals) == 1, (
        f"expected exactly 1 terminal event, got {len(terminals)} "
        f"(indices {terminal_indices})"
    )
    assert terminal_indices[0] == len(lines) - 1, (
        f"terminal event must be the last line (idx {terminal_indices[0]}), "
        f"but stream has {len(lines)} lines"
    )

    # -- terminal exit_code -----------------------------------------------
    term = terminals[0]
    term_exit = term["data"].get("exit_code")
    assert isinstance(term_exit, int), (
        f"terminal data.exit_code must be int, got {type(term_exit).__name__} ({term_exit!r})"
    )

    if expect_exit_code is not None:
        assert term_exit == expect_exit_code, (
            f"terminal data.exit_code {term_exit} != expected {expect_exit_code}"
        )
