#!/usr/bin/env python3
"""CLI-A08 dependency SBOM + integrity audit for the aisc CLI.

Loads a built wheel, reads its declared dependencies, runs ``pip check`` in
the install environment for dependency integrity, and emits an SBOM (JSON) of
the installed distribution versions.

Usage::

    python scripts/verify-sbom.py --wheel <aisc.whl> --venv-python <venv/bin/python>

Exit 0 when the integrity check passes; non-zero with a diagnostic otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

SCHEMA_VERSION = 1


def wheel_requires_dist(wheel: Path) -> list[str]:
    """Parse the wheel's METADATA for Requires-Dist entries (direct deps)."""
    with zipfile.ZipFile(wheel) as z:
        metadata_name = next(
            n for n in z.namelist() if n.endswith(".dist-info/METADATA")
        )
        metadata = z.read(metadata_name).decode("utf-8")
    return [
        line.split(": ", 1)[1]
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:")
    ]


def pip_check(venv_python: Path) -> list[str]:
    proc = subprocess.run(
        [str(venv_python), "-m", "pip", "check"],
        capture_output=True, text=True,
    )
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        return []
    # Broken requirements are reported one per line after a header.
    lines = [l for l in out.splitlines() if " - " in l and "has requirement" in l]
    return lines or [out]


def installed_sbom(venv_python: Path) -> list[dict]:
    proc = subprocess.run(
        [str(venv_python), "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pip list failed: {proc.stderr}")
    rows = json.loads(proc.stdout)
    return sorted(rows, key=lambda r: r["name"].lower())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wheel", type=Path, required=True, help="built aisc wheel")
    ap.add_argument("--venv-python", type=Path, required=True,
                    help="python of the install environment (for pip check/list)")
    ap.add_argument("--out", type=Path, default=None, help="write SBOM JSON here")
    args = ap.parse_args()

    requires = wheel_requires_dist(args.wheel)
    problems = pip_check(args.venv_python)
    installed = installed_sbom(args.venv_python)

    sbom = {
        "schema_version": SCHEMA_VERSION,
        "project": "aisc",
        "wheel": args.wheel.name,
        "declared_dependencies": requires,
        "installed": installed,
        "integrity_ok": not problems,
        "integrity_errors": problems,
    }
    text = json.dumps(sbom, ensure_ascii=True, indent=2)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)

    if problems:
        print(f"\nCLI-A08 SBOM FAILED: {len(problems)} broken requirement(s)", file=sys.stderr)
        raise SystemExit(1)
    print(f"\nCLI-A08 SBOM PASS: {len(installed)} packages installed, integrity ok")


if __name__ == "__main__":
    main()
