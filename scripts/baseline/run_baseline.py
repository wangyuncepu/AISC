"""Stage 0 baseline CLI: probe the environment and write a deterministic manifest.

Usage:
    python scripts/baseline/run_baseline.py --out <dir> [--fixtures <dir>]
        [--env KEY ...] [--command CMD ...] [--strict]

Behavior:
- Always writes ``<out>/baseline.json`` for the current run.
- Writes ``<out>/latest.json`` only when the probe is ``complete`` — a failed
  baseline never overwrites a previously PASSed marker (B-A01/B-A02).
- ``--strict`` turns an incomplete probe into a non-zero exit.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# Make sibling modules importable whether run as `python scripts/baseline/run_baseline.py`
# (cwd on sys.path) or loaded via importlib by the test suite.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from probe import probe_all, real_run, collect_os_info  # noqa: E402
from manifest import build_manifest, fixture_hashes, toolchain_payload  # noqa: E402


DEFAULT_COMMANDS = [
    "python -m pytest tests -q",
    "cargo test --manifest-path workbench/src-tauri/Cargo.toml",
    "npm --prefix workbench test -- --run",
]

# Tools whose absence does NOT make the baseline incomplete (aisc CLI may live
# only as a Workbench sidecar and not be on PATH).
NON_CRITICAL_TOOLS = {"aisc"}


class BaselineIncomplete(Exception):
    """Raised in strict mode when the probe reports missing critical tools."""


def _git_field(argv: List[str], run) -> Optional[str]:
    try:
        result = run(["git", *argv])
    except Exception:
        return None
    stdout = getattr(result, "stdout", None)
    if not isinstance(stdout, str):
        return None
    text = stdout.strip()
    return text or None


def run_baseline(
    *,
    out_dir: Path,
    commands: List[str],
    env_allowlist: Dict[str, Optional[str]],
    fixture_dir: Optional[Path] = None,
    strict: bool = False,
    generated_at: Optional[str] = None,
    run=None,
) -> Dict[str, object]:
    """Probe the environment and write the baseline manifest files."""
    runner = run or real_run

    tools = probe_all(run=runner)
    toolchain = toolchain_payload(tools)

    missing = [name for name, tool in tools.items()
               if tool.error and name not in NON_CRITICAL_TOOLS]
    git_commit = _git_field(["rev-parse", "HEAD"], runner)
    git_branch = _git_field(["rev-parse", "--abbrev-ref", "HEAD"], runner)

    probe_status = "complete" if not missing and git_commit else "incomplete"

    os_info = collect_os_info()
    manifest = build_manifest(
        git_commit=git_commit,
        git_branch=git_branch,
        os_name=os_info["name"],
        os_arch=os_info["arch"],
        os_release=os_info["release"],
        toolchain=toolchain,
        commands=commands,
        env_allowlist=env_allowlist,
        fixture_hashes=fixture_hashes(fixture_dir),
        probe_status=probe_status,
        generated_at=generated_at,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    import json

    (out_dir / "baseline.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )

    if probe_status == "complete":
        (out_dir / "latest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
    elif strict:
        raise BaselineIncomplete(", ".join(missing) if missing else "git unavailable")

    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_baseline.py",
        description="Probe environment and write a deterministic baseline manifest",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--fixtures", type=Path, default=None, help="Fixture directory to hash")
    parser.add_argument("--env", action="append", default=None,
                        help="Environment variable name to record (allowlist); repeatable")
    parser.add_argument("--command", action="append", default=None,
                        help="Locked command to record; repeatable")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero when critical tools are missing")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv or sys.argv[1:])
    commands = args.command or DEFAULT_COMMANDS
    env_allowlist = {key: os.environ.get(key) for key in (args.env or [])}
    try:
        run_baseline(
            out_dir=args.out,
            commands=commands,
            env_allowlist=env_allowlist,
            fixture_dir=args.fixtures,
            strict=args.strict,
        )
    except BaselineIncomplete as exc:
        print(f"baseline incomplete: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
