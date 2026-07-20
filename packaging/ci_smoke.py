#!/usr/bin/env python3
"""CI smoke helper for workflow artifact validation — cross-platform, stdlib-only.

Usage:
    python3 packaging/ci_smoke.py --executable PATH --expected-version-file VERSION
    python3 packaging/ci_smoke.py --archive-dir DIR
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

_PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ))

_artifact = None


def _get_artifact():
    global _artifact
    if _artifact is None:
        import importlib.util as _iu
        spec = _iu.spec_from_file_location("aisc_artifact", _PROJ / "packaging" / "artifact.py")
        if spec is None or spec.loader is None:
            sys.exit("ERROR: cannot load packaging/artifact.py")
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _artifact = mod
    return _artifact


def _find_single_archive(archive_dir: Path) -> Path:
    art = _get_artifact()
    candidates = sorted(
        p for p in archive_dir.iterdir()
        if p.is_file() and p.name.startswith("AISC-") and not p.name.endswith(".sha256")
    )
    # Only accept names recognised by _parse_archive_name
    valid = [c for c in candidates if art._parse_archive_name(c.name) is not None]
    if len(valid) == 0:
        sys.exit(f"ERROR: No valid AISC archive found in {archive_dir} (had {len(candidates)} candidates)")
    if len(valid) > 1:
        sys.exit(f"ERROR: Multiple AISC archives in {archive_dir}: {[c.name for c in valid]}")
    return valid[0]


def _smoke_onedir(executable: Path, expected_version_file: Path) -> None:
    expected = expected_version_file.read_text(encoding="utf-8").strip().split("\n")[0].strip()
    print(f"Expected version: {expected}")

    def run(cmd, desc):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"FAIL [{desc}]: exit {r.returncode}")
            if r.stderr: print(f"  stderr: {r.stderr[:300]}")
            sys.exit(1)
        print(f"PASS [{desc}]")
        return r

    run([str(executable), "version"], "version text")
    r = run([str(executable), "version", "--format", "json"], "version JSON")
    data = json.loads(r.stdout)
    cli_ver = data.get("data", {}).get("cli_version", "")
    print(f"  cli_version = {cli_ver}")
    if cli_ver != expected:
        print(f"FAIL [version guard]: expected {expected}, got {cli_ver}")
        sys.exit(1)
    print("PASS [version guard]: matches VERSION")


def _smoke_archive(archive_path: Path) -> None:
    art = _get_artifact()

    # 1. Structural verify
    print(f"=== Verifying archive: {archive_path.name} ===")
    errors = art.verify_archive(archive_path)
    if errors:
        for e in errors: print(f"  ERR: {e}")
        sys.exit(1)
    print("Archive structural verification: PASSED")

    # 2. Extract safely using artifact's public helper
    smoke_dir = Path(tempfile.mkdtemp(prefix="aisc-ci-smoke-"))
    try:
        extract_errors = art.safe_extract_archive(archive_path, smoke_dir)
        if extract_errors:
            for e in extract_errors: print(f"  ERR: extract - {e}")
            sys.exit(1)

        top_dirs = list(smoke_dir.iterdir())
        if len(top_dirs) != 1:
            print(f"ERROR: expected 1 top-level dir, got {len(top_dirs)}")
            sys.exit(1)
        top_dir = top_dirs[0]
        exe_name = "aisc.exe" if sys.platform == "win32" else "aisc"
        exe = top_dir / exe_name
        bundle = top_dir / "aisc-bundle"
        if not exe.is_file(): print(f"ERROR: executable not found: {exe_name}"); sys.exit(1)
        if not bundle.is_dir(): print("ERROR: aisc-bundle/ not found"); sys.exit(1)

        expected_version = (bundle / "VERSION").read_text(encoding="utf-8").strip().split("\n")[0].strip()
        print(f"Expected version (from bundle): {expected_version}")

        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "AISC_ROOT")}

        def run(cmd, desc, check=True):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env, cwd=str(smoke_dir))
            if check and r.returncode != 0:
                print(f"FAIL [{desc}]: exit {r.returncode}")
                if r.stderr: print(f"  stderr: {r.stderr[:300]}")
                sys.exit(1)
            print(f"PASS [{desc}]")
            return r

        run([str(exe), "version"], "version text")
        r = run([str(exe), "version", "--format", "json"], "version JSON")
        data = json.loads(r.stdout)
        cli_ver = data.get("data", {}).get("cli_version", "")
        if cli_ver != expected_version:
            print(f"FAIL [version guard]: cli_version={cli_ver} != expected={expected_version}")
            sys.exit(1)
        print(f"  version guard: OK ({cli_ver} == {expected_version})")

        run([str(exe), "build", "--dry-run"], "build --dry-run text")

        r = run([str(exe), "build", "--dry-run", "--format", "json"], "build --dry-run JSON")
        bd = json.loads(r.stdout)
        docker_argv = bd.get("data", {}).get("docker_argv", [])
        bundle_str = str(bundle.resolve())
        ok = True
        if "-f" in docker_argv:
            idx = docker_argv.index("-f")
            df_path = docker_argv[idx + 1]
            if bundle_str not in str(Path(df_path).resolve()) and "aisc-bundle" not in df_path:
                print(f"FAIL [build JSON path]: Dockerfile not in bundle: {df_path}"); ok = False
            else: print(f"  build context OK: Dockerfile at {df_path}")
        bc = docker_argv[-1] if docker_argv else ""
        if bundle_str not in str(Path(bc).resolve()) and "aisc-bundle" not in bc:
            print(f"FAIL [build JSON context]: not pointing to bundle: {bc}"); ok = False
        else: print(f"  build context OK: {bc}")
        if not ok: sys.exit(1)

        r = run([str(exe), "build", "--dry-run", "--events"], "build --dry-run events")
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        if not lines: print("FAIL [events]: no JSONL output"); sys.exit(1)
        events = []
        for l in lines:
            try: events.append(json.loads(l))
            except json.JSONDecodeError: print(f"FAIL [events]: invalid JSON line: {l[:80]}"); sys.exit(1)
        for i, ev in enumerate(events):
            if ev.get("seq", -1) != i + 1: print(f"FAIL [events]: seq={ev.get('seq')} expected {i+1}"); sys.exit(1)
        lt = events[-1].get("type", "")
        if not lt.endswith(".complete"): print(f"FAIL [events]: last event type={lt}"); sys.exit(1)
        le = events[-1].get("data", {}).get("exit_code")
        if le != 0: print(f"FAIL [events]: terminal exit_code={le}"); sys.exit(1)
        print(f"  events OK: {len(events)} events, terminal={lt}")

        # negative
        bundle_away = top_dir / "aisc-bundle-away"
        shutil.move(str(bundle), str(bundle_away))
        try:
            r = subprocess.run([str(exe), "build", "--dry-run"], capture_output=True, text=True, timeout=30, env=env, cwd=str(smoke_dir))
            if r.returncode == 0: print("FAIL [negative]: build succeeded without bundle"); sys.exit(1)
            print(f"PASS [negative]: correctly failed (exit {r.returncode})")
        finally:
            shutil.move(str(bundle_away), str(bundle))

        print("=== ALL SMOKE PASSED ===")
    finally:
        shutil.rmtree(smoke_dir, ignore_errors=True)


def main():
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--executable"); p.add_argument("--expected-version-file"); p.add_argument("--archive-dir")
    args = p.parse_args()
    if args.executable and args.expected_version_file:
        _smoke_onedir(Path(args.executable), Path(args.expected_version_file))
    elif args.archive_dir:
        _smoke_archive(_find_single_archive(Path(args.archive_dir)))
    else:
        p.print_help(); sys.exit("ERROR: specify --executable + --expected-version-file, or --archive-dir")


if __name__ == "__main__":
    main()
