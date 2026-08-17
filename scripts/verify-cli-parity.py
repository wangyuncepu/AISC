#!/usr/bin/env python3
"""CLI-A05/A06 dual-track parity runner.

Runs the same command matrix against two AISC CLI binaries — typically the
pip-installed console script (fresh venv) and the PyInstaller frozen sidecar —
and asserts they agree on:

- exit code (and, where pinned, the exact expected value),
- stable error code (errors[0].code),
- the JSON envelope (deep-equal after normalizing the dynamic meta.timestamp
  and meta.run_id fields),
- human-readable stdout/stderr for text-mode commands.

Any difference between the two CLIs, or a JSON-requested command that fails to
emit a JSON envelope, FAILs the run (CLI-A05). Commands that need a live
Docker runtime carry ``expected_exit=None``: the runner still asserts the two
CLIs agree, it just does not pin a specific exit code.

Usage::

    python scripts/verify-cli-parity.py --cli-a <pip-aisc.exe> --cli-b <sidecar-aisc.exe>

Exit 0 on full PASS; non-zero with a diagnostic on any difference.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Optional

PROTOCOL = "aisc.cli/v1"
# Envelope fields that legitimately differ run to run.
DYNAMIC_META = ("timestamp", "run_id")
# Dynamic fields inside `data` (e.g. runtime list's "observed at" wall clock).
DYNAMIC_DATA_FIELDS = ("observed_at",)


# (argv, expected_exit | None, expect_json)
# expected_exit=None -> compare the two CLIs only (docker-dependent command).
MATRIX: list[tuple[list[str], Optional[int], bool]] = [
    # --- version: normal, flag placement, equals-form, text ---
    (["version", "--format", "json"], 0, True),
    (["version", "--format=json"], 0, True),
    (["--format", "json", "version"], 0, True),  # global flag before command
    (["version"], 0, False),
    (["version", "--help"], 0, False),
    # --- parse errors: unknown command / bad format / extra flag ---
    (["definitely_not_a_command", "--format", "json"], 2, True),
    # invalid --format VALUE: the CLI cannot know JSON was requested, so the
    # usage error is text (exit 2) — parity still asserted on stdout/stderr.
    (["version", "--format", "bogus"], 2, False),
    (["version", "--format", "json", "--extra-flag"], 2, True),
    # --- bare grouped command -> text help, exit 0 ---
    (["runtime"], 0, False),
    (["runtime", "--format", "json"], 0, False),
    # --- missing required args -> JSON usage error (CLI-A02/A05) ---
    (["runtime", "inspect", "--format", "json"], 2, True),
    (["runtime", "preflight", "--format", "json"], 2, True),
    (["runtime", "stop", "--format", "json"], 2, True),
    (["runtime", "restart", "--format", "json"], 2, True),
    (["runtime", "remove", "--format", "json"], 2, True),
    (["session", "list", "--format", "json"], 2, True),
    (["session", "terminate", "--format", "json"], 2, True),
    (["provider", "current", "--agent", "claude", "--format", "json"], 2, True),
    # --- invalid runtime-id -> stable code, no docker ---
    (["runtime", "inspect", "--runtime-id", "not-a-uuid", "--format", "json"], 15, True),
    (["runtime", "preflight", "--runtime-id", "not-a-uuid", "--format", "json"], 15, True),
    (["provider", "current", "--runtime-id", "not-a-uuid", "--agent", "claude", "--format", "json"], 15, True),
    (["session", "terminate", "--runtime-id", "not-a-uuid", "--session-id", "not-a-uuid", "--format", "json"], 15, True),
    # --- host-dependent diagnostics: compare the two CLIs only ---
    # doctor's exit code reflects host checks (docker presence etc.) and differs
    # by platform (0 with docker, non-zero on runners without a live daemon);
    # the parity contract is that pip and sidecar AGREE, not a pinned value.
    (["doctor", "--format", "json"], None, True),
    (["runtime", "list", "--format", "json"], None, True),
    (["ps", "--format", "json"], None, True),
]


def _run(cli: str, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([cli, *argv], capture_output=True, text=True)


def _normalize(env: dict) -> dict:
    for key in DYNAMIC_META:
        env.get("meta", {}).pop(key, None)
    data = env.get("data")
    if isinstance(data, dict):
        for key in DYNAMIC_DATA_FIELDS:
            data.pop(key, None)
    return env


def _compare(cmd: str, a: subprocess.CompletedProcess, b: subprocess.CompletedProcess,
             expected_exit: Optional[int], expect_json: bool) -> Optional[str]:
    if a.returncode != b.returncode:
        return f"exit mismatch: A={a.returncode} B={b.returncode}"
    if expected_exit is not None and a.returncode != expected_exit:
        return f"unexpected exit {a.returncode} (expected {expected_exit})"

    a_out, b_out = a.stdout, b.stdout
    if expect_json:
        try:
            a_env = json.loads(a_out)
        except json.JSONDecodeError:
            return f"CLI-A did not emit JSON for {cmd!r}: {a_out[:200]!r}"
        try:
            b_env = json.loads(b_out)
        except json.JSONDecodeError:
            return f"CLI-B did not emit JSON for {cmd!r}: {b_out[:200]!r}"
        if a_env.get("meta", {}).get("protocol") != PROTOCOL:
            return f"CLI-A wrong protocol for {cmd!r}: {a_env.get('meta', {}).get('protocol')!r}"
        if _normalize(a_env) != _normalize(b_env):
            return f"envelope mismatch for {cmd!r}:\n  A={json.dumps(_normalize(a_env), ensure_ascii=True)}\n  B={json.dumps(_normalize(b_env), ensure_ascii=True)}"
        # stable error code agrees
        a_code = (a_env.get("errors") or [{}])[0].get("code")
        b_code = (b_env.get("errors") or [{}])[0].get("code")
        if a_code != b_code:
            return f"error-code mismatch for {cmd!r}: A={a_code!r} B={b_code!r}"
    else:
        if a_out != b_out:
            return f"text stdout mismatch for {cmd!r}:\n  A={a_out[:200]!r}\n  B={b_out[:200]!r}"
        if a.stderr != b.stderr:
            return f"text stderr mismatch for {cmd!r}:\n  A={a.stderr[:200]!r}\n  B={b.stderr[:200]!r}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cli-a", required=True, help="first CLI executable (e.g. pip console script)")
    ap.add_argument("--cli-b", required=True, help="second CLI executable (e.g. PyInstaller sidecar)")
    args = ap.parse_args()

    failed = 0
    for argv, expected_exit, expect_json in MATRIX:
        cmd = " ".join(argv)
        a = _run(args.cli_a, argv)
        b = _run(args.cli_b, argv)
        problem = _compare(cmd, a, b, expected_exit, expect_json)
        if problem:
            print(f"FAIL [{cmd}]: {problem}")
            # Divergence triage on host-dependent commands: print both raw
            # outputs so CI logs show WHAT differed (7f gate finding: an
            # exit mismatch alone gave no signal).
            print(f"  A rc={a.returncode} out={a.stdout[:400]!r} err={a.stderr[:200]!r}")
            print(f"  B rc={b.returncode} out={b.stdout[:400]!r} err={b.stderr[:200]!r}")
            failed += 1
        else:
            suffix = "" if expected_exit is None else f" (exit {expected_exit})"
            print(f"ok   [{cmd}]{suffix}")

    if failed:
        print(f"\nCLI-A05 PARITY FAILED: {failed} command(s) differ")
        raise SystemExit(1)
    print("\nCLI-A05 PASS: pip CLI and sidecar agree on all matrix commands")


if __name__ == "__main__":
    main()
